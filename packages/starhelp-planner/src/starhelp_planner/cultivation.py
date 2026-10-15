"""Version-bound integer progression costs, evaluated entirely in memory."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from .conditions import field_reason, final_equipment

CATEGORIES = {"character", "light_cone", "trace", "relic"}


def cultivation(variant: Mapping[str, Any], snapshot: Mapping[str, Any], slots: Sequence[Mapping[str, Any]], task: Mapping[str, Any], definitions: Mapping[str, Any], allocation: Mapping[str, Any] | None, evaluation_time: str | None) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    characters = {char["entity_id"]: char for char in snapshot["characters"]}
    seats = {slot["slot_id"]: slot["character_id"] for slot in slots}
    equipment = final_equipment(snapshot["equipment_instances"], allocation)
    steps: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for requirement in variant.get("cultivation_requirements", []):
        subject, category = requirement.get("subject", {}), requirement.get("category")
        subject = subject if isinstance(subject, dict) else {}
        owner, subject_id, entity_id = None, None, None
        if subject.get("kind") == "character" and category in {"character", "trace"}:
            entity_id = subject.get("character_id")
            if entity_id in seats.values():
                owner, subject_id = characters.get(entity_id), entity_id
        elif subject.get("kind") == "equipment_slot" and category in {"light_cone", "relic"}:
            candidates = [item for item in equipment if item.get("equipped_by") == seats.get(subject.get("slot_id")) and item.get("kind") == subject.get("equipment_kind") == category and item.get("slot") == subject.get("equipment_slot") and item.get("identity_state") in {"player_confirmed", "source_verified"}]
            if len(candidates) == 1:
                owner = candidates[0]
                subject_id, entity_id = owner["local_instance_id"], owner.get("public_type_id")
        attribute = requirement.get("current_field")
        definition = definitions.get(attribute, {})
        field = (owner or {}).get("fields", {}).get(attribute, {})
        context = requirement.get("measurement_context")
        reason = "unsupported_progression" if category not in CATEGORIES or definition.get("value_type") != "integer" or definition.get("loadout_dependent") is not False or requirement.get("unit") != definition.get("unit") or not isinstance(context, dict) or context.get("phase") not in definition.get("phases", []) else None
        reason = reason or ("unsupported_subject" if owner is None else None)
        if not reason:
            reason = field_reason(field, requirement, task["scope"], evaluation_time)
        current, target = field.get("value"), requirement.get("target_value")
        if not reason and (type(current) is not int or current < 0 or type(target) is not int or target < 0):
            reason = "invalid_progression_range"
        if not reason and (subject_id, attribute) in seen:
            reason = "duplicate_progression_requirement"
        seen.add((subject_id, attribute))
        gap = max(0, target - current) if not reason else None
        rule = requirement.get("cost_rule", {})
        rule = rule if isinstance(rule, dict) else {}
        costs: dict[str, int] = defaultdict(int)
        if not reason and gap:
            reason = _costs(rule, requirement, entity_id, current, target, task["scope"], costs)
        cost = {"status": "not_calculated", "reason": reason} if reason else {
            "status": "calculated", "basis": "gross_cost_before_inventory",
            "rule_id": rule.get("id"), "rule_revision": rule.get("revision"),
            "materials": [{"material_id": identifier, "amount": amount} for identifier, amount in sorted(costs.items())],
        }
        steps.append({
            "requirement_id": requirement.get("requirement_id"), "subject": dict(subject),
            "local_subject_id": subject_id, "category": category, "current": current if gap is not None else None,
            "target": target, "gap": gap, "priority": requirement.get("priority"), "reason": requirement.get("reason"),
            "cost": cost, "evidence_refs": [*requirement.get("evidence_refs", []), *rule.get("evidence_refs", [])],
        })
    steps.sort(key=lambda step: (step["priority"] if type(step["priority"]) is int else 2**31, str(step["requirement_id"])))
    return steps, _aggregate(steps, snapshot, task["scope"], evaluation_time)


def _costs(rule: Any, requirement: Mapping[str, Any], entity_id: str | None, current: int, target: int, scope: Mapping[str, Any], costs: dict[str, int]) -> str | None:
    if not isinstance(rule, dict) or not rule.get("id") or type(rule.get("revision")) is not int or rule["revision"] < 1 or not rule.get("evidence_refs"):
        return "missing_versioned_cost_rule"
    applies = rule.get("scope", {})
    if not isinstance(applies, dict) or any(applies.get(key) != scope.get(key) for key in ("game_version", "environment")) or any(key not in scope or scope[key] != value for key, value in applies.items()):
        return "cost_rule_scope_mismatch"
    if rule.get("category") != requirement["category"] or rule.get("subject_entity_id") != entity_id or rule.get("attribute") != requirement["current_field"] or rule.get("unit") != requirement.get("unit"):
        return "cost_rule_subject_mismatch"
    edges = rule.get("transitions")
    if not isinstance(edges, list) or not edges or len(edges) > 10_000:
        return "missing_cost_transitions"
    lookup = {}
    for edge in edges:
        if not isinstance(edge, dict) or type(edge.get("from")) is not int or type(edge.get("to")) is not int or edge["from"] < 0 or edge["to"] != edge["from"] + 1 or edge["from"] in lookup:
            return "invalid_cost_transition"
        materials = edge.get("materials")
        if not isinstance(materials, list) or any(not isinstance(item, dict) or type(item.get("material_id")) is not str or not item["material_id"] or type(item.get("amount")) is not int or item["amount"] < 0 for item in materials):
            return "invalid_material_cost"
        lookup[edge["from"]] = materials
    if target - current > 10_000 or any(level not in lookup for level in range(current, target)):
        return "cost_range_not_covered"
    for level in range(current, target):
        for item in lookup[level]:
            costs[item["material_id"]] += item["amount"]
    return None


def _aggregate(steps: Sequence[Mapping[str, Any]], snapshot: Mapping[str, Any], scope: Mapping[str, Any], evaluation_time: str | None) -> dict[str, Any]:
    if any(step["cost"]["status"] != "calculated" for step in steps):
        return {"status": "not_calculated", "reason": "incomplete_step_costs", "net_status": "not_calculated", "materials": []}
    totals: dict[str, int] = defaultdict(int)
    for step in steps:
        for cost in step["cost"]["materials"]:
            totals[cost["material_id"]] += cost["amount"]
    inventory = {item["material_id"]: item for item in snapshot.get("materials", [])}
    reason = "material_coverage_incomplete" if totals and snapshot.get("coverage", {}).get("materials") != "complete" else None
    rows = []
    for material_id, amount in sorted(totals.items()):
        material = inventory.get(material_id, {})
        reason = reason or field_reason({**material, "value": material.get("count")}, {"unit": "item_count", "measurement_context": {"phase": "inventory", "assumptions": []}}, scope, evaluation_time)
        if type(material.get("count")) is not int or material["count"] < 0:
            reason = reason or "invalid_material_count"
        rows.append({"material_id": material_id, "amount": amount, "available": material.get("count")})
    for row in rows:
        row["available"] = row["available"] if not reason else None
        row["net_shortage"] = max(0, row["amount"] - row["available"]) if not reason else None
    return {"status": "calculated", "basis": "aggregate_gross_cost", "net_status": "not_calculated" if reason else "calculated", "reason": reason, "materials": rows}
