"""Separate producer entry point; native 0.2 analyze remains unchanged."""

from __future__ import annotations

from typing import Any

from ..api import analyze
from .a_legacy import A_LEGACY_PROFILE, reject_legacy
from .a_distribution import DISTRIBUTION_PROFILE, adapt_distribution
from .b_snapshot import adapt_snapshot
from .common import ADAPTER_PROFILE, COMPONENT_VERSION, AdaptationError, error_result, fail, materialized
from ..validation import validate_json_request


def prepare_producer_request(request: dict[str, Any]) -> dict[str, Any]:
    try:
        clean = materialized(request)
        if type(clean) is not dict or clean.get("schema_id") != "ProducerAnalysisRequest" or clean.get("schema_version") != "0.1" or clean.get("adapter_profile") != ADAPTER_PROFILE:
            fail("unsupported_adapter_profile", "select the explicit producer adapter schema/profile")
        envelope = clean.get("public_bundle", {})
        profile = envelope.get("format_profile") if type(envelope) is dict else None
        if profile == A_LEGACY_PROFILE:
            reject_legacy(envelope)
        if profile == DISTRIBUTION_PROFILE:
            public, a_proof = adapt_distribution(envelope, clean.get("distribution_trust"))
            snapshot, b_proof, diagnostics = adapt_snapshot(clean.get("account_snapshot"), clean.get("authorization_context"), public["entities"])
            native = {
                "schema_id": "AnalysisRequest", "schema_version": "0.1-draft", "contract_version": "0.1-draft",
                "adapter_profile": "starhelp.local.v0.2", "local_rule_version": "0.2.0",
                "request_id": clean.get("request_id"), "authorization_generation": snapshot["authorization_generation"],
                "public_bundle": public, "account_snapshot": snapshot, "task": clean.get("task"),
                "evaluation_time": clean.get("evaluation_time"), "latest_known_validity": clean.get("latest_known_validity", {}),
                "feedback": clean.get("feedback"),
            }
            validate_json_request(native)
            return {
                "status": "ready", "native_request": native,
                "producer_provenance": {"public_bundle": a_proof, "account_snapshot": b_proof},
                "compatibility": {"diagnostics": diagnostics, "normalization_is_a_signature": False, "native_rule_profile": "starhelp.local.v0.2", "core_rule_version": "0.2.0"},
            }
        fail("unsupported_producer_version", "no executable A producer profile has been accepted yet")
    except AdaptationError as exc:
        return error_result(exc, request)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, RecursionError):
        return error_result(AdaptationError("invalid_producer_payload", "invalid producer input; no conversion was executed"), request)


def analyze_producers(request: dict[str, Any]) -> dict[str, Any]:
    prepared = prepare_producer_request(request)
    if prepared["status"] == "error":
        return prepared
    result = analyze(prepared["native_request"])
    return {
        "schema_id": "ProducerAnalysisResult", "schema_version": "0.1",
        "adapter_profile": ADAPTER_PROFILE, "component_version": COMPONENT_VERSION,
        "request_id": prepared["native_request"]["request_id"], "status": result["status"],
        "analysis": result, "producer_provenance": prepared["producer_provenance"],
        "compatibility": prepared["compatibility"],
    }
