"""Finite condition semantics; values and their measurement context stay together."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from datetime import datetime
from typing import Any

OPERATORS = {"eq", "neq", "gt", "gte", "lt", "lte", "in", "contains"}
TYPES = {"number", "integer", "string", "boolean", "array"}
STATES = {"confirmed", "player_confirmed", "source_verified"}


class UnsupportedSemantics(ValueError):
    pass


def validate_condition(condition: Mapping[str, Any], definitions: Mapping[str, Any], *, feedback: bool = False) -> list[str]:
    issues: list[str] = []
    supported_keys = {"condition_id", "subject", "attribute", "operator", "value", "unit", "measurement_context", "requirement", "evidence_status", "evidence_refs", "required_capabilities", "schema_version", "index_release_id"}
    if set(condition) - supported_keys:
        issues.append("unsupported_condition_field")
    definition = definitions.get(condition.get("attribute"))
    if not isinstance(definition, Mapping):
        return ["unregistered_attribute"]
    if definition.get("value_type") not in TYPES or not isinstance(definition.get("loadout_dependent"), bool):
        issues.append("unsupported_attribute_definition")
    if not condition.get("condition_id") or condition.get("operator") not in OPERATORS:
        issues.append("unsupported_condition")
    allowed = {"team_slot", "character", "equipment_slot"} | ({"feedback", "task"} if feedback else set())
    subject = condition.get("subject", {})
    if not isinstance(subject, Mapping) or subject.get("kind") not in allowed:
        issues.append("unsupported_subject")
    elif subject.get("kind") == "equipment_slot" and (
        subject.get("equipment_kind") not in {"relic", "light_cone"} or not subject.get("equipment_slot")
    ):
        issues.append("invalid_equipment_subject")
    if condition.get("requirement") not in {"hard", "soft"}:
        issues.append("invalid_requirement")
    if condition.get("evidence_status") not in {"confirmed", "suggested", "unknown"}:
        issues.append("invalid_evidence_status")
    if condition.get("unit") != definition.get("unit") or not isinstance(condition.get("unit"), str):
        issues.append("unsupported_unit")
    context = condition.get("measurement_context")
    if not isinstance(context, Mapping) or context.get("phase") not in definition.get("phases", []):
        issues.append("unsupported_measurement_context")
    elif not isinstance(context.get("assumptions"), list):
        issues.append("missing_context_assumptions")
    if "value" not in condition:
        issues.append("missing_condition_value")
    if condition.get("operator") in {"gt", "gte", "lt", "lte"} and definition.get("value_type") not in {"number", "integer"}:
        issues.append("unsupported_ordered_comparison")
    expected, operator, value_type = condition.get("value"), condition.get("operator"), definition.get("value_type")
    if operator == "in":
        valid = isinstance(expected, list) and all(value_matches_type(value, value_type) for value in expected)
    elif operator == "contains":
        valid = value_type == "array" or value_type == "string" and isinstance(expected, str)
    else:
        valid = value_matches_type(expected, value_type)
    if not valid:
        issues.append("invalid_condition_value_type")
    return issues


def evaluate_conditions(conditions: Sequence[Mapping[str, Any]], slots: Sequence[Mapping[str, Any]], snapshot: Mapping[str, Any], task: Mapping[str, Any], definitions: Mapping[str, Any], *, feedback: Any = None, allocation: Mapping[str, Any] | None = None, evaluation_time: str | None = None, troubleshooting: bool = False) -> list[dict[str, Any]]:
    characters = {c["entity_id"]: c for c in snapshot.get("characters", [])}
    seats = {slot["slot_id"]: slot for slot in slots}
    items = final_equipment(snapshot.get("equipment_instances", []), allocation)
    changed = {
        owner for action in (allocation or {}).get("actions", [])
        for owner in (action.get("from_character_id"), action.get("to_character_id")) if owner is not None
    }
    results: list[dict[str, Any]] = []
    for condition in conditions:
        issues = validate_condition(condition, definitions, feedback=troubleshooting)
        if issues:
            raise UnsupportedSemantics(", ".join(issues))
        definition = definitions[condition["attribute"]]
        subject = condition["subject"]
        kind = subject["kind"]
        character_id = subject.get("character_id")
        if kind in {"team_slot", "equipment_slot"}:
            character_id = seats.get(subject.get("slot_id"), {}).get("character_id")
        owner = characters.get(character_id)
        path = f"characters/{character_id}"
        reason: str | None = None
        if kind == "equipment_slot":
            matches = [item for item in items if item.get("equipped_by") == character_id and item.get("kind") == subject.get("equipment_kind") and item.get("slot") == subject.get("equipment_slot")]
            owner = matches[0] if len(matches) == 1 else None
            reason = "equipment_assignment_ambiguous" if len(matches) > 1 else None
            path = f"equipment_instances/{owner.get('local_instance_id') if owner else 'missing'}"
        elif kind in {"feedback", "task"}:
            owner = feedback if kind == "feedback" else task
            path = kind
        elif character_id in changed and definition["loadout_dependent"]:
            fingerprint = loadout_fingerprint(items, character_id)
            views = [view for view in snapshot.get("loadout_views", []) if view.get("character_id") == character_id and view.get("loadout_fingerprint") == fingerprint]
            owner = views[0] if len(views) == 1 else None
            path = f"loadout_views/{character_id}/{fingerprint}"
            if owner is None:
                reason = "loadout_changed_without_confirmed_panel"
        field = _field(owner, condition["attribute"])
        if reason is None:
            reason = field_reason(field, condition, task.get("scope", {}), evaluation_time, allow_reported=kind == "feedback")
        status = "unknown"
        value = None
        if reason is None:
            value = field["value"]
            if not value_matches_type(value, definition["value_type"]):
                reason = "field_type_mismatch"
            else:
                try:
                    status = "satisfied" if compare(value, condition["value"], condition["operator"]) else "not_satisfied"
                    reason = "condition_met" if status == "satisfied" else "condition_not_met"
                except (TypeError, ValueError):
                    reason = "incomparable_values"
        results.append({
            "condition_id": condition["condition_id"], "requirement": condition["requirement"],
            "evidence_status": condition["evidence_status"], "match_status": status,
            "reason_code": reason, "observed": value if status != "unknown" else None,
            "expected": {key: condition.get(key) for key in ("operator", "value", "unit", "measurement_context")},
            "local_field_refs": [f"{path}/fields/{condition['attribute']}"] if field else [],
            "field_basis": {key: field.get(key) for key in ("state", "unit", "measurement_context", "observed_at", "confirmed_at", "sources", "scope", "valid_until") if key in field},
            "evidence_refs": list(condition.get("evidence_refs", [])),
        })
    return results


def field_reason(field: Mapping[str, Any], requirement: Mapping[str, Any], scope: Mapping[str, Any], evaluation_time: str | None, *, allow_reported: bool = False) -> str | None:
    if not field or field.get("value") is None:
        return "missing_field"
    allowed = STATES | ({"user_reported"} if allow_reported else set())
    if field.get("state") not in allowed:
        return {"stale": "stale_field", "conflict": "conflicting_field"}.get(field.get("state"), "unconfirmed_field")
    if field.get("unit") is None:
        return "missing_unit"
    if field["unit"] != requirement.get("unit"):
        return "unit_mismatch"
    actual_context = field.get("measurement_context")
    if not isinstance(actual_context, Mapping):
        return "missing_measurement_context"
    if normalized_context(actual_context) != normalized_context(requirement.get("measurement_context", {})):
        return "measurement_context_mismatch"
    field_scope = field.get("scope", {})
    if not isinstance(field_scope, Mapping):
        return "invalid_field_scope"
    if any(key not in scope or scope[key] != val for key, val in field_scope.items()):
        return "field_scope_mismatch"
    try:
        if field.get("valid_until"):
            if not evaluation_time:
                return "freshness_time_missing"
            if parse_time(field["valid_until"]) <= parse_time(evaluation_time):
                return "stale_field"
        if evaluation_time and field.get("observed_at") and parse_time(field["observed_at"]) > parse_time(evaluation_time):
            return "field_from_future"
    except (ValueError, TypeError):
        return "invalid_field_time"
    return None


def normalized_context(context: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(context)
    assumptions = context.get("assumptions")
    if isinstance(assumptions, list):
        result["assumptions"] = sorted(assumptions, key=lambda item: json.dumps(item, sort_keys=True))
    return result


def parse_time(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("time must be an ISO string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timezone is required")
    return parsed


def _field(owner: Any, attribute: str) -> Mapping[str, Any]:
    if not isinstance(owner, Mapping):
        return {}
    value = owner.get("fields", {}).get(attribute)
    return value if isinstance(value, Mapping) else {}


def final_equipment(equipment: Sequence[Mapping[str, Any]], allocation: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    changes = {action["local_instance_id"]: action.get("to_character_id") for action in (allocation or {}).get("actions", [])}
    return [{**item, "equipped_by": changes.get(item["local_instance_id"], item.get("equipped_by"))} for item in equipment]


def loadout_fingerprint(equipment: Sequence[Mapping[str, Any]], character_id: str) -> str:
    members = sorted((item.get("kind"), item.get("slot"), item["local_instance_id"]) for item in equipment if item.get("equipped_by") == character_id)
    encoded = json.dumps(members, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def value_matches_type(value: Any, kind: str) -> bool:
    if kind == "boolean":
        return type(value) is bool
    if kind in {"number", "integer"}:
        return type(value) is int or kind == "number" and type(value) is float and math.isfinite(value)
    return isinstance(value, {"string": str, "array": list}.get(kind, type(None)))


def equal(left: Any, right: Any) -> bool:
    if isinstance(left, bool) or isinstance(right, bool):
        return type(left) is type(right) and left == right
    if type(left) in {int, float} and type(right) in {int, float}:
        return left == right
    return type(left) is type(right) and left == right


def compare(actual: Any, expected: Any, operator: str) -> bool:
    if operator in {"eq", "neq"}:
        matched = equal(actual, expected)
        return matched if operator == "eq" else not matched
    if operator in {"gt", "gte", "lt", "lte"}:
        if not value_matches_type(actual, "number") or not value_matches_type(expected, "number"):
            raise TypeError("numeric comparison requires finite numbers")
        return {"gt": actual > expected, "gte": actual >= expected, "lt": actual < expected, "lte": actual <= expected}[operator]
    if operator == "in" and isinstance(expected, list):
        return any(equal(actual, candidate) for candidate in expected)
    if operator == "contains":
        if isinstance(actual, str) and isinstance(expected, str):
            return expected in actual
        if isinstance(actual, list):
            return any(equal(expected, candidate) for candidate in actual)
    raise TypeError("unsupported operand types")
