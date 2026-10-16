from __future__ import annotations

import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from .lifecycle import ProfileLifecycle

PROTOCOL_ID = "starhelp-local-planner"
PROTOCOL_VERSION = "0.1-draft"
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_RESPONSE_BYTES = 16 * 1024 * 1024


class PlannerUnavailable(RuntimeError):
    """The selected local planner could not complete a compatible analysis."""


class PlannerCancelled(PlannerUnavailable):
    """The profile was revoked or the analysis was otherwise cancelled."""


@dataclass(frozen=True, slots=True)
class PlannerResult:
    planner_version: str
    capabilities: frozenset[str]
    result: dict[str, Any]


@dataclass(frozen=True, slots=True)
class LocalPlannerProcess:
    """Explicit, same-user planner executable and its declared compatibility needs."""

    command: tuple[str, ...]
    required_capabilities: frozenset[str]
    timeout_seconds: float = 30.0
    max_request_bytes: int = MAX_REQUEST_BYTES
    max_response_bytes: int = MAX_RESPONSE_BYTES

    def __post_init__(self) -> None:
        if not self.command or any(not part or "\x00" in part for part in self.command):
            raise ValueError("planner command must be an explicit non-empty argument list")
        if self.timeout_seconds <= 0 or self.timeout_seconds > 600:
            raise ValueError("planner timeout must be between 0 and 600 seconds")
        if not 0 < self.max_request_bytes <= MAX_REQUEST_BYTES:
            raise ValueError("planner request limit is outside the supported range")
        if not 0 < self.max_response_bytes <= MAX_RESPONSE_BYTES:
            raise ValueError("planner response limit is outside the supported range")

    def analyze(
        self,
        *,
        request: dict[str, Any],
        profile_id: UUID,
        authorization_generation: int,
        lifecycle: ProfileLifecycle,
    ) -> PlannerResult:
        """Send one complete local request over stdio; never persist or log its contents."""
        _validate_request_envelope(request, profile_id, authorization_generation)
        payload = json.dumps(request, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
        request_bytes = payload.encode("utf-8") + b"\n"
        if len(request_bytes) > self.max_request_bytes:
            raise PlannerUnavailable("analysis request exceeds the local planner size limit")

        cancel = lifecycle.register_task(profile_id, authorization_generation)
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                self.command,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                shell=False,
                close_fds=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
            output = bytearray()
            output_limit_hit = threading.Event()
            io_errors: list[BaseException] = []

            def write_request() -> None:
                try:
                    assert process is not None and process.stdin is not None
                    if cancel.is_set() or not lifecycle.is_active(
                        profile_id, authorization_generation
                    ):
                        process.stdin.close()
                        return
                    process.stdin.write(request_bytes)
                    process.stdin.close()
                except (BrokenPipeError, OSError, ValueError) as exc:
                    io_errors.append(exc)

            def read_response() -> None:
                try:
                    assert process is not None and process.stdout is not None
                    while True:
                        chunk = process.stdout.read(64 * 1024)
                        if not chunk:
                            return
                        if len(output) + len(chunk) > self.max_response_bytes:
                            output_limit_hit.set()
                            return
                        output.extend(chunk)
                except (OSError, ValueError) as exc:
                    io_errors.append(exc)

            writer = threading.Thread(target=write_request, name="starhelp-planner-stdin", daemon=True)
            reader = threading.Thread(target=read_response, name="starhelp-planner-stdout", daemon=True)
            writer.start()
            reader.start()
            deadline = time.monotonic() + self.timeout_seconds
            while process.poll() is None:
                if cancel.is_set() or not lifecycle.is_active(profile_id, authorization_generation):
                    _stop_process(process)
                    raise PlannerCancelled("analysis cancelled because profile authorization is inactive")
                if output_limit_hit.is_set():
                    _stop_process(process)
                    raise PlannerUnavailable("planner response exceeds the local size limit")
                if time.monotonic() >= deadline:
                    _stop_process(process)
                    raise PlannerUnavailable("local planner timed out")
                time.sleep(0.025)
            writer.join(timeout=0.5)
            reader.join(timeout=0.5)
            if output_limit_hit.is_set():
                raise PlannerUnavailable("planner response exceeds the local size limit")
            if io_errors:
                raise PlannerUnavailable("local planner stdio exchange failed") from None
            if process.returncode != 0:
                raise PlannerUnavailable("local planner exited with an error")
            lifecycle.require_active(profile_id, authorization_generation)
            return _parse_response(bytes(output), self.required_capabilities, request)
        except PlannerUnavailable:
            raise
        except PermissionError as exc:
            raise PlannerCancelled("analysis result rejected because profile authorization changed") from exc
        except (OSError, ValueError) as exc:
            raise PlannerUnavailable("local planner is unavailable or returned invalid data") from exc
        finally:
            if process is not None:
                if process.poll() is None:
                    _stop_process(process)
                for stream in (process.stdin, process.stdout):
                    if stream is not None:
                        stream.close()
            lifecycle.unregister_task(profile_id, authorization_generation, cancel)


def _validate_request_envelope(
    request: dict[str, Any], profile_id: UUID, generation: int
) -> None:
    if not isinstance(request, dict) or request.get("schema_id") != "AnalysisRequest":
        raise ValueError("planner input must be a complete AnalysisRequest object")
    if request.get("contract_version") != PROTOCOL_VERSION:
        raise ValueError("analysis request contract version is incompatible")
    if request.get("schema_version") != PROTOCOL_VERSION:
        raise ValueError("analysis request schema version is incompatible")
    if not isinstance(request.get("request_id"), str) or not request["request_id"]:
        raise ValueError("analysis request must have an id")
    if request.get("authorization_generation") != generation:
        raise PermissionError("analysis request generation does not match the authorization")
    snapshot = request.get("account_snapshot")
    if not isinstance(snapshot, dict):
        raise ValueError("analysis request must embed the account snapshot")
    if snapshot.get("profile_id") != str(profile_id):
        raise PermissionError("analysis request profile does not match the authorized profile")
    if snapshot.get("authorization_generation") != generation:
        raise PermissionError("analysis request generation does not match the authorization")
    if snapshot.get("authorization_state") != "active":
        raise PermissionError("analysis request profile authorization is inactive")
    if (not isinstance(snapshot.get("snapshot_revision"), int)
            or isinstance(snapshot.get("snapshot_revision"), bool)):
        raise ValueError("analysis request snapshot revision is required")
    if not isinstance(request.get("public_bundle"), dict):
        raise ValueError("analysis request must embed one complete public bundle")
    if not isinstance(request.get("task"), dict):
        raise ValueError("analysis request must embed its local task constraints")


def _parse_response(
    data: bytes, required: frozenset[str], request: dict[str, Any]
) -> PlannerResult:
    if not data:
        raise PlannerUnavailable("local planner returned no result")
    try:
        envelope = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise PlannerUnavailable("local planner returned invalid JSON") from None
    if not isinstance(envelope, dict):
        raise PlannerUnavailable("local planner returned an invalid response envelope")
    if envelope.get("protocol") != PROTOCOL_ID or envelope.get("protocol_version") != PROTOCOL_VERSION:
        raise PlannerUnavailable("local planner protocol version is incompatible")
    planner_version = envelope.get("planner_version")
    capabilities = envelope.get("capabilities")
    result = envelope.get("result")
    if not isinstance(planner_version, str) or not planner_version.strip():
        raise PlannerUnavailable("local planner did not declare its version")
    if not isinstance(capabilities, list) or any(not isinstance(item, str) for item in capabilities):
        raise PlannerUnavailable("local planner capabilities are malformed")
    if not isinstance(result, dict):
        raise PlannerUnavailable("local planner result is malformed")
    missing = required - set(capabilities)
    if missing:
        raise PlannerUnavailable("local planner lacks required capabilities")
    snapshot = request["account_snapshot"]
    if result.get("request_id") != request["request_id"]:
        raise PlannerUnavailable("local planner result belongs to a different request")
    if result.get("snapshot_revision") != snapshot["snapshot_revision"]:
        raise PlannerUnavailable("local planner result belongs to a different account snapshot")
    if result.get("authorization_generation") != snapshot["authorization_generation"]:
        raise PlannerUnavailable("local planner result belongs to a different authorization generation")
    return PlannerResult(planner_version, frozenset(capabilities), result)


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=1)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
