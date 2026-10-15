"""Validation and canonical serialization for public knowledge records."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any

from starhelp_knowledge.errors import InvalidPayload

RECORD_KINDS = frozenset({"entity", "knowledge", "stage", "template", "variant", "troubleshooting", "resource"})
ENVIRONMENTS = frozenset({"live", "beta", "unknown"})
RELEASE_STATES = frozenset({"released", "unreleased", "unknown"})
FORBIDDEN_KEYS = frozenset(
    {
        "uid", "account", "account_id", "profile_id", "snapshot_id", "roster", "inventory",
        "owned_characters", "owned_character_ids", "equipment_instances", "build", "loadout",
        "battle_result", "score_result", "failure_feedback", "private_report", "match_status",
        "authorization_generation", "cookie", "session_token", "password", "credential",
        "script", "code", "command", "dynamic_import", "function_call", "tool_call",
    }
)
FORBIDDEN_KEY_PARTS = ("account", "uid", "roster", "inventory", "owned", "snapshot", "private", "feedback", "loadout", "session", "credential")
CONDITION_OPERATORS = frozenset({"eq", "ne", "gt", "gte", "lt", "lte", "in", "not_in"})


def canonical_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def content_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def _scan_public(value: Any) -> None:
    if isinstance(value, Mapping):
        for key, child in value.items():
            if not isinstance(key, str):
                raise InvalidPayload("invalid record field")
            if key.casefold() in FORBIDDEN_KEYS:
                raise InvalidPayload("record contains a prohibited field")
            if any(part in key.casefold() for part in FORBIDDEN_KEY_PARTS):
                raise InvalidPayload("record contains a prohibited field")
            _scan_public(child)
    elif isinstance(value, list):
        for child in value:
            _scan_public(child)
    elif not (value is None or isinstance(value, str | int | float | bool)):
        raise InvalidPayload("record contains a non-serializable value")


def validate_scope(scope: Any) -> dict[str, Any]:
    if not isinstance(scope, dict):
        raise InvalidPayload("invalid record scope")
    allowed = {"game_version", "environment", "release_status", "mode_id", "cycle_id", "stage_id", "target_kind"}
    if set(scope) - allowed:
        raise InvalidPayload("unexpected scope field")
    if scope.get("environment", "unknown") not in ENVIRONMENTS:
        raise InvalidPayload("invalid environment")
    if scope.get("release_status", "unknown") not in RELEASE_STATES:
        raise InvalidPayload("invalid release status")
    for key, value in scope.items():
        if value is not None and (not isinstance(value, str) or len(value) > 200):
            raise InvalidPayload("invalid scope value")
    return {**scope, "environment": scope.get("environment", "unknown"), "release_status": scope.get("release_status", "unknown")}


def validate_public_record(
    kind: str,
    record_id: str,
    scope: Any,
    payload: Any,
    evidence_refs: Any,
    dependency_refs: Any,
) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    if kind not in RECORD_KINDS or not isinstance(record_id, str) or not 1 <= len(record_id) <= 200:
        raise InvalidPayload("invalid public record identity")
    if not isinstance(payload, dict) or len(canonical_json(payload)) > 2_000_000:
        raise InvalidPayload("invalid public record payload")
    normalized_scope = validate_scope(scope)
    _scan_public({"scope": normalized_scope, "payload": payload})
    normalized_evidence = _validate_refs(evidence_refs, evidence=True)
    normalized_dependencies = _validate_refs(dependency_refs, evidence=False)
    if not normalized_evidence:
        raise InvalidPayload("public records require evidence")
    if kind == "template":
        if not normalized_scope.get("stage_id"):
            raise InvalidPayload("template requires explicit stage scope")
        variant_refs = [ref for ref in normalized_dependencies if ref["kind"] == "variant"]
        stage_refs = [ref for ref in normalized_dependencies if ref["kind"] == "stage"]
        if not variant_refs or len(stage_refs) != 1 or any(ref["kind"] not in {"stage", "variant"} for ref in normalized_dependencies):
            raise InvalidPayload("template must reference one stage and complete variants")
        if stage_refs[0]["id"] != normalized_scope["stage_id"]:
            raise InvalidPayload("template stage reference does not match its scope")
        variant_ids = {ref["id"] for ref in variant_refs}
        if payload.get("primary_variant_id") not in variant_ids:
            raise InvalidPayload("template must name a primary complete variant")
        alternatives = payload.get("alternate_variant_ids", [])
        if not isinstance(alternatives, list) or any(not isinstance(item, str) or item not in variant_ids for item in alternatives):
            raise InvalidPayload("template alternate variants must be complete referenced variants")
    if kind == "variant":
        if not isinstance(payload.get("team"), list) or not payload["team"]:
            raise InvalidPayload("complete variant must declare its full team")
        if not isinstance(payload.get("steps"), list) or not payload["steps"]:
            raise InvalidPayload("complete variant must declare ordered steps")
        team_ids = {slot.get("entity_id") for slot in payload["team"] if isinstance(slot, dict)}
        slot_ids = {slot.get("slot_id") for slot in payload["team"] if isinstance(slot, dict)}
        dependency_ids = {ref["id"] for ref in normalized_dependencies if ref["kind"] == "entity"}
        if len(team_ids) != len(payload["team"]) or None in team_ids or not team_ids.issubset(dependency_ids) or len(slot_ids) != len(payload["team"]) or None in slot_ids:
            raise InvalidPayload("variant must reference every team entity")
        if not isinstance(payload.get("conditions", []), list) or not isinstance(payload.get("steps"), list):
            raise InvalidPayload("variant conditions and steps must be ordered lists")
        for condition in payload.get("conditions", []):
            _validate_condition(condition, slot_ids, {ref["id"] for ref in normalized_evidence})
        if not payload["steps"]:
            raise InvalidPayload("complete variant must declare ordered steps")
        for index, step in enumerate(payload["steps"], start=1):
            if not isinstance(step, dict) or not isinstance(step.get("order"), int) or isinstance(step.get("order"), bool) or step.get("order") != index or not isinstance(step.get("text"), str) or not step["text"].strip():
                raise InvalidPayload("variant steps must be ordered and descriptive")
    if kind == "stage" and not all(normalized_scope.get(key) for key in ("mode_id", "cycle_id", "stage_id", "game_version")):
        raise InvalidPayload("stage requires explicit version, mode, cycle, and stage scope")
    if kind == "troubleshooting" and not normalized_dependencies:
        raise InvalidPayload("troubleshooting must reference complete variants")
    if kind == "entity" and (not isinstance(payload.get("entity_type"), str) or not isinstance(payload.get("canonical_name"), str)):
        raise InvalidPayload("entity requires a type and canonical name")
    return normalized_scope, payload, normalized_evidence, normalized_dependencies


def _validate_refs(value: Any, *, evidence: bool) -> list[dict[str, Any]]:
    if not isinstance(value, list) or len(value) > 500:
        raise InvalidPayload("invalid reference list")
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            raise InvalidPayload("invalid reference")
        allowed = {"id", "revision"} if evidence else {"kind", "id", "revision"}
        if set(item) != allowed:
            raise InvalidPayload("invalid reference")
        if not isinstance(item["id"], str) or not 1 <= len(item["id"]) <= 200:
            raise InvalidPayload("invalid reference")
        if not isinstance(item["revision"], int) or isinstance(item["revision"], bool) or item["revision"] < 1:
            raise InvalidPayload("invalid reference")
        if not evidence and item["kind"] not in RECORD_KINDS:
            raise InvalidPayload("invalid dependency kind")
        result.append(dict(item))
    if len({canonical_json(ref) for ref in result}) != len(result):
        raise InvalidPayload("duplicate reference")
    return result


def _validate_condition(condition: Any, slot_ids: set[Any], evidence_ids: set[str]) -> None:
    fields = {"condition_id", "subject", "attribute", "operator", "value", "unit", "measurement_context", "requirement", "evidence_status", "evidence_refs"}
    if not isinstance(condition, dict) or set(condition) != fields:
        raise InvalidPayload("condition does not match the declared condition schema")
    subject = condition["subject"]
    if not isinstance(subject, dict) or set(subject) - {"kind", "slot_id", "entity_id"}:
        raise InvalidPayload("invalid condition subject")
    if subject.get("kind") not in {"team_slot", "team", "entity"}:
        raise InvalidPayload("invalid condition subject")
    if subject.get("kind") == "team_slot" and subject.get("slot_id") not in slot_ids:
        raise InvalidPayload("condition refers to an unknown team slot")
    if subject.get("kind") == "entity" and not isinstance(subject.get("entity_id"), str):
        raise InvalidPayload("invalid condition entity")
    if not isinstance(condition["condition_id"], str) or not isinstance(condition["attribute"], str) or not condition["attribute"]:
        raise InvalidPayload("invalid condition identity")
    if condition["operator"] not in CONDITION_OPERATORS:
        raise InvalidPayload("unsupported condition operator")
    if condition["operator"] in {"in", "not_in"} and not isinstance(condition["value"], list):
        raise InvalidPayload("membership conditions require a value list")
    if condition["operator"] not in {"in", "not_in"} and isinstance(condition["value"], list | dict):
        raise InvalidPayload("comparison conditions require a scalar value")
    if not isinstance(condition["unit"], str) or not condition["unit"]:
        raise InvalidPayload("condition unit is required")
    if condition["requirement"] not in {"hard", "soft"} or condition["evidence_status"] not in {"confirmed", "suggested", "unknown"}:
        raise InvalidPayload("invalid condition semantics")
    context = condition["measurement_context"]
    if not isinstance(context, dict) or set(context) != {"phase", "assumptions"}:
        raise InvalidPayload("condition measurement context is required")
    if context["phase"] not in {"pre_battle", "in_battle"} or not isinstance(context["assumptions"], list) or any(not isinstance(item, str) for item in context["assumptions"]):
        raise InvalidPayload("invalid condition measurement context")
    refs = _validate_refs(condition["evidence_refs"], evidence=True)
    if not refs or any(ref["id"] not in evidence_ids for ref in refs):
        raise InvalidPayload("condition requires evidence from this record")
