"""Draft-contract planner implementation. This module intentionally has no I/O."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

PLANNER_VERSION = "0.1.0"
_CONTRACT = "0.1-draft"
_SUPPORTED_CAPABILITIES = {
    "starhelp.complete-variant.v1",
    "starhelp.conditions.v1",
    "starhelp.cultivation.v1",
    "starhelp.troubleshooting.v1",
    "fixture:complete-variant:v1",
    "fixture:conditions:v1",
    "fixture:cultivation:v1",
    "fixture:troubleshooting:v1",
}
_OPERATORS = {"eq", "neq", "gt", "gte", "lt", "lte", "in", "contains"}


def analyze_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-compatible result for one already-materialized request."""
    try:
        return _analyze(request)
    except _InputError as exc:
        return _error_result(request, exc.code, str(exc), exc.details)
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        return _error_result(request, "invalid_payload", f"Invalid planner input: {exc}")


class _InputError(ValueError):
    def __init__(self, code: str, message: str, details: Mapping[str, Any] | None = None) -> None:
        self.code = code
        self.details = dict(details or {})
        super().__init__(message)


def _analyze(request: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(request, Mapping):
        raise _InputError("invalid_payload", "request must be a mapping")
    bundle = _mapping(request.get("public_bundle"))
    snapshot = _mapping(request.get("account_snapshot"))
    task = _mapping(request.get("task"))
    if not bundle or not snapshot or not task:
        raise _InputError("invalid_payload", "public_bundle, account_snapshot, and task are required")
    if request.get("schema_id") != "AnalysisRequest" or request.get("schema_version") != _CONTRACT or request.get("contract_version") != _CONTRACT:
        raise _InputError("unsupported_schema", "request schema is missing or unsupported")
    if snapshot.get("schema_id") != "AccountSnapshot" or snapshot.get("schema_version") != _CONTRACT:
        raise _InputError("unsupported_schema", "account snapshot schema is missing or unsupported")
    if not request.get("request_id") or not snapshot.get("profile_id") or not snapshot.get("snapshot_id") or snapshot.get("snapshot_revision") is None:
        raise _InputError("invalid_payload", "request and snapshot identity fields are required")
    if snapshot.get("authorization_state") != "active":
        raise _InputError("authorization_inactive", "account snapshot is not currently authorized")
    if request.get("authorization_generation") is None or snapshot.get("authorization_generation") is None:
        raise _InputError("invalid_payload", "authorization_generation is required on request and snapshot")
    if request.get("authorization_generation") != snapshot.get("authorization_generation"):
        raise _InputError("superseded_generation", "request and snapshot authorization generations differ")
    snapshot_issues = _validate_snapshot(snapshot)
    if snapshot_issues:
        raise _InputError("snapshot_conflict", "account snapshot contains ambiguous identities", {"issues": snapshot_issues})
    if not _mapping(task.get("public_goal")):
        raise _InputError("invalid_payload", "task.public_goal is required")
    if "allow_rearrangement" in task and not isinstance(task.get("allow_rearrangement"), bool):
        raise _InputError("invalid_payload", "task.allow_rearrangement must be boolean")

    issues = _validate_bundle(bundle)
    if issues:
        raise _InputError("invalid_public_bundle", "public bundle is incomplete or incompatible", {"issues": issues})
    manifest = _mapping(bundle.get("manifest"))
    release_id = manifest.get("index_release_id")
    task_scope = _mapping(task.get("scope"))
    stages = _objects_by_id(bundle.get("stages"), "stage_id")
    stage = stages.get(str(task_scope.get("stage_id", "")))
    if stage is None:
        raise _InputError("scope_mismatch", "selected stage is not present in this public bundle")
    stage_scope = _stage_scope(stage)
    scope_mismatch = _scope_mismatch(task_scope, stage_scope)
    scope_mismatch.extend(
        key for key in ("game_version", "environment", "mode_id", "cycle_id", "stage_id")
        if task_scope.get(key) is None or stage_scope.get(key) is None
    )
    if scope_mismatch:
        raise _InputError("scope_mismatch", "selected task does not match the bundled stage", {"fields": scope_mismatch})
    withdrawn = _withdrawn_refs(request)

    evidence = _objects_by_id(bundle.get("evidence"), "id")
    entities = _objects_by_id(bundle.get("entities"), "id")
    templates = list(_mapping_list(bundle.get("templates")))
    variants = list(_mapping_list(bundle.get("variants")))
    snapshot_characters = _objects_by_id(snapshot.get("characters"), "entity_id")
    equipment = _mapping_list(snapshot.get("equipment_instances"))
    character_locks = set(_string_list(task.get("fixed_character_ids")))
    excluded_characters = set(_string_list(task.get("excluded_character_ids")))
    locked_instances = set(_string_list(task.get("locked_local_instance_ids")))
    if character_locks & excluded_characters:
        raise _InputError("no_feasible_variant", "a character is both fixed and excluded")

    evaluated: list[dict[str, Any]] = []
    pending: list[dict[str, Any]] = []
    rejection_reasons: list[dict[str, Any]] = []
    matching_templates = [t for t in templates if _template_applies(t, stage, task_scope) and not _is_withdrawn(t, withdrawn, "template")]
    matching_ids = {str(t.get("id")) for t in matching_templates}

    for variant in variants:
        template_id = str(variant.get("template_id", ""))
        if template_id not in matching_ids or not _reviewed_and_published(variant):
            continue
        variant_id = str(variant.get("id", ""))
        if _is_withdrawn(variant, withdrawn, "variant"):
            rejection_reasons.append(_rejection(variant_id, "withdrawn_evidence", "variant or its evidence is withdrawn"))
            continue
        template = next(t for t in matching_templates if str(t.get("id")) == template_id)
        variant_issues = _validate_variant(variant, stage, entities, evidence)
        declared_variants = _string_list(template.get("variant_ids"))
        if declared_variants and variant_id not in declared_variants:
            variant_issues.append("template does not declare this complete variant")
        if variant_issues:
            rejection_reasons.append(_rejection(variant_id, "invalid_variant", "complete variant validation failed", variant_issues))
            continue
        slots = _flatten_slots(variant)
        roster_complete = _mapping(snapshot.get("coverage")).get("roster") == "complete"
        role_state = _check_roster(slots, snapshot_characters, character_locks, excluded_characters, roster_complete)
        if role_state["rejected"]:
            rejection_reasons.append(_rejection(variant_id, "hard_constraint_conflict", "roster or fixed/excluded character constraints conflict", role_state["reasons"]))
            continue
        condition_results = _evaluate_conditions(
            _conditions_for(variant), slots, snapshot_characters, task, request.get("feedback")
        )
        hard_failed = [c for c in condition_results if c["requirement"] == "hard" and c["match_status"] == "not_satisfied"]
        if hard_failed:
            rejection_reasons.append(_rejection(variant_id, "hard_condition_failed", "a hard template condition is not satisfied", hard_failed))
            continue
        hard_unknown = [c for c in condition_results if c["requirement"] == "hard" and c["match_status"] == "unknown"]
        role_unknown = role_state["pending"]
        equip_sets = _equipment_options(slots, equipment, locked_instances, stage, bool(task.get("allow_rearrangement", False)))
        if not equip_sets["current"] and not equip_sets["rearranged"]:
            inventory_incomplete = _mapping(snapshot.get("coverage")).get("inventory") != "complete"
            if inventory_incomplete or equip_sets.get("search_limited"):
                pending.append(_public_candidate({
                    "template": _template_summary(template),
                    "variant": _variant_summary(variant), "team": slots,
                    "condition_results": condition_results, "hard_unknown": hard_unknown,
                    "role_unknown": role_unknown,
                    "current_equipment": None, "rearranged_equipment": None,
                    "cultivation": _cultivation(variant, snapshot, slots),
                    "strategy": {
                        "steps": _mapping_list(variant.get("steps")),
                        "mechanics": _mapping_list(variant.get("mechanics")),
                        "failure_conditions": _mapping_list(variant.get("failure_conditions")),
                        "risks": _mapping_list(variant.get("risks")),
                    },
                    "evidence_refs": _collect_evidence_refs(template, variant, condition_results, evidence),
                    "sort": _rank_key(condition_results, equip_sets),
                    "equipment_unknown": True,
                    "equipment_unknown_reason": "allocation_search_incomplete" if equip_sets.get("search_limited") else "inventory_coverage_incomplete",
                }))
                continue
            rejection_reasons.append(_rejection(variant_id, "equipment_conflict", "no legal equipment assignment satisfies the complete variant", equip_sets["reasons"]))
            continue
        item = {
            "template": _template_summary(template),
            "variant": _variant_summary(variant),
            "team": slots,
            "condition_results": condition_results,
            "hard_unknown": hard_unknown,
            "role_unknown": role_unknown,
            "current_equipment": equip_sets["current"],
            "rearranged_equipment": equip_sets["rearranged"],
            "cultivation": _cultivation(variant, snapshot, slots),
            "strategy": {
                "steps": _mapping_list(variant.get("steps")),
                "mechanics": _mapping_list(variant.get("mechanics")),
                "failure_conditions": _mapping_list(variant.get("failure_conditions")),
                "risks": _mapping_list(variant.get("risks")),
            },
            "evidence_refs": _collect_evidence_refs(template, variant, condition_results, evidence),
            "sort": _rank_key(condition_results, equip_sets),
        }
        if hard_unknown or role_unknown:
            pending.append(_public_candidate(item))
        else:
            evaluated.append(item)

    evaluated.sort(key=lambda x: x["sort"])
    pending.sort(key=lambda x: x["sort"])
    current_plans = [_as_plan(item, "current", release_id) for item in evaluated if item["current_equipment"]]
    rearrangement_plans = [_as_plan(item, "rearrangement", release_id) for item in evaluated if item["rearranged_equipment"] and item["rearranged_equipment"]["actions"]]
    pending_candidates = [_as_plan(item, "pending_confirmation", release_id) for item in pending]
    troubleshooting = _troubleshooting(request.get("feedback"), bundle, variants, snapshot_characters, task, task_scope, withdrawn)
    if current_plans or rearrangement_plans:
        status = "plans_available"
    elif pending_candidates:
        status = "confirmation_required"
    elif not matching_templates:
        status = "no_reviewed_template"
    elif rejection_reasons:
        status = "no_feasible_variant"
    else:
        status = "coverage_insufficient"

    return {
        "contract_version": _CONTRACT,
        "schema_id": "AnalysisResult",
        "schema_version": _CONTRACT,
        "planner_version": PLANNER_VERSION,
        "request_id": request.get("request_id"),
        "profile_id": snapshot.get("profile_id"),
        "snapshot_id": snapshot.get("snapshot_id"),
        "snapshot_revision": snapshot.get("snapshot_revision"),
        "authorization_generation": request.get("authorization_generation"),
        "index_release_id": release_id,
        "public_goal": task.get("public_goal"),
        "hard_constraints": {
            "fixed_character_ids": sorted(character_locks),
            "excluded_character_ids": sorted(excluded_characters),
            "locked_local_instance_ids": sorted(locked_instances),
        },
        "stage": {"id": stage.get("stage_id"), "revision": stage.get("revision"), "scope": _stage_scope(stage)},
        "public_material": {
            key: stage.get(key) for key in ("title", "enemy_refs", "mechanics", "objectives", "evidence_refs") if stage.get(key) is not None
        },
        "local_rule_version": request.get("local_rule_version", PLANNER_VERSION),
        "status": status,
        "current_equipment_plans": current_plans,
        "rearrangement_plans": rearrangement_plans,
        "pending_confirmation_candidates": pending_candidates,
        "rejected_variants": rejection_reasons,
        "troubleshooting": troubleshooting,
        "coverage": _mapping(manifest.get("coverage")),
        "validity": {
            "checked_at": _mapping(request.get("latest_known_validity")).get("checked_at"),
            "online_confirmation_available": _mapping(request.get("latest_known_validity")).get("online_confirmation_available"),
            "withdrawn_public_refs": sorted(withdrawn),
        },
        "degradation": {
            "reasons": _degradation_reasons(status, matching_templates, rejection_reasons, pending_candidates),
            "coverage_gaps": _mapping_list(stage.get("coverage_gaps")),
        },
        "citations": _citation_catalog(bundle, _dedupe_refs([*_all_result_refs(current_plans, rearrangement_plans, pending_candidates, [troubleshooting]), *_mapping_list(stage.get("evidence_refs"))])),
        "limitations": ["匹配和排序不代表通关概率。", "此实现使用 mvp-v0.1 工程初稿的适配配置，等待 M0 冻结。"],
    }


def _validate_bundle(bundle: Mapping[str, Any]) -> list[dict[str, str]]:
    problems: list[dict[str, str]] = []
    if bundle.get("schema_id") != "PublicBundle" or bundle.get("contract_version") != _CONTRACT:
        problems.append({"code": "unsupported_schema", "message": "schema_id must be PublicBundle"})
    manifest = _mapping(bundle.get("manifest"))
    if not manifest.get("index_release_id"):
        problems.append({"code": "missing_release", "message": "manifest.index_release_id is required"})
    required = _string_list(manifest.get("required_capabilities"))
    unknown = sorted(set(required) - _SUPPORTED_CAPABILITIES)
    if unknown:
        problems.append({"code": "unsupported_capability", "message": ", ".join(unknown)})
    schemas = _mapping(manifest.get("object_schemas"))
    for kind in ("stage", "entity", "template", "variant", "evidence", "troubleshooting"):
        if kind not in schemas:
            problems.append({"code": "unsupported_schema", "message": f"missing schema declaration for {kind}"})
        elif schemas[kind] != _CONTRACT:
            problems.append({"code": "unsupported_schema", "message": f"unsupported {kind} schema {schemas[kind]}"})
    members = _mapping_list(manifest.get("members"))
    member_keys = {
        (str(m.get("kind", "")), str(m.get("id", "")), str(m.get("revision", "")))
        for m in members
    }
    if len(member_keys) != len(members):
        problems.append({"code": "invalid_payload", "message": "manifest has duplicate member identity"})
    for plural, kind, id_key in (
        ("entities", "entity", "id"), ("stages", "stage", "stage_id"),
        ("templates", "template", "id"), ("variants", "variant", "id"),
        ("evidence", "evidence", "id"), ("troubleshooting", "troubleshooting", "id"),
    ):
        objects = _mapping_list(bundle.get(plural))
        identities = [(str(obj.get(id_key, "")), str(obj.get("revision", ""))) for obj in objects]
        if len(identities) != len(set(identities)):
            problems.append({"code": "invalid_payload", "message": f"{plural} has duplicate stable identity"})
        for obj in objects:
            revision = obj.get("revision")
            key = (kind, str(obj.get(id_key, "")), str(revision if revision is not None else ""))
            if not key[1] or not key[2]:
                problems.append({"code": "invalid_payload", "message": f"{plural} object lacks stable id or revision"})
            elif key not in member_keys:
                problems.append({"code": "missing_member", "message": f"manifest does not list {kind} {key[1]}@{key[2]}"})
    available_refs = {
        (str(obj.get("id", obj.get("stage_id", ""))), str(obj.get("revision", "")))
        for plural in ("entities", "stages", "templates", "variants", "evidence", "troubleshooting")
        for obj in _mapping_list(bundle.get(plural))
    }
    for plural in ("stages", "templates", "variants", "evidence", "troubleshooting"):
        for obj in _mapping_list(bundle.get(plural)):
            problems.extend(_reference_issues(obj, available_refs, str(obj.get("id", obj.get("stage_id", "")))))
    for member in members:
        if not member.get("content_hash"):
            problems.append({"code": "integrity_failed", "message": f"manifest member {member.get('id')} lacks content_hash"})
    for item in _mapping_list(bundle.get("evidence")):
        state = item.get("status", item.get("state", "unknown"))
        if state in {"withdrawn", "disabled", "rejected", "expired"} or item.get("enabled") is False:
            problems.append({"code": "withdrawn_evidence", "message": f"evidence {item.get('id')} is not currently usable"})
    if bundle.get("schema_version") != _CONTRACT:
        problems.append({"code": "unsupported_schema", "message": "unsupported PublicBundle schema_version"})
    return problems


def _validate_snapshot(snapshot: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    characters = _mapping_list(snapshot.get("characters"))
    character_ids = [str(item.get("entity_id", "")) for item in characters]
    if any(not value for value in character_ids) or len(character_ids) != len(set(character_ids)):
        problems.append("character entity identities are missing or duplicated")
    if any(item.get("ownership", "unknown") not in {"owned", "not_owned", "unknown"} for item in characters):
        problems.append("character ownership uses an unsupported state")
    equipment = _mapping_list(snapshot.get("equipment_instances"))
    equipment_ids = [str(item.get("local_instance_id", "")) for item in equipment]
    if any(not value for value in equipment_ids) or len(equipment_ids) != len(set(equipment_ids)):
        problems.append("local equipment instance identities are missing or duplicated")
    allowed_identity = {"player_confirmed", "source_verified", "ambiguous", "unconfirmed", "unknown"}
    if any(item.get("identity_state", "unknown") not in allowed_identity for item in equipment):
        problems.append("equipment identity state is unsupported")
    return problems


def _validate_variant(variant: Mapping[str, Any], stage: Mapping[str, Any], entities: Mapping[str, Mapping[str, Any]], evidence: Mapping[str, Mapping[str, Any]]) -> list[str]:
    problems: list[str] = []
    slots = _flatten_slots(variant)
    required_partitions = _partition_ids(stage)
    actual_partitions = {str(slot["partition_id"]) for slot in slots}
    if not slots or required_partitions != actual_partitions:
        problems.append("variant partitions must exactly match the complete stage partition set")
    expected_slots = _expected_slots(stage)
    for partition, required_ids in expected_slots.items():
        actual = {str(s["slot_id"]) for s in slots if str(s["partition_id"]) == partition}
        if required_ids != actual:
            problems.append(f"variant slots must exactly match required slots in partition {partition}")
    seen_slot_ids: set[tuple[str, str]] = set()
    seen_global_slot_ids: set[str] = set()
    for slot in slots:
        slot_id = str(slot["slot_id"])
        partition_id = str(slot["partition_id"])
        if (partition_id, slot_id) in seen_slot_ids:
            problems.append(f"duplicate slot {partition_id}/{slot_id}")
        seen_slot_ids.add((partition_id, slot_id))
        if slot_id in seen_global_slot_ids:
            problems.append(f"slot id {slot_id} must be unique across the complete variant")
        seen_global_slot_ids.add(slot_id)
        character_id = str(slot.get("character_id", ""))
        if character_id and character_id not in entities:
            problems.append(f"unknown public character entity {character_id}")
        elif character_id and entities[character_id].get("entity_type") not in {"character", "character_entity"}:
            problems.append(f"team slot {slot_id} does not reference a character entity")
        for ref in _mapping_list(slot.get("evidence_refs")):
            if not _valid_ref(ref, evidence):
                problems.append(f"slot {slot_id} has an unresolved evidence reference")
    for source in [variant, *_mapping_list(variant.get("conditions"))]:
        for ref in _mapping_list(source.get("evidence_refs")):
            if not _valid_ref(ref, evidence):
                problems.append("variant or condition has an unresolved evidence reference")
    for condition in _mapping_list(variant.get("conditions")):
        subject = _mapping(condition.get("subject"))
        if subject.get("kind") == "team_slot" and str(subject.get("slot_id", "")) not in seen_global_slot_ids:
            problems.append(f"condition {condition.get('condition_id')} references a missing team slot")
        if subject.get("kind") == "character" and str(subject.get("character_id", "")) not in {str(s.get("character_id", "")) for s in slots}:
            problems.append(f"condition {condition.get('condition_id')} references a character outside this variant")
        if subject.get("kind") not in {"team_slot", "character"}:
            problems.append(f"public variant condition has unsupported subject {subject.get('kind')}")
        if condition.get("operator") not in _OPERATORS:
            problems.append(f"condition {condition.get('condition_id')} uses an unsupported operator")
        if not condition.get("unit") or not _mapping(condition.get("measurement_context")).get("phase"):
            problems.append(f"condition {condition.get('condition_id')} lacks unit or measurement context")
        if condition.get("requirement", "hard") not in {"hard", "soft"}:
            problems.append(f"condition {condition.get('condition_id')} has an unsupported requirement level")
        if condition.get("evidence_status", "unknown") not in {"confirmed", "suggested", "unknown"}:
            problems.append(f"condition {condition.get('condition_id')} has an unsupported evidence status")
    if not _collect_declared_refs(variant):
        problems.append("complete variant has no cited evidence")
    resources = _mapping(stage.get("resource_reuse"))
    if resources.get("characters", "exclusive") == "exclusive":
        chars = [str(s.get("character_id", "")) for s in slots if s.get("character_id")]
        if len(chars) != len(set(chars)):
            problems.append("stage requires characters to be unique across its partitions")
    # Any alternative composition must itself be one published complete variant.
    return problems


def _reviewed_and_published(obj: Mapping[str, Any]) -> bool:
    return obj.get("approval_status") == "approved" and obj.get("publication_status") == "published"


def _template_applies(template: Mapping[str, Any], stage: Mapping[str, Any], task_scope: Mapping[str, Any]) -> bool:
    template_scope = _mapping(template.get("scope"))
    required_scope = ("game_version", "environment", "mode_id", "cycle_id", "stage_id", "stage_revision")
    if any(template_scope.get(key) is None for key in required_scope):
        return False
    if task_scope.get("stage_revision") is None or template_scope.get("stage_revision") != task_scope.get("stage_revision"):
        return False
    return (
        _reviewed_and_published(template)
        and _scope_mismatch(template_scope, _stage_scope(stage)) == []
        and _scope_mismatch(task_scope, template_scope) == []
        and str(stage.get("stage_id")) in _string_list(template.get("stage_ids", [stage.get("stage_id")]))
    )


def _scope_mismatch(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> list[str]:
    keys = ("game_version", "environment", "mode_id", "cycle_id", "stage_id", "stage_revision")
    return [key for key in keys if expected.get(key) is not None and actual.get(key) is not None and expected.get(key) != actual.get(key)]


def _stage_scope(stage: Mapping[str, Any]) -> dict[str, Any]:
    scope = dict(_mapping(stage.get("scope")))
    scope.setdefault("stage_id", stage.get("stage_id"))
    scope.setdefault("stage_revision", stage.get("revision"))
    return scope


def _partition_ids(stage: Mapping[str, Any]) -> set[str]:
    return {str(p.get("partition_id", p.get("id", ""))) for p in _mapping_list(stage.get("partitions"))}


def _expected_slots(stage: Mapping[str, Any]) -> dict[str, set[str]]:
    return {
        str(p.get("partition_id", p.get("id", ""))): {
            str(s.get("slot_id", s.get("id", ""))) for s in _mapping_list(p.get("slots"))
        }
        for p in _mapping_list(stage.get("partitions"))
    }


def _flatten_slots(variant: Mapping[str, Any]) -> list[dict[str, Any]]:
    teams = _mapping(variant.get("teams"))
    if not teams:
        teams = _mapping(variant.get("partitions"))
    flattened: list[dict[str, Any]] = []
    for partition_id, raw_slots in teams.items():
        for slot in _mapping_list(raw_slots):
            item = dict(slot)
            item["partition_id"] = str(partition_id)
            item["slot_id"] = str(item.get("slot_id", item.get("id", "")))
            item["character_id"] = str(item.get("character_id", item.get("character_entity_id", "")))
            flattened.append(item)
    return flattened


def _check_roster(slots: Sequence[Mapping[str, Any]], characters: Mapping[str, Mapping[str, Any]], fixed: set[str], excluded: set[str], roster_complete: bool) -> dict[str, Any]:
    actual = {str(s.get("character_id", "")) for s in slots}
    reasons: list[dict[str, str]] = []
    if fixed - actual:
        reasons.append({"code": "fixed_character_missing", "characters": ", ".join(sorted(fixed - actual))})
    if excluded & actual:
        reasons.append({"code": "excluded_character_used", "characters": ", ".join(sorted(excluded & actual))})
    pending: list[dict[str, str]] = []
    for character_id in sorted(actual):
        entry = characters.get(character_id)
        if entry is None:
            if roster_complete:
                reasons.append({"code": "character_not_in_complete_roster", "characters": character_id})
            else:
                pending.append({"character_id": character_id, "reason": "character_not_observed_in_partial_roster"})
            continue
        ownership = entry.get("ownership", "unknown")
        if ownership == "not_owned":
            reasons.append({"code": "character_confirmed_not_owned", "characters": character_id})
        elif ownership != "owned":
            pending.append({"character_id": character_id, "reason": "ownership_unknown"})
    return {"rejected": bool(reasons), "reasons": reasons, "pending": pending}


def _conditions_for(variant: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [dict(c) for c in _mapping_list(variant.get("conditions"))]


def _evaluate_conditions(conditions: Sequence[Mapping[str, Any]], slots: Sequence[Mapping[str, Any]], characters: Mapping[str, Mapping[str, Any]], task: Mapping[str, Any], feedback: Any) -> list[dict[str, Any]]:
    by_slot = {str(s.get("slot_id")): s for s in slots}
    result: list[dict[str, Any]] = []
    for condition in conditions:
        operator = str(condition.get("operator", ""))
        if operator not in _OPERATORS:
            raise _InputError("unsupported_capability", f"unsupported condition operator: {operator}")
        subject = _mapping(condition.get("subject"))
        kind = subject.get("kind")
        owner: Mapping[str, Any] | None = None
        if kind == "team_slot":
            slot = by_slot.get(str(subject.get("slot_id", "")))
            owner = characters.get(str(slot.get("character_id", ""))) if slot else None
        elif kind == "character":
            owner = characters.get(str(subject.get("character_id", "")))
        elif kind == "feedback":
            owner = _mapping(feedback)
        elif kind == "task":
            owner = task
        else:
            raise _InputError("unsupported_capability", f"unsupported condition subject: {kind}")
        field_state, actual, local_ref = _read_condition_value(owner, str(condition.get("attribute", "")))
        status = "unknown"
        reason = field_state
        if field_state == "confirmed":
            try:
                matched = _compare(actual, condition.get("value"), operator)
                status = "satisfied" if matched else "not_satisfied"
                reason = "condition_met" if matched else "condition_not_met"
            except (TypeError, ValueError):
                reason = "incomparable_values"
        requirement = "hard" if condition.get("requirement", "hard") == "hard" else "soft"
        result.append({
            "condition_id": condition.get("condition_id", condition.get("id")),
            "requirement": requirement,
            "evidence_status": condition.get("evidence_status", "unknown"),
            "match_status": status,
            "reason_code": reason,
            "expected": {"operator": operator, "value": condition.get("value"), "unit": condition.get("unit"), "measurement_context": condition.get("measurement_context")},
            "observed": actual if status != "unknown" else None,
            "local_field_refs": [local_ref] if local_ref else [],
            "evidence_refs": _mapping_list(condition.get("evidence_refs")),
        })
    return result


def _read_condition_value(owner: Mapping[str, Any] | None, attribute: str) -> tuple[str, Any, str | None]:
    if owner is None:
        return "missing_field", None, None
    fields = _mapping(owner.get("fields"))
    raw = fields.get(attribute)
    if raw is None:
        raw = owner.get("attributes", {}).get(attribute) if isinstance(owner.get("attributes"), Mapping) else None
        if raw is None:
            return "missing_field", None, None
        if isinstance(raw, Mapping) and raw.get("state") in {"confirmed", "player_confirmed", "source_verified"}:
            if "value" not in raw or raw.get("value") is None:
                return "missing_field", None, None
            return "confirmed", raw.get("value"), f"snapshot.attributes.{attribute}"
        return "unconfirmed_field", None, None
    if not isinstance(raw, Mapping):
        return "unconfirmed_field", None, None
    state = raw.get("state", "unknown")
    if state not in {"confirmed", "player_confirmed", "source_verified", "user_reported"}:
        return ("stale_field" if state == "stale" else "conflicting_field" if state == "conflict" else "unconfirmed_field"), None, None
    if "value" not in raw or raw.get("value") is None:
        return "missing_field", None, None
    local_id = raw.get("local_source_id")
    return "confirmed", raw.get("value"), f"snapshot.fields.{attribute}" if not local_id else f"snapshot.fields.{attribute}@{local_id}"


def _compare(actual: Any, expected: Any, operator: str) -> bool:
    if operator == "eq":
        return _values_equal(actual, expected)
    if operator == "neq":
        return not _values_equal(actual, expected)
    if operator == "gt":
        _require_numeric(actual, expected)
        return actual > expected
    if operator == "gte":
        _require_numeric(actual, expected)
        return actual >= expected
    if operator == "lt":
        _require_numeric(actual, expected)
        return actual < expected
    if operator == "lte":
        _require_numeric(actual, expected)
        return actual <= expected
    if operator == "in":
        if not isinstance(expected, Sequence) or isinstance(expected, (str, bytes)):
            raise TypeError("in operator expects an array value")
        return any(_values_equal(actual, option) for option in expected)
    if operator == "contains":
        if isinstance(actual, str) and isinstance(expected, str):
            return expected in actual
        if isinstance(actual, Sequence) and not isinstance(actual, (str, bytes)):
            return any(_values_equal(expected, option) for option in actual)
        raise TypeError("contains operator requires a string or array")
    raise ValueError("unsupported operator")


def _values_equal(actual: Any, expected: Any) -> bool:
    if isinstance(actual, bool) or isinstance(expected, bool):
        return isinstance(actual, bool) and isinstance(expected, bool) and actual is expected
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        return actual == expected
    return type(actual) is type(expected) and actual == expected


def _require_numeric(actual: Any, expected: Any) -> None:
    if isinstance(actual, bool) or isinstance(expected, bool) or not isinstance(actual, (int, float)) or not isinstance(expected, (int, float)):
        raise TypeError("ordered comparison requires numeric values")


def _equipment_options(slots: Sequence[Mapping[str, Any]], equipment: Sequence[Mapping[str, Any]], locked: set[str], stage: Mapping[str, Any], allow_rearrangement: bool) -> dict[str, Any]:
    requirements: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for slot in slots:
        for requirement in _mapping_list(slot.get("equipment_requirements")):
            requirements.append((slot, requirement))
    if not requirements:
        return {"current": {"assignments": [], "actions": []}, "rearranged": {"assignments": [], "actions": []}, "reasons": []}
    current_by_owner: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for item in equipment:
        owner = item.get("equipped_by")
        if owner is not None:
            current_by_owner[str(owner)].append(item)
    current_choices: list[list[Mapping[str, Any]]] = []
    move_choices: list[list[Mapping[str, Any]]] = []
    for slot, requirement in requirements:
        owner = str(slot.get("character_id", ""))
        current_candidates = [e for e in current_by_owner.get(owner, []) if _equipment_matches(e, requirement)]
        all_candidates = [e for e in equipment if _equipment_matches(e, requirement)]
        current_choices.append(current_candidates)
        move_choices.append(all_candidates)
    current = _first_assignment(requirements, current_choices, equipment, locked, stage, allow_unconfirmed=True)
    known_ids = {str(item.get("local_instance_id")) for item in equipment if item.get("local_instance_id")}
    missing_locked = locked - known_ids
    rearranged = (
        _first_assignment(requirements, move_choices, equipment, locked, stage, allow_unconfirmed=False)
        if allow_rearrangement and not missing_locked else None
    )
    search_limited = False
    if current and current[0].get("no_feasible_found"):
        search_limited = True
        current = None
    if rearranged and rearranged[0].get("no_feasible_found"):
        search_limited = True
        rearranged = None
    reasons: list[str] = []
    if current is None:
        reasons.append("current_equipment_does_not_meet_requirements")
    if rearranged is None:
        reasons.append("locked_instance_not_observed" if missing_locked else "no_rearrangement_with_reliable_unique_instances")
    return {
        "current": _assignment_result(current, requirements, equipment) if current else None,
        "rearranged": _assignment_result(rearranged, requirements, equipment) if rearranged else None,
        "search_limited": search_limited,
        "reasons": reasons,
    }


def _equipment_matches(item: Mapping[str, Any], requirement: Mapping[str, Any]) -> bool:
    if requirement.get("kind") and item.get("kind") != requirement.get("kind"):
        return False
    if requirement.get("slot") and item.get("slot") != requirement.get("slot"):
        return False
    allowed = _string_list(requirement.get("public_type_ids"))
    exact = requirement.get("public_type_id")
    return not exact and not allowed or item.get("public_type_id") == exact or item.get("public_type_id") in allowed


def _first_assignment(requirements: Sequence[tuple[Mapping[str, Any], Mapping[str, Any]]], choices: Sequence[Sequence[Mapping[str, Any]]], equipment: Sequence[Mapping[str, Any]], locked: set[str], stage: Mapping[str, Any], *, allow_unconfirmed: bool) -> list[dict[str, Any]] | None:
    if any(not group for group in choices):
        return None
    exclusive = _mapping(stage.get("resource_reuse")).get("equipment", "exclusive") == "exclusive"
    chosen: list[dict[str, Any]] = []
    used: set[str] = set()
    candidates: list[dict[str, Any]] = []
    remaining_nodes = 50_000
    truncated = False

    def search(index: int) -> None:
        nonlocal remaining_nodes, truncated
        remaining_nodes -= 1
        if remaining_nodes < 0 or len(candidates) >= 256:
            truncated = True
            return
        if index == len(requirements):
            destinations = [
                (str(entry["to_character_id"]), str(entry["kind"]), str(entry["requirement"].get("slot", "")))
                for entry in chosen
            ]
            if len(destinations) != len(set(destinations)):
                return
            selected = {str(entry["local_instance_id"]) for entry in chosen}
            final_assignments = [dict(entry) for entry in chosen]
            for entry in chosen:
                destination = (str(entry["to_character_id"]), str(entry["kind"]), str(entry["requirement"].get("slot", "")))
                occupants = [
                    item for item in equipment
                    if item.get("equipped_by") is not None
                    and (str(item.get("equipped_by")), str(item.get("kind", "")), str(item.get("slot", ""))) == destination
                    and str(item.get("local_instance_id", "")) != str(entry["local_instance_id"])
                    and str(item.get("local_instance_id", "")) not in selected
                ]
                if occupants and allow_unconfirmed:
                    return
                for occupant in occupants:
                    occupant_id = str(occupant.get("local_instance_id", ""))
                    if occupant_id in locked or occupant.get("identity_state") not in {"player_confirmed", "source_verified"}:
                        return
                    final_assignments.append({
                        "slot_id": entry["slot_id"], "partition_id": entry["partition_id"],
                        "character_id": entry["character_id"], "local_instance_id": occupant_id,
                        "public_type_id": occupant.get("public_type_id"), "kind": occupant.get("kind"),
                        "from_character_id": destination[0], "to_character_id": None,
                        "action": "unequip", "requirement": dict(entry["requirement"]),
                    })
            actions = [
                {
                    "local_instance_id": entry["local_instance_id"],
                    "from_character_id": entry["from_character_id"],
                    "to_character_id": entry["to_character_id"],
                    **({"action": entry["action"]} if entry.get("action") else {}),
                }
                for entry in final_assignments
                if entry.get("action") == "unequip" or entry["from_character_id"] != entry["to_character_id"]
            ]
            candidates.append({"assignments": final_assignments, "actions": actions})
            return
        slot, requirement = requirements[index]
        current_owner = str(slot.get("character_id", ""))
        ordered_choices = sorted(
            choices[index],
            key=lambda item: (str(item.get("equipped_by", "")) != current_owner, str(item.get("local_instance_id", ""))),
        )
        for item in ordered_choices:
            item_id = str(item.get("local_instance_id", ""))
            owner = str(item.get("equipped_by", "")) if item.get("equipped_by") is not None else None
            identity_ok = item.get("identity_state") in {"player_confirmed", "source_verified"}
            if not item_id or (exclusive and item_id in used):
                continue
            if item_id in locked and owner != current_owner:
                continue
            if not allow_unconfirmed and not identity_ok:
                continue
            if not allow_unconfirmed and item_id in locked and owner != current_owner:
                continue
            chosen.append({"slot_id": slot.get("slot_id"), "partition_id": slot.get("partition_id"), "character_id": current_owner, "local_instance_id": item_id, "public_type_id": item.get("public_type_id"), "kind": item.get("kind"), "from_character_id": owner, "to_character_id": current_owner, "requirement": dict(requirement)})
            used.add(item_id)
            search(index + 1)
            used.discard(item_id)
            chosen.pop()
            if truncated:
                break

    search(0)
    if not candidates:
        if truncated:
            return [{"assignments": [], "actions": [], "search_truncated": True, "no_feasible_found": True}]
        return None
    candidates.sort(key=lambda item: (
        len(item["actions"]),
        sum(action.get("from_character_id") != action.get("to_character_id") for action in item["actions"] if action.get("action") != "unequip"),
        tuple(str(entry["local_instance_id"]) for entry in item["assignments"]),
    ))
    best = candidates[0]
    best["search_truncated"] = truncated
    return [best]


def _assignment_result(result: list[dict[str, Any]], requirements: Sequence[Any], equipment: Sequence[Any]) -> dict[str, Any]:
    return result[0]


def _cultivation(variant: Mapping[str, Any], snapshot: Mapping[str, Any], slots: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    characters = _objects_by_id(snapshot.get("characters"), "entity_id")
    inventory = _objects_by_id(snapshot.get("materials"), "material_id")
    materials_complete = _mapping(snapshot.get("coverage")).get("materials") == "complete"
    for req in _mapping_list(variant.get("cultivation_requirements")):
        subject = _mapping(req.get("subject"))
        character_id = str(subject.get("character_id", ""))
        current_state, current, _ = _read_condition_value(characters.get(character_id), str(req.get("current_field", "")))
        target = req.get("target_value")
        gap = None
        if current_state == "confirmed" and isinstance(current, (int, float)) and isinstance(target, (int, float)):
            gap = max(0, target - current)
        cost_result: dict[str, Any] = {"status": "not_calculated", "reason": "incomplete_or_unverified_cost_inputs"}
        rule = _mapping(req.get("cost_rule"))
        materials = _mapping_list(rule.get("materials"))
        if rule.get("applicable") is True and rule.get("revision") and materials and materials_complete and gap is not None:
            costs: list[dict[str, Any]] = []
            complete = True
            for cost in materials:
                material_id = str(cost.get("material_id", ""))
                amount = cost.get("amount")
                material = inventory.get(material_id)
                if material is None or material.get("state") != "confirmed" or not isinstance(amount, (int, float)) or not isinstance(material.get("count"), (int, float)):
                    complete = False
                    break
                costs.append({"material_id": material_id, "amount": amount, "available": material.get("count"), "net_shortage": max(0, amount - material["count"]) if isinstance(material.get("count"), (int, float)) else None})
            if complete:
                cost_result = {"status": "calculated", "rule_revision": rule["revision"], "materials": costs}
        steps.append({
            "requirement_id": req.get("requirement_id", req.get("id")),
            "character_id": character_id,
            "category": req.get("category"),
            "current": current if current_state == "confirmed" else None,
            "target": target,
            "gap": gap,
            "priority": req.get("priority"),
            "reason": req.get("reason"),
            "cost": cost_result,
            "evidence_refs": _mapping_list(req.get("evidence_refs")),
        })
    return steps


def _troubleshooting(feedback: Any, bundle: Mapping[str, Any], variants: Sequence[Mapping[str, Any]], characters: Mapping[str, Mapping[str, Any]], task: Mapping[str, Any], task_scope: Mapping[str, Any], withdrawn: set[str]) -> dict[str, Any]:
    if not isinstance(feedback, Mapping):
        return {"status": "not_requested", "suggestions": []}
    published = {str(v.get("id")): v for v in variants if _reviewed_and_published(v)}
    templates = _objects_by_id(bundle.get("templates"), "id")
    stages = _objects_by_id(bundle.get("stages"), "stage_id")
    selected_stage = stages.get(str(task_scope.get("stage_id", "")))
    matches: list[dict[str, Any]] = []
    unsupported: list[str] = []
    for rule in _mapping_list(bundle.get("troubleshooting")):
        if not _reviewed_and_published(rule) or _is_withdrawn(rule, withdrawn, "troubleshooting"):
            continue
        rule_scope = _mapping(rule.get("scope"))
        required_scope = ("game_version", "environment", "mode_id", "cycle_id", "stage_id", "stage_revision")
        if not selected_stage or any(rule_scope.get(key) is None for key in required_scope):
            continue
        if _scope_mismatch(task_scope, rule_scope):
            continue
        if str(task_scope.get("stage_id")) not in _string_list(rule.get("stage_ids")):
            continue
        if not _mapping_list(rule.get("trigger_conditions")):
            unsupported.append(str(rule.get("id")))
            continue
        try:
            trigger = _evaluate_conditions(_mapping_list(rule.get("trigger_conditions")), [], characters, task, feedback)
        except _InputError:
            unsupported.append(str(rule.get("id")))
            continue
        if any(c["match_status"] == "unknown" for c in trigger):
            unsupported.append(str(rule.get("id")))
            continue
        if all(c["match_status"] == "satisfied" for c in trigger):
            target_id = rule.get("suggested_variant_id")
            suggestion: dict[str, Any] = {"rule_id": rule.get("id"), "evidence_refs": _mapping_list(rule.get("evidence_refs")), "condition_results": trigger}
            target_variant = published.get(str(target_id)) if target_id else None
            target_template = templates.get(str(target_variant.get("template_id"))) if target_variant else None
            target_is_applicable = bool(target_template and _template_applies(target_template, selected_stage, task_scope))
            if target_variant and target_is_applicable and not _is_withdrawn(target_variant, withdrawn, "variant"):
                suggestion["suggested_variant_id"] = str(target_id)
                suggestion["suggested_variant_revision"] = target_variant.get("revision")
            elif rule.get("action") == "recheck_conditions":
                suggestion["action"] = "recheck_conditions"
            elif rule.get("action") == "review_cultivation_gaps":
                suggestion["action"] = "review_cultivation_gaps"
            else:
                continue
            matches.append(suggestion)
    status = "suggestions_available" if matches else "unable_to_determine"
    return {"status": status, "suggestions": matches, "unsupported_rules": unsupported, "explanation": None if matches else "没有触发条件明确且有审核依据的排障规则；不会自动学习或发明建议。"}


def _citation_catalog(bundle: Mapping[str, Any], refs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    evidence = _objects_by_id(bundle.get("evidence"), "id")
    catalog: list[dict[str, Any]] = []
    for ref in refs:
        item = evidence.get(str(ref.get("id")))
        if item and item.get("revision") == ref.get("revision"):
            catalog.append({"id": item.get("id"), "revision": item.get("revision"), "index_release_id": _mapping(bundle.get("manifest")).get("index_release_id"), "title": item.get("title"), "source_url": item.get("source_url"), "locator": item.get("locator"), "excerpt": item.get("excerpt"), "evidence_status": item.get("status")})
    return catalog


def _collect_evidence_refs(template: Mapping[str, Any], variant: Mapping[str, Any], conditions: Sequence[Mapping[str, Any]], evidence: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for source in (template, variant, *conditions, *_mapping_list(variant.get("steps")), *_mapping_list(variant.get("mechanics")), *_mapping_list(variant.get("cultivation_requirements")), *_mapping_list(variant.get("failure_conditions"))):
        refs.extend(dict(r) for r in _mapping_list(source.get("evidence_refs")) if _valid_ref(r, evidence))
    for slot in _flatten_slots(variant):
        refs.extend(dict(r) for r in _mapping_list(slot.get("evidence_refs")) if _valid_ref(r, evidence))
    return _dedupe_refs(refs)


def _valid_ref(ref: Mapping[str, Any], index: Mapping[str, Mapping[str, Any]]) -> bool:
    item = index.get(str(ref.get("id", "")))
    return bool(item and item.get("revision") == ref.get("revision"))


def _is_withdrawn(obj: Mapping[str, Any], withdrawn: set[str], kind: str) -> bool:
    refs = [*(_mapping_list(obj.get("evidence_refs"))), *(_mapping_list(obj.get("citations")))]
    for condition in _mapping_list(obj.get("conditions")) + _mapping_list(obj.get("trigger_conditions")):
        refs.extend(_mapping_list(condition.get("evidence_refs")))
    object_key = f"{obj.get('id')}@{obj.get('revision')}"
    return str(obj.get("id")) in withdrawn or object_key in withdrawn or any(
        str(r.get("id")) in withdrawn or f"{r.get('id')}@{r.get('revision')}" in withdrawn for r in refs
    )


def _withdrawn_refs(request: Mapping[str, Any]) -> set[str]:
    validity = _mapping(request.get("latest_known_validity"))
    refs = validity.get("withdrawn_public_refs")
    result = {r for r in refs if isinstance(r, str)} if isinstance(refs, Sequence) and not isinstance(refs, (str, bytes)) else set()
    result.update(f"{r.get('id')}@{r.get('revision')}" for r in _mapping_list(refs) if r.get("id") is not None and r.get("revision") is not None)
    return result


def _collect_declared_refs(variant: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    refs: list[Mapping[str, Any]] = []
    for source in (variant, *_mapping_list(variant.get("conditions")), *_mapping_list(variant.get("steps")), *_mapping_list(variant.get("mechanics")), *_mapping_list(variant.get("cultivation_requirements")), *_mapping_list(variant.get("failure_conditions")), *_flatten_slots(variant)):
        refs.extend(_mapping_list(source.get("evidence_refs")))
    return refs


def _template_summary(template: Mapping[str, Any]) -> dict[str, Any]:
    return {key: template.get(key) for key in ("id", "revision", "title", "scope")}


def _variant_summary(variant: Mapping[str, Any]) -> dict[str, Any]:
    return {key: variant.get(key) for key in ("id", "revision", "title", "template_id", "variant_kind")}


def _as_plan(item: Mapping[str, Any], plan_kind: str, release_id: Any) -> dict[str, Any]:
    equipment = item["current_equipment"] if plan_kind == "current" else item["rearranged_equipment"] if plan_kind == "rearrangement" else None
    allocation_truncated = bool(equipment and equipment.get("search_truncated"))
    result = {
        "plan_kind": plan_kind,
        "index_release_id": release_id,
        "template": item["template"],
        "variant": item["variant"],
        "team": item["team"],
        "equipment": equipment,
        "condition_results": item["condition_results"],
        "strategy": item["strategy"],
        "cultivation": item["cultivation"],
        "evidence_refs": item["evidence_refs"],
        "ranking": {"known_condition_count": sum(c["match_status"] == "satisfied" for c in item["condition_results"]), "unknown_condition_count": sum(c["match_status"] == "unknown" for c in item["condition_results"]), "equipment_changes": len(equipment["actions"]) if equipment else 0, "allocation_search_truncated": allocation_truncated, "meaning": "仅用于适配顺序，不是通关概率"},
        "warnings": [c["condition_id"] for c in item["condition_results"] if c["match_status"] != "satisfied"] + (["equipment_allocation_search_truncated"] if allocation_truncated else []),
    }
    if plan_kind == "pending_confirmation":
        result["pending_reasons"] = item.get("pending_reasons", [])
        result["equipment_status"] = "unknown" if item.get("equipment_unknown") else "assessed"
    return result


def _public_candidate(item: Mapping[str, Any]) -> dict[str, Any]:
    reasons = [*item["role_unknown"], *[{"condition_id": c["condition_id"], "reason": c["reason_code"]} for c in item["hard_unknown"]]]
    if item.get("equipment_unknown"):
        reasons.append({"reason": item.get("equipment_unknown_reason", "inventory_coverage_incomplete")})
    return {**item, "pending_reasons": reasons}


def _rank_key(conditions: Sequence[Mapping[str, Any]], equipment: Mapping[str, Any]) -> tuple[Any, ...]:
    failed_soft = sum(c["requirement"] == "soft" and c["match_status"] == "not_satisfied" for c in conditions)
    unknown = sum(c["match_status"] == "unknown" for c in conditions)
    suggested = sum(c["evidence_status"] != "confirmed" for c in conditions)
    change_count = len(_mapping(equipment.get("rearranged")).get("actions", []))
    return failed_soft, unknown, suggested, change_count


def _citation_refs_from_troubleshooting(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    refs: list[Mapping[str, Any]] = []
    for suggestion in _mapping_list(result.get("suggestions")):
        refs.extend(_mapping_list(suggestion.get("evidence_refs")))
    return refs


def _all_result_refs(*groups: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for group in groups:
        for item in group:
            refs.extend(dict(r) for r in _mapping_list(item.get("evidence_refs")))
            refs.extend(_citation_refs_from_troubleshooting(item))
    return _dedupe_refs(refs)


def _reference_issues(value: Any, available_refs: set[tuple[str, str]], owner_id: str) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).endswith("_refs"):
                for ref in _mapping_list(child):
                    identity = (str(ref.get("id", "")), str(ref.get("revision", "")))
                    if not identity[0] or not identity[1] or identity not in available_refs:
                        issues.append({"code": "missing_member", "message": f"{owner_id} has an unresolved {key} reference {identity[0]}@{identity[1]}"})
            else:
                issues.extend(_reference_issues(child, available_refs, owner_id))
    elif isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
        for child in value:
            issues.extend(_reference_issues(child, available_refs, owner_id))
    return issues


def _degradation_reasons(status: str, matching_templates: Sequence[Mapping[str, Any]], rejections: Sequence[Mapping[str, Any]], pending: Sequence[Mapping[str, Any]]) -> list[str]:
    reasons: list[str] = []
    if not matching_templates:
        reasons.append("no_reviewed_template_for_selected_scope")
    if rejections:
        reasons.extend(str(item.get("code")) for item in rejections)
    if pending:
        reasons.append("additional_confirmation_or_coverage_is_required")
    if status == "coverage_insufficient" and not reasons:
        reasons.append("bundle_or_account_coverage_is_insufficient")
    return list(dict.fromkeys(reasons))


def _rejection(variant_id: str, code: str, reason: str, details: Any = None) -> dict[str, Any]:
    return {"variant_id": variant_id, "code": code, "reason": reason, "details": details or []}


def _error_result(request: Any, code: str, message: str, details: Mapping[str, Any] | None = None) -> dict[str, Any]:
    mapping = _mapping(request)
    return {
        "contract_version": _CONTRACT,
        "schema_id": "AnalysisResult",
        "schema_version": _CONTRACT,
        "planner_version": PLANNER_VERSION,
        "request_id": mapping.get("request_id"),
        "status": "error",
        "error": {"code": code, "message": message, "retryable": False, "details": dict(details or {})},
        "current_equipment_plans": [],
        "rearrangement_plans": [],
        "pending_confirmation_candidates": [],
        "citations": [],
    }


def _objects_by_id(value: Any, key: str) -> dict[str, Mapping[str, Any]]:
    return {str(item.get(key)): item for item in _mapping_list(value) if item.get(key) is not None}


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _mapping_list(value: Any) -> list[Mapping[str, Any]]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [v for v in value if isinstance(v, Mapping)]


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return []
    return [str(v) for v in value]


def _dedupe_refs(refs: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    found: dict[tuple[str, str], dict[str, Any]] = {}
    for ref in refs:
        if ref.get("id") is not None and ref.get("revision") is not None:
            found[(str(ref["id"]), str(ref["revision"]))] = {"id": ref["id"], "revision": ref["revision"]}
    return [found[key] for key in sorted(found)]
