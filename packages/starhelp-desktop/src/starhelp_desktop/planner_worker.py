from __future__ import annotations

import hashlib
import importlib
import json
import sys
from pathlib import Path
from typing import Any

from .planner import PROTOCOL_ID, PROTOCOL_VERSION, MAX_REQUEST_BYTES, MAX_RESPONSE_BYTES

PLANNER_WHEEL_SHA256 = "f7b6c5c221e2491c9399ed76656945175961ac94188b11ad2fe4d4160d0aa0ca"


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON number")


def _decode_json(data: bytes) -> dict[str, Any]:
    value = json.loads(
        data.decode("utf-8"),
        object_pairs_hook=_unique_object,
        parse_constant=_reject_constant,
    )
    if not isinstance(value, dict):
        raise ValueError("planner request must be a JSON object")
    return value


def _load_planner() -> tuple[Any, str, str]:
    """Load only the pinned planner wheel, or its verified installed package in a frozen app."""
    wheel = (
        Path(__file__).resolve().parents[2]
        / "packaging"
        / "vendor"
        / "starhelp_planner-0.3.0-py3-none-any.whl"
    )
    if wheel.is_file():
        digest = hashlib.sha256(wheel.read_bytes()).hexdigest()
        if digest != PLANNER_WHEEL_SHA256:
            raise RuntimeError("pinned planner wheel digest mismatch")
        sys.path.insert(0, str(wheel))
    module = importlib.import_module("starhelp_planner")
    component_version = getattr(module, "COMPONENT_VERSION", None)
    adapter_profile = getattr(module, "PRODUCER_ADAPTER_PROFILE", None)
    if component_version != "0.3.0" or adapter_profile != "starhelp.producers.v0.1":
        raise RuntimeError("local planner artifact version or profile is unsupported")
    return module, component_version, adapter_profile


def _validate_wrapper(wrapper: dict[str, Any]) -> dict[str, Any]:
    if wrapper.get("schema_id") != "AnalysisRequest":
        raise ValueError("unsupported desktop planner request")
    if (
        wrapper.get("contract_version") != PROTOCOL_VERSION
        or wrapper.get("schema_version") != PROTOCOL_VERSION
    ):
        raise ValueError("unsupported desktop planner protocol")
    request_id = wrapper.get("request_id")
    generation = wrapper.get("authorization_generation")
    snapshot = wrapper.get("account_snapshot")
    producer_request = wrapper.get("producer_request")
    if not isinstance(request_id, str) or not request_id:
        raise ValueError("planner request id is missing")
    if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
        raise ValueError("planner authorization generation is invalid")
    if not isinstance(snapshot, dict) or not isinstance(producer_request, dict):
        raise ValueError("complete local producer request is required")
    if producer_request.get("schema_id") != "ProducerAnalysisRequest":
        raise ValueError("unsupported producer adapter request")
    if producer_request.get("schema_version") != "0.1":
        raise ValueError("unsupported producer adapter schema")
    if producer_request.get("request_id") != request_id:
        raise ValueError("desktop and producer request IDs differ")
    auth = producer_request.get("authorization_context")
    source_snapshot = producer_request.get("account_snapshot")
    source_bundle = producer_request.get("public_bundle")
    if (
        not isinstance(auth, dict)
        or not isinstance(source_snapshot, dict)
        or not isinstance(source_bundle, dict)
    ):
        raise ValueError("producer request is missing authorization or source objects")
    if auth.get("active") is not True or auth.get("generation") != generation:
        raise ValueError("producer authorization does not match active desktop authorization")
    if auth.get("profile_id") != snapshot.get("profile_id"):
        raise ValueError("producer snapshot does not match the active desktop profile")
    raw_snapshot = source_snapshot.get("raw_json")
    raw_bundle = source_bundle.get("raw_json")
    if not isinstance(raw_snapshot, str) or not isinstance(raw_bundle, str):
        raise ValueError("producer source objects must retain their serialized bytes")
    snapshot_data = _decode_json(raw_snapshot.encode("utf-8"))
    bundle_data = _decode_json(raw_bundle.encode("utf-8"))
    if snapshot_data.get("profile_id") != snapshot.get("profile_id"):
        raise ValueError("serialized producer snapshot belongs to another profile")
    if snapshot_data.get("revision") != snapshot.get("snapshot_revision"):
        raise ValueError("serialized producer snapshot revision does not match desktop context")
    if wrapper.get("public_bundle") != bundle_data:
        raise ValueError("serialized public bundle does not match the desktop-validated bundle")
    if wrapper.get("task") != producer_request.get("task"):
        raise ValueError("desktop task does not match producer task")
    return producer_request


def _run(data: bytes) -> dict[str, Any]:
    wrapper = _decode_json(data)
    producer_request = _validate_wrapper(wrapper)
    planner, component_version, adapter_profile = _load_planner()
    adapted = planner.analyze_producers(producer_request)
    analysis = adapted.get("analysis")
    if isinstance(analysis, dict):
        result: dict[str, Any] = dict(analysis)
    else:
        result = {
            "request_id": wrapper["request_id"],
            "snapshot_revision": wrapper["account_snapshot"]["snapshot_revision"],
            "authorization_generation": wrapper["authorization_generation"],
        }
    # Preserve the desktop-validated correlation context when the planner returns a
    # structured domain error without its own correlation fields. Keep any fields
    # supplied by the planner intact so the parent bridge can still reject mismatches.
    result.setdefault("request_id", wrapper["request_id"])
    result.setdefault("snapshot_revision", wrapper["account_snapshot"]["snapshot_revision"])
    result.setdefault("authorization_generation", wrapper["authorization_generation"])
    result.update({
        "status": adapted.get("status", "error"),
        "component_version": component_version,
        "adapter_profile": adapter_profile,
        "adapter_metadata": {key: value for key, value in adapted.items() if key != "analysis"},
    })
    if adapted.get("status") == "error":
        result["planner_error"] = adapted.get("error")
    return {
        "protocol": PROTOCOL_ID,
        "protocol_version": PROTOCOL_VERSION,
        "planner_version": "0.2.0",
        "capabilities": ["starhelp.producers.v0.1", "starhelp.local-profile.v0.2"],
        "result": result,
    }


def main() -> int:
    data = sys.stdin.buffer.read(MAX_REQUEST_BYTES + 1)
    if len(data) > MAX_REQUEST_BYTES:
        return 2
    try:
        response = _run(data)
        encoded = (
            json.dumps(response, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            .encode("utf-8")
            + b"\n"
        )
    except Exception:
        # The child has no diagnostic channel for inputs: do not print user or profile data.
        return 3
    if len(encoded) > MAX_RESPONSE_BYTES:
        return 4
    sys.stdout.buffer.write(encoded)
    sys.stdout.buffer.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
