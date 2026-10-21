"""Strict original-byte decoding and structured compatibility failures."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

ADAPTER_PROFILE = "starhelp.producers.v0.1"
COMPONENT_VERSION = "0.4.0"
B_COMMIT = "045965bce4fbc38a3baa79b594535c9dd983d776"
A_BASELINE = "313508f895cb422d4a309743eb7f8b99f45a7a91"


class AdaptationError(ValueError):
    def __init__(self, code: str, message: str, details: Any = None):
        self.code, self.details = code, details if details is not None else []
        super().__init__(message)


def fail(code: str, message: str, details: Any = None) -> None:
    raise AdaptationError(code, message, details)


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def materialized(value: Any) -> Any:
    active = set()
    count = 0

    def walk(item: Any, depth: int) -> None:
        nonlocal count
        count += 1
        if count > 100_000 or depth > 48:
            fail("invalid_producer_payload", "JSON size/depth limit exceeded")
        if item is None or type(item) in {str, int, bool}:
            return
        if type(item) is float:
            canonical(item)
            return
        if type(item) not in {dict, list} or id(item) in active:
            fail("invalid_producer_payload", "materialized, acyclic built-in JSON is required")
        active.add(id(item))
        if type(item) is dict:
            if any(type(key) is not str for key in item):
                fail("invalid_producer_payload", "JSON keys must be strings")
            children = item.values()
        else:
            children = item
        for child in children:
            walk(child, depth + 1)
        active.remove(id(item))

    walk(value, 0)
    return deepcopy(value)


def original(envelope: Any, producer: str, commit: str, profile: str) -> tuple[dict[str, Any], dict[str, Any]]:
    if type(envelope) is not dict or envelope.get("producer") != producer or envelope.get("producer_commit") != commit or envelope.get("format_profile") != profile:
        fail("unsupported_producer_version", "producer commit/profile is not supported")
    text = envelope.get("raw_json")
    expected = envelope.get("sha256")
    if type(text) is not str or len(text) > 8_000_000 or type(expected) is not str or len(expected) != 64:
        fail("invalid_producer_payload", "original UTF-8 JSON text and its pinned SHA-256 are required")
    actual = hashlib.sha256(text.encode("utf-8")).hexdigest()
    if actual != expected:
        fail("producer_digest_mismatch", "original producer bytes do not match the pinned digest")

    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                fail("invalid_producer_payload", "duplicate JSON keys are unsupported")
            result[key] = value
        return result

    def constant(_):
        fail("invalid_producer_payload", "non-finite JSON number")

    value = materialized(json.loads(text, object_pairs_hook=pairs, parse_constant=constant))
    if type(value) is not dict:
        fail("invalid_producer_payload", "producer document root must be an object")
    proof = {key: envelope[key] for key in ("producer", "producer_commit", "format_profile", "sha256")}
    proof.update(raw_digest_verified=True, signature_verification="not_performed_by_C")
    return value, proof


def error_result(exc: AdaptationError, request: Any) -> dict[str, Any]:
    return {
        "schema_id": "ProducerAnalysisResult", "schema_version": "0.1",
        "adapter_profile": ADAPTER_PROFILE, "component_version": COMPONENT_VERSION,
        "request_id": request.get("request_id") if type(request) is dict and type(request.get("request_id")) is str else None,
        "status": "error", "analysis": None,
        "error": {"code": exc.code, "message": str(exc), "details": exc.details, "retryable": False},
    }
