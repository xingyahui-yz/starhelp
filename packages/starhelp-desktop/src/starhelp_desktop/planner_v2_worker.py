"""Strict stdio entry point for the pinned C 0.5.1 producer v0.2 artifact."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

from .planner_v2 import (
    MAX_RESPONSE_BYTES_V2,
    PROTOCOL_ID_V2,
    PROTOCOL_VERSION_V2,
)
from .producer_v2 import MAX_REQUEST_BYTES

PLANNER_V2_VERSION = "0.5.1"
PLANNER_V2_WHEEL_SHA256 = "c79ceb58e78d11cf947c0c9f7c5c862ccad8155886fab715a76f7d8977f98322"
MAX_POLICY_BYTES = 2 * 1024 * 1024


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _decode_object(data: bytes, label: str) -> dict[str, Any]:
    value = json.loads(
        data.decode("utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _load_planner() -> tuple[Any, ...]:
    if not getattr(sys, "frozen", False):
        wheel = (
            Path(__file__).resolve().parents[2]
            / "packaging"
            / "vendor"
            / "starhelp_planner-0.5.1-py3-none-any.whl"
        )
        if hashlib.sha256(wheel.read_bytes()).hexdigest() != PLANNER_V2_WHEEL_SHA256:
            raise ValueError("pinned planner wheel digest mismatch")
        sys.path.insert(0, str(wheel))
    from starhelp_planner import (
        COMPONENT_VERSION,
        PRODUCER_V2_CAPABILITIES,
        analyze_producers_v2,
        validate_execution_policy,
        validate_outer_request_v2,
    )

    if COMPONENT_VERSION != PLANNER_V2_VERSION:
        raise ValueError("pinned planner version mismatch")
    return (COMPONENT_VERSION, PRODUCER_V2_CAPABILITIES, analyze_producers_v2,
            validate_execution_policy, validate_outer_request_v2)


def _read_policy(path: str, expected_sha256: str, validate: Any) -> dict[str, Any]:
    if len(expected_sha256) != 64 or any(c not in "0123456789abcdef" for c in expected_sha256):
        raise ValueError("execution policy digest is invalid")
    with Path(path).open("rb") as stream:
        raw = stream.read(MAX_POLICY_BYTES + 1)
    if len(raw) > MAX_POLICY_BYTES or hashlib.sha256(raw).hexdigest() != expected_sha256:
        raise ValueError("execution policy digest or size is invalid")
    return validate(_decode_object(raw, "execution policy"))


def _run(data: bytes, *, policy_path: str, policy_sha256: str) -> bytes:
    if len(data) > MAX_REQUEST_BYTES:
        raise ValueError("local_payload_too_large")
    (component_version, capabilities, analyze, validate_policy,
     validate_outer) = _load_planner()
    policy = _read_policy(policy_path, policy_sha256, validate_policy)
    outer = _decode_object(data, "producer request")
    inner = validate_outer(outer, execution_policy=policy)
    result = analyze(inner, execution_policy=policy)
    envelope = {
        "protocol": PROTOCOL_ID_V2,
        "protocol_version": PROTOCOL_VERSION_V2,
        "planner_version": component_version,
        "capabilities": sorted(capabilities),
        "result": result,
    }
    encoded = json.dumps(
        envelope, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8") + b"\n"
    if len(encoded) > MAX_RESPONSE_BYTES_V2:
        raise ValueError("local_payload_too_large")
    return encoded


def main() -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--execution-policy", required=True)
    parser.add_argument("--execution-policy-sha256", required=True)
    try:
        args = parser.parse_args()
        data = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
        sys.stdout.buffer.write(_run(
            data, policy_path=args.execution_policy,
            policy_sha256=args.execution_policy_sha256,
        ))
        sys.stdout.buffer.flush()
    except Exception:
        # The local worker has no diagnostic channel for request or policy contents.
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
