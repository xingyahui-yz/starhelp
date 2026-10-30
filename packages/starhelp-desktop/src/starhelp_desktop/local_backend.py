"""Owned local A-service lifecycle controller for the first, loopback-only phase."""

from __future__ import annotations

import ctypes
import hashlib
import json
import os
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from uuid import uuid4


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request: Any, fp: Any, code: int, msg: str, headers: Any,
                         new_url: str) -> None:
        return None


@dataclass(frozen=True, slots=True)
class BackendHealth:
    pid: int | None
    application_version: str | None
    schema_version: str | None
    readiness: str
    active_release_id: str | None
    last_error_code: str | None = None


@dataclass(frozen=True, slots=True)
class BackendStartResult:
    started: bool
    health: BackendHealth
    instance_id: str | None


@dataclass(frozen=True, slots=True)
class LocalBackendConfig:
    executable: Path
    executable_sha256: str
    application_version: str
    database_path: Path
    distribution_store: Path
    port: int = 8765
    start_timeout_seconds: float = 15.0
    request_timeout_seconds: float = 0.75
    command_prefix: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if len(self.executable_sha256) != 64 or any(
            char not in "0123456789abcdef" for char in self.executable_sha256
        ):
            raise ValueError("local A executable SHA-256 must be lowercase hex")
        if not self.application_version or not 1 <= self.port <= 65535:
            raise ValueError("local A version or port is invalid")
        if not 0 < self.start_timeout_seconds <= 120 or not 0 < self.request_timeout_seconds <= 10:
            raise ValueError("local A controller timeout is outside the supported range")
        if any(not part or "\x00" in part for part in self.command_prefix):
            raise ValueError("local A command prefix is invalid")


