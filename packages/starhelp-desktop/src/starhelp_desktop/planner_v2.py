"""Isolated stdio bridge for the explicit local producer v0.2 protocol."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from uuid import UUID

from .distribution_state import DistributionSecurityStore
from .lifecycle import ProfileLifecycle
from .planner import PlannerCancelled, PlannerResult, PlannerUnavailable, _stop_process
from .producer_v2 import (
    MAX_REQUEST_BYTES,
    build_public_basis_sha256,
    canonical_json_bytes,
    load_execution_policy,
    validate_inner_request_v2,
    validate_execution_policy_context,
)


PROTOCOL_ID_V2 = "starhelp-local-planner"
PROTOCOL_VERSION_V2 = "0.2"
MAX_RESPONSE_BYTES_V2 = 16 * 1024 * 1024
REQUIRED_CAPABILITIES_V2 = frozenset({
    "starhelp.producers.v0.2", "starhelp.public-basis.v1", "starhelp.request-producer.v1",
})


@dataclass(frozen=True, slots=True)
class LocalProducerV2Process:
    """Run one v0.2 request using a fixed command, without a legacy fallback path."""

    command: tuple[str, ...]
    execution_policy_path: Path
    execution_policy_sha256: str
    timeout_seconds: float = 30.0
    max_request_bytes: int = MAX_REQUEST_BYTES
    max_response_bytes: int = MAX_RESPONSE_BYTES_V2

    def __post_init__(self) -> None:
        if not self.command or any(not part or "\x00" in part for part in self.command):
            raise ValueError("v0.2 worker command must be an explicit argument list")
        if not 0 < self.max_request_bytes <= MAX_REQUEST_BYTES:
            raise ValueError("v0.2 request byte limit exceeds the frozen maximum")
        if not 0 < self.max_response_bytes <= MAX_RESPONSE_BYTES_V2:
            raise ValueError("v0.2 response byte limit exceeds the frozen maximum")
        if not 0 < self.timeout_seconds <= 600:
            raise ValueError("v0.2 worker timeout must be between 0 and 600 seconds")

    def analyze(self, *, request: dict[str, Any], profile_id: UUID,
                authorization_generation: int, lifecycle: ProfileLifecycle,
                security_state: DistributionSecurityStore) -> PlannerResult:
        _validate_outer_v2(request, profile_id, authorization_generation,
                           security_state, self.max_request_bytes)
        policy = load_execution_policy(
            self.execution_policy_path, expected_sha256=self.execution_policy_sha256
        )
        try:
            validate_execution_policy_context(policy, request["producer_request"])
        except (KeyError, TypeError, ValueError):
            raise PlannerUnavailable("v0.2 execution policy does not admit this request") from None
        persistent = security_state.snapshot()
        policy_context = policy["context"]
        if (policy_context["safety_state"] != persistent["safety_state"]
                or policy_context["known_revoked_releases"] != persistent["known_revoked_releases"]
                or policy_context["known_revoked_public_refs"] != persistent[
                    "known_revoked_public_refs"
                ]):
            raise PlannerUnavailable("v0.2 execution policy is stale versus host security state")
        payload = canonical_json_bytes(request) + b"\n"
        worker_command = (*self.command, "--execution-policy", str(self.execution_policy_path),
                          "--execution-policy-sha256", self.execution_policy_sha256)
        cancel = lifecycle.register_task(profile_id, authorization_generation)
        process: subprocess.Popen[bytes] | None = None
        try:
            process = subprocess.Popen(
                worker_command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, shell=False, close_fds=True,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
            output = bytearray()
            too_large = threading.Event()
            errors: list[BaseException] = []

            def write_request() -> None:
                try:
                    assert process is not None and process.stdin is not None
                    if cancel.is_set() or not lifecycle.is_active(profile_id, authorization_generation):
                        process.stdin.close()
                        return
                    process.stdin.write(payload)
                    process.stdin.close()
                except (BrokenPipeError, OSError, ValueError) as exc:
                    errors.append(exc)

            def read_response() -> None:
                try:
                    assert process is not None and process.stdout is not None
                    while chunk := process.stdout.read(64 * 1024):
                        if len(output) + len(chunk) > self.max_response_bytes:
                            too_large.set()
                            return
                        output.extend(chunk)
                except (OSError, ValueError) as exc:
                    errors.append(exc)

            writer = threading.Thread(target=write_request, name="starhelp-v02-stdin", daemon=True)
            reader = threading.Thread(target=read_response, name="starhelp-v02-stdout", daemon=True)
            writer.start()
            reader.start()
            deadline = time.monotonic() + self.timeout_seconds
            while process.poll() is None:
                if cancel.is_set() or not lifecycle.is_active(profile_id, authorization_generation):
                    _stop_process(process)
                    raise PlannerCancelled("v0.2 analysis cancelled after authorization changed")
                if too_large.is_set():
                    _stop_process(process)
                    raise PlannerUnavailable("local_payload_too_large")
                if time.monotonic() >= deadline:
                    _stop_process(process)
                    raise PlannerUnavailable("v0.2 local planner timed out")
                time.sleep(0.025)
            writer.join(timeout=0.5)
            reader.join(timeout=0.5)
            if too_large.is_set():
                raise PlannerUnavailable("local_payload_too_large")
            if errors or process.returncode != 0:
                raise PlannerUnavailable("v0.2 local planner stdio exchange failed")
            lifecycle.require_active(profile_id, authorization_generation)
            response = _parse_response_v2(bytes(output), request)
            epoch = request["producer_request"]["public_basis"]["epoch"]
            security_state.run_if_epoch_current(epoch, lambda: None)
            return response
        except PlannerCancelled:
            raise
        except PermissionError as exc:
            raise PlannerCancelled("v0.2 result rejected after authorization changed") from exc
        except PlannerUnavailable:
            raise
        except (OSError, ValueError, UnicodeError, RecursionError) as exc:
            raise PlannerUnavailable("v0.2 local planner is unavailable or returned invalid data") from exc
        finally:
            if process is not None:
                if process.poll() is None:
                    _stop_process(process)
                for stream in (process.stdin, process.stdout):
                    if stream is not None:
                        stream.close()
            lifecycle.unregister_task(profile_id, authorization_generation, cancel)


def _validate_outer_v2(request: Any, profile_id: UUID, generation: int,
                       security_state: DistributionSecurityStore, max_bytes: int) -> None:
    if not isinstance(request, dict) or set(request) != {
        "schema_id", "schema_version", "request_id", "authorization_generation",
        "account_snapshot", "producer_request",
    }:
        raise PlannerUnavailable("v0.2 outer request has missing or unknown fields")
    if request["schema_id"] != "AnalysisRequest" or request["schema_version"] != "0.2":
        raise PlannerUnavailable("unsupported local planner protocol; legacy fallback is disabled")
    if (not isinstance(request["request_id"], str) or not request["request_id"]
            or request["authorization_generation"] != generation
            or isinstance(request["authorization_generation"], bool)):
        raise PlannerUnavailable("v0.2 request identity or generation is invalid")
    snapshot = request["account_snapshot"]
    if not isinstance(snapshot, dict) or set(snapshot) != {
        "profile_id", "snapshot_revision", "authorization_generation", "authorization_state",
    }:
        raise PlannerUnavailable("v0.2 snapshot summary has missing or unknown fields")
    if (snapshot["profile_id"] != str(profile_id) or snapshot["authorization_generation"] != generation
            or snapshot["authorization_state"] != "active"):
        raise PlannerUnavailable("v0.2 snapshot does not match active authorization")
    if (not isinstance(snapshot["snapshot_revision"], int)
            or isinstance(snapshot["snapshot_revision"], bool) or snapshot["snapshot_revision"] < 1):
        raise PlannerUnavailable("v0.2 snapshot revision is invalid")
    try:
        inner = validate_inner_request_v2(request["producer_request"])
    except (KeyError, TypeError, ValueError) as exc:
        raise PlannerUnavailable(f"v0.2 producer request rejected: {exc}") from None
    if inner["request_id"] != request["request_id"]:
        raise PlannerUnavailable("v0.2 outer and inner request IDs differ")
    if inner["authorization_context"] != {
        "profile_id": str(profile_id), "active": True, "generation": generation,
    }:
        raise PlannerUnavailable("v0.2 inner authorization context differs from outer request")
    snapshot_data = json.loads(inner["account_snapshot"]["raw_json"])
    if (snapshot_data.get("revision") != snapshot["snapshot_revision"]
            or snapshot_data.get("profile_id") != str(profile_id)):
        raise PlannerUnavailable("v0.2 raw snapshot differs from outer snapshot summary")
    basis = inner["public_basis"]
    if inner["public_basis_sha256"] != build_public_basis_sha256(basis):
        raise PlannerUnavailable("v0.2 public basis digest mismatch")
    if len(canonical_json_bytes(request)) + 1 > max_bytes:
        raise PlannerUnavailable("local_payload_too_large")
    state = security_state.snapshot()
    if state["safety_state"] != "ready" or state["pending"]:
        raise PlannerUnavailable(state["safety_state"])
    if state["public_epoch"] != basis["epoch"]:
        raise PlannerUnavailable("public_basis_changed")


def _parse_response_v2(data: bytes, request: dict[str, Any]) -> PlannerResult:
    if not data:
        raise PlannerUnavailable("v0.2 local planner returned no result")
    try:
        envelope = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise PlannerUnavailable("v0.2 local planner returned invalid JSON") from None
    if not isinstance(envelope, dict) or set(envelope) != {
        "protocol", "protocol_version", "planner_version", "capabilities", "result",
    }:
        raise PlannerUnavailable("v0.2 response envelope has missing or unknown fields")
    if envelope["protocol"] != PROTOCOL_ID_V2 or envelope["protocol_version"] != PROTOCOL_VERSION_V2:
        raise PlannerUnavailable("local planner protocol version is incompatible")
    capabilities = envelope["capabilities"]
    result = envelope["result"]
    if (not isinstance(envelope["planner_version"], str) or not envelope["planner_version"]
            or not isinstance(capabilities, list) or any(not isinstance(x, str) for x in capabilities)
            or not isinstance(result, dict)):
        raise PlannerUnavailable("v0.2 planner response is malformed")
    if not REQUIRED_CAPABILITIES_V2.issubset(capabilities):
        raise PlannerUnavailable("v0.2 planner lacks required capabilities")
    inner = request["producer_request"]
    basis = inner["public_basis"]
    expected_feedback = inner.get("feedback")
    expected = {
        "request_id": request["request_id"],
        "request_producer": inner["request_producer"],
        "request_sha256": hashlib.sha256(canonical_json_bytes(inner)).hexdigest(),
        "feedback_sha256": hashlib.sha256(canonical_json_bytes(expected_feedback)).hexdigest(),
        "public_basis_sha256": inner["public_basis_sha256"],
        "public_epoch": basis["epoch"],
        "snapshot_revision": request["account_snapshot"]["snapshot_revision"],
        "authorization_generation": request["authorization_generation"],
        "adapter_profile": "starhelp.producers.v0.2",
    }
    if any(result.get(key) != value for key, value in expected.items()):
        raise PlannerUnavailable("v0.2 planner result correlation or digest mismatch")
    return PlannerResult(envelope["planner_version"], frozenset(capabilities), result)