class KnowledgeBackendController:
    """Starts only its configured, digest-pinned A executable and owns its process handle."""

    def __init__(self, config: LocalBackendConfig) -> None:
        self._config = config
        self._lock = threading.RLock()
        self._process: subprocess.Popen[bytes] | None = None
        self._instance_id: str | None = None
        self._creation_time: float | None = None
        self._opener = urllib.request.build_opener(_NoRedirect())

    def start(self) -> BackendStartResult:
        with self._lock:
            if self._process is not None and self._process.poll() is None:
                health = self.health()
                if health.readiness == "ready":
                    return BackendStartResult(False, health, self._instance_id)
                raise RuntimeError("owned A process is running but not ready")
            if self._port_is_in_use():
                raise RuntimeError("local A port is already occupied; external process was not touched")
            path = self._config.executable.resolve(strict=True)
            if hashlib.sha256(path.read_bytes()).hexdigest() != self._config.executable_sha256:
                raise RuntimeError("local A executable digest mismatch")
            instance_id = str(uuid4())
            command = [
                str(path), *self._config.command_prefix, "serve",
                "--database", str(self._config.database_path.resolve()),
                "--host", "127.0.0.1", "--port", str(self._config.port),
                "--distribution-store", str(self._config.distribution_store.resolve()),
                "--instance-id", instance_id,
            ]
            flags = 0
            if os.name == "nt":
                flags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0) | getattr(
                    subprocess, "CREATE_NO_WINDOW", 0
                )
            self._process = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL, shell=False, close_fds=True, creationflags=flags,
            )
            self._instance_id = instance_id
            try:
                self._creation_time = _process_creation_time(self._process)
            except OSError:
                self._owned_stop(0.1)
                raise RuntimeError("could not establish ownership of the local A process") from None
            deadline = time.monotonic() + self._config.start_timeout_seconds
            last_error = "readiness_timeout"
            while time.monotonic() < deadline:
                if self._process.poll() is not None:
                    self._owned_stop(0.1)
                    raise RuntimeError("local A process exited before readiness")
                try:
                    payload = self._fetch_json("/health/ready")
                    self._validate_readiness(payload, instance_id)
                    return BackendStartResult(
                        True, self._health_from_payload(payload, self._process.pid), instance_id
                    )
                except (OSError, ValueError, urllib.error.URLError):
                    last_error = "readiness_unavailable"
                    time.sleep(0.1)
            self._owned_stop(0.5)
            raise RuntimeError(last_error)

    def health(self) -> BackendHealth:
        with self._lock:
            process = self._process
            if process is None or process.poll() is not None:
                return BackendHealth(None, None, None, "stopped", None)
            try:
                payload = self._fetch_json("/health/ready")
                self._validate_readiness(payload, self._instance_id)
                return self._health_from_payload(payload, process.pid)
            except (OSError, ValueError, urllib.error.URLError):
                return BackendHealth(process.pid, None, None, "not_ready", None,
                                     "readiness_unavailable")

    def stop(self, grace_seconds: float = 5.0) -> BackendHealth:
        if not 0 <= grace_seconds <= 60:
            raise ValueError("grace period must be between 0 and 60 seconds")
        with self._lock:
            process = self._process
            if process is None:
                return BackendHealth(None, None, None, "stopped", None)
            self._owned_stop(grace_seconds)
            return BackendHealth(None, None, None, "stopped", None)

    def _owned_stop(self, grace_seconds: float) -> None:
        process = self._process
        if process is None:
            return
        # Popen retains the original OS process handle, preventing PID reuse from redirecting stop.
        if process.poll() is None:
            try:
                if os.name == "nt":
                    process.send_signal(getattr(subprocess, "CTRL_BREAK_EVENT", 1))
                else:
                    process.terminate()
            except (OSError, ValueError):
                pass
            try:
                process.wait(timeout=grace_seconds)
            except subprocess.TimeoutExpired:
                process.terminate()
                try:
                    process.wait(timeout=1)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
        if process.poll() is not None:
            self._process = None
            self._instance_id = None
            self._creation_time = None

    def _fetch_json(self, route: str) -> dict[str, Any]:
        url = f"http://127.0.0.1:{self._config.port}{route}"
        request = urllib.request.Request(url, headers={"Accept": "application/json"}, method="GET")
        with self._opener.open(request, timeout=self._config.request_timeout_seconds) as response:
            if response.status != 200 or response.headers.get("Content-Encoding", "identity") != "identity":
                raise ValueError("local A health response is not an identity-encoded 200")
            raw = response.read(16 * 1024 + 1)
        if len(raw) > 16 * 1024:
            raise ValueError("local A health response exceeds the size limit")
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict):
            raise ValueError("local A health response must be an object")
        return value

    def _validate_readiness(self, payload: dict[str, Any], instance_id: str | None) -> None:
        required = {
            "status", "service", "application_version", "schema_version", "database",
            "migration", "active_release_id", "distribution_catalog", "checked_at", "instance_id",
        }
        if (set(payload) != required or payload["status"] != "ready"
                or payload["service"] != "starhelp-knowledge"
                or payload["application_version"] != self._config.application_version
                or payload["instance_id"] != instance_id
                or payload["database"] != "ready" or payload["migration"] != "current"
                or payload["distribution_catalog"] != "available"
                or not isinstance(payload["schema_version"], str)
                or not isinstance(payload["active_release_id"], str)
                or not payload["active_release_id"]):
            raise ValueError("local A readiness identity or dependencies do not match")
        checked = payload["checked_at"]
        if not isinstance(checked, str) or not checked.endswith("Z"):
            raise ValueError("local A readiness timestamp is invalid")
        try:
            datetime.fromisoformat(checked[:-1] + "+00:00")
        except ValueError:
            raise ValueError("local A readiness timestamp is invalid") from None

    @staticmethod
    def _health_from_payload(payload: dict[str, Any], pid: int | None) -> BackendHealth:
        return BackendHealth(
            pid, payload["application_version"], payload["schema_version"],
            payload["status"], payload["active_release_id"], None,
        )

    def _port_is_in_use(self) -> bool:
        try:
            with socket.create_connection(("127.0.0.1", self._config.port), timeout=0.2):
                return True
        except OSError:
            return False


def _process_creation_time(process: subprocess.Popen[bytes]) -> float:
    if os.name != "nt":
        return time.time()

    class _FileTime(ctypes.Structure):
        _fields_ = [("low", ctypes.c_uint32), ("high", ctypes.c_uint32)]

    creation, exit_time, kernel_time, user_time = _FileTime(), _FileTime(), _FileTime(), _FileTime()
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    get_times = kernel32.GetProcessTimes
    get_times.argtypes = [ctypes.c_void_p, ctypes.POINTER(_FileTime), ctypes.POINTER(_FileTime),
                          ctypes.POINTER(_FileTime), ctypes.POINTER(_FileTime)]
    get_times.restype = ctypes.c_int
    handle = getattr(process, "_handle", None)
    if handle is None or not get_times(handle, ctypes.byref(creation), ctypes.byref(exit_time),
                                       ctypes.byref(kernel_time), ctypes.byref(user_time)):
        raise ctypes.WinError(ctypes.get_last_error())
    ticks = (creation.high << 32) | creation.low
    return ticks / 10_000_000 - 11_644_473_600
