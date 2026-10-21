"""Draft-contract planner implementation. This module intentionally has no I/O."""

from __future__ import annotations

from copy import deepcopy
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

from .conditions import UnsupportedSemantics, evaluate_conditions, validate_condition
from .cultivation import cultivation
from .validation import canonical_hash, disabled_objects, objects, validate_bundle, validate_json_request

PLANNER_VERSION = "0.2.0"
ADAPTER_PROFILE = "starhelp.local.v0.2"
_CONTRACT = "0.1-draft"
_SUPPORTED_CAPABILITIES = {"starhelp.local-profile.v0.2"}
_OPERATORS = {"eq", "neq", "gt", "gte", "lt", "lte", "in", "contains"}


def analyze_request(request: Mapping[str, Any]) -> dict[str, Any]:
    """Return a JSON-compatible result for one already-materialized request."""
    try:
        validate_json_request(request)
        return _analyze(deepcopy(request))
    except _InputError as exc:
        return _error_result(request, exc.code, str(exc), exc.details)
    except (KeyError, TypeError, ValueError, OverflowError, AttributeError) as exc:
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

    if request.get("adapter_profile") != ADAPTER_PROFILE or bundle.get("adapter_profile") != ADAPTER_PROFILE:
        raise _InputError("unsupported_profile", "request and bundle must select the supported local adapter profile")
    if request.get("local_rule_version") not in {None, PLANNER_VERSION}:
        raise _InputError("unsupported_rule_version", "requested local rule version is unavailable")
    capabilities = request.get("required_capabilities", [])
    if not isinstance(capabilities, list) or any(type(capability) is not str or capability not in _SUPPORTED_CAPABILITIES for capability in capabilities):
        raise _InputError("unsupported_capability", "request needs unsupported planner capabilities")
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
        key for key in ("game_version", "environment", "mode_id", "cycle_id", "stage_id", "stage_revision")
        if task_scope.get(key) is None or stage_scope.get(key) is None
    )
    if scope_mismatch:
        raise _InputError("scope_mismatch", "selected task does not match the bundled stage", {"fields": scope_mismatch})
    reported_withdrawn = _withdrawn_refs(request)
    incompatible = {
        key for key, obj in objects(bundle).items()
        if _scope_mismatch(task_scope, _mapping(obj.get("scope")))
        or any(obj.get(field) is not None and obj[field] != task_scope.get(field) for field in ("game_version", "environment"))
    }
    disabled = disabled_objects(bundle, reported_withdrawn, incompatible)
    if ("stage", stage["stage_id"], stage["revision"]) in disabled:
        raise _InputError("withdrawn_public_object", "selected stage or its dependencies are unavailable")

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
    matching_templates = [t for t in templates if _template_applies(t, stage, task_scope) and any(canonical_hash(task["public_goal"]) == canonical_hash(goal) for goal in t.get("public_goals", [])) and not _is_unavailable(t, disabled, "template")]
    matching_ids = {str(t.get("id")) for t in matching_templates}

    for variant in variants:
        template_id = str(variant.get("template_id", ""))
        if template_id not in matching_ids or not _reviewed_and_published(variant):
            continue
        variant_id = str(variant.get("id", ""))
        if _is_unavailable(variant, disabled, "variant"):
            rejection_reasons.append(_rejection(variant_id, "unavailable_public_dependency", "variant or its dependency is unavailable or outside the selected scope"))
            continue
        template = next(t for t in matching_templates if str(t.get("id")) == template_id)
        variant_issues = _validate_variant(variant, stage, entities, evidence, manifest.get("attribute_definitions", {}))
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
        accepted_items, pending_items, rejected_items = _variant_candidates(
            template, variant, slots, snapshot, task, stage, evidence,
            manifest.get("attribute_definitions", {}), role_state["pending"], locked_instances,
            request.get("evaluation_time"),
        )
        evaluated.extend(accepted_items)
        pending.extend(pending_items)
        rejection_reasons.extend(rejected_items)

    evaluated.sort(key=lambda x: x["sort"])
    pending.sort(key=lambda x: x["sort"])
    current_plans = [_as_plan(item, "current", release_id) for item in evaluated if item["candidate_plan_kind"] == "current"]
    rearrangement_plans = [_as_plan(item, "rearrangement", release_id) for item in evaluated if item["candidate_plan_kind"] == "rearrangement"]
    pending_candidates = [_as_plan(item, "pending_confirmation", release_id) for item in pending]
    troubleshooting = _troubleshooting(request.get("feedback"), bundle, variants, snapshot, task, task_scope, disabled, manifest.get("attribute_definitions", {}), request.get("evaluation_time"), [*current_plans, *rearrangement_plans, *pending_candidates])
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
        "adapter_profile": ADAPTER_PROFILE,
        "supported_capabilities": sorted(_SUPPORTED_CAPABILITIES),
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
        "local_rule_version": PLANNER_VERSION,
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
            "withdrawn_public_refs": sorted(reported_withdrawn),
            "unavailable_public_objects": [{"kind": kind, "id": identifier, "revision": revision} for kind, identifier, revision in sorted(disabled)],
        },
        "degradation": {
            "reasons": _degradation_reasons(status, matching_templates, rejection_reasons, pending_candidates),
            "coverage_gaps": _mapping_list(stage.get("coverage_gaps")),
        },
        "citations": _citation_catalog(bundle, _dedupe_refs([*_all_result_refs(current_plans, rearrangement_plans, pending_candidates, rejection_reasons, [troubleshooting]), *_mapping_list(stage.get("evidence_refs"))])),
        "limitations": ["匹配和排序不代表通关概率。", "此实现使用本地 v0.2 适配提案，M0 共同契约尚未冻结。"],
    }


def _variant_candidates(template: Mapping[str, Any], variant: Mapping[str, Any], slots: Sequence[Mapping[str, Any]], snapshot: Mapping[str, Any], task: Mapping[str, Any], stage: Mapping[str, Any], evidence: Mapping[str, Any], definitions: Mapping[str, Any], role_unknown: list[Any], locked: set[str], evaluation_time: str | None) -> tuple[list[Any], list[Any], list[Any]]:
    options = _equipment_options(slots, snapshot.get("equipment_instances", []), locked, stage, task.get("allow_rearrangement", False))
    candidates: list[tuple[str, Any]] = []
    if options["current"]:
        candidates.append(("current", options["current"]))
    candidates.extend(("rearrangement", option) for option in options.get("rearrangement_candidates", []) if option.get("actions"))
    equipment_unknown_reason = None
    if not candidates:
        if snapshot.get("coverage", {}).get("inventory") != "complete" or options.get("search_limited"):
            equipment_unknown_reason = "allocation_search_incomplete" if options.get("search_limited") else "inventory_coverage_incomplete"
            candidates.append(("current", None))
        else:
            return [], [], [_rejection(str(variant["id"]), "equipment_conflict", "no legal equipment assignment", options["reasons"])]
    accepted: dict[str, list[Any]] = defaultdict(list)
    pending: dict[str, list[Any]] = defaultdict(list)
    failed: dict[str, list[Any]] = defaultdict(list)
    for category, allocation in candidates:
        conditions = evaluate_conditions(
            variant.get("conditions", []), slots, snapshot, task, definitions,
            allocation=allocation, evaluation_time=evaluation_time,
        )
        hard_failed = [c for c in conditions if c["requirement"] == "hard" and c["match_status"] == "not_satisfied"]
        hard_unknown = [c for c in conditions if c["requirement"] == "hard" and c["match_status"] == "unknown"]
        steps, total_cost = cultivation(variant, snapshot, slots, task, definitions, allocation, evaluation_time)
        item = {
            "template": _template_summary(template), "variant": _variant_summary(variant), "team": slots,
            "candidate_plan_kind": category, "candidate_equipment": allocation,
            "current_equipment": allocation if category == "current" else None,
            "rearranged_equipment": allocation if category == "rearrangement" else None,
            "condition_results": conditions, "hard_unknown": hard_unknown, "role_unknown": role_unknown,
            "cultivation": steps, "cultivation_cost": total_cost,
            "strategy": {key: _mapping_list(variant.get(key)) for key in ("steps", "mechanics", "failure_conditions", "risks")},
            "evidence_refs": _collect_evidence_refs(template, variant, conditions, evidence),
            "sort": (*_rank_key(conditions, {"rearranged": allocation}), str(variant["id"]), tuple(str(a["local_instance_id"]) for a in (allocation or {}).get("assignments", []))),
            "equipment_unknown": equipment_unknown_reason is not None,
            "equipment_unknown_reason": equipment_unknown_reason,
        }
        if hard_failed and not equipment_unknown_reason:
            failed[category].append(item)
        elif role_unknown or hard_unknown or equipment_unknown_reason:
            pending[category].append(_public_candidate(item))
        else:
            accepted[category].append(item)
    selected: list[Any] = []
    waiting: list[Any] = []
    rejections: list[Any] = []
    for category in ("current", "rearrangement"):
        if accepted[category]:
            selected.append(min(accepted[category], key=lambda item: item["sort"]))
        elif pending[category]:
            waiting.append(min(pending[category], key=lambda item: item["sort"]))
        elif failed[category]:
            item = min(failed[category], key=lambda item: item["sort"])
            if category == "rearrangement" and item["candidate_equipment"].get("search_truncated"):
                unknown_conditions = [{**condition, "match_status": "unknown", "reason_code": "allocation_search_incomplete", "observed": None, "local_field_refs": [], "field_basis": {}} for condition in item["condition_results"]]
                waiting.append(_public_candidate({
                    **item, "candidate_equipment": None, "condition_results": unknown_conditions,
                    "hard_unknown": [], "equipment_unknown": True, "equipment_unknown_reason": "allocation_search_incomplete",
                    "cultivation": [], "cultivation_cost": {"status": "not_calculated", "net_status": "not_calculated", "reason": "allocation_search_incomplete", "materials": []},
                }))
                continue
            rejections.append({
                **_rejection(str(variant["id"]), "hard_condition_failed", "hard condition is not satisfied", item["condition_results"]),
                "plan_kind": category, "cultivation": item["cultivation"], "cultivation_cost": item["cultivation_cost"], "evidence_refs": item["evidence_refs"],
            })
    return selected, waiting, rejections


def _validate_bundle(bundle: Mapping[str, Any]) -> list[dict[str, str]]:
    problems = validate_bundle(bundle, _SUPPORTED_CAPABILITIES, _CONTRACT)
    if bundle.get("schema_id") != "PublicBundle" or bundle.get("contract_version") != _CONTRACT or bundle.get("schema_version") != _CONTRACT:
        problems.append({"code": "unsupported_schema", "message": "unsupported public bundle schema"})
    manifest = bundle["manifest"]
    if not isinstance(manifest.get("index_release_id"), str) or not manifest["index_release_id"]:
        problems.append({"code": "missing_release", "message": "manifest.index_release_id is required"})
    schemas = manifest.get("object_schemas", {})
    if not isinstance(schemas, dict) or any(schemas.get(kind) != _CONTRACT for kind in ("stage", "entity", "template", "variant", "evidence", "troubleshooting")):
        problems.append({"code": "unsupported_schema", "message": "unsupported object schema declarations"})
    for stage in bundle["stages"]:
        scope = _mapping(stage.get("scope"))
        if scope.get("stage_id") != stage.get("stage_id") or scope.get("stage_revision") != stage.get("revision"):
            problems.append({"code": "scope_mismatch", "message": "stage scope contradicts its object identity"})
        partitions = stage["partitions"]
        ids = [part.get("partition_id") for part in partitions]
        seats = [slot.get("slot_id") for part in partitions for slot in part["slots"]]
        if not partitions or any(type(value) is not str or not value for value in ids + seats) or len(ids) != len(set(ids)) or len(seats) != len(set(seats)) or any(not part["slots"] for part in partitions):
            problems.append({"code": "invalid_payload", "message": "stage requires unique nonempty partitions and seats"})
    return problems


def _validate_snapshot(snapshot: Mapping[str, Any]) -> list[str]:
    problems: list[str] = []
    characters = _mapping_list(snapshot.get("characters"))
    character_ids = [item.get("entity_id") for item in characters]
    if any(type(value) is not str or not value for value in character_ids) or len(character_ids) != len(set(character_ids)):
        problems.append("character entity identities are missing or duplicated")
    if any(item.get("ownership", "unknown") not in {"owned", "not_owned", "unknown"} for item in characters):
        problems.append("character ownership uses an unsupported state")
    equipment = _mapping_list(snapshot.get("equipment_instances"))
    equipment_ids = [item.get("local_instance_id") for item in equipment]
    if any(type(value) is not str or not value for value in equipment_ids) or len(equipment_ids) != len(set(equipment_ids)):
        problems.append("local equipment instance identities are missing or duplicated")
    allowed_identity = {"player_confirmed", "source_verified", "ambiguous", "unconfirmed", "unknown"}
    if any(item.get("identity_state", "unknown") not in allowed_identity for item in equipment):
        problems.append("equipment identity state is unsupported")
    materials = snapshot.get("materials", [])
    ids = [item.get("material_id") for item in materials]
    if any(type(value) is not str or not value for value in ids) or len(ids) != len(set(ids)):
        problems.append("material identities are missing or duplicated")
    for item in [*characters, *equipment, *snapshot.get("loadout_views", [])]:
        fields = item.get("fields", {})
        if not isinstance(fields, dict) or any(not isinstance(field, dict) for field in fields.values()):
            problems.append("snapshot fields must be materialized field objects")
    return problems


def _validate_variant(variant: Mapping[str, Any], stage: Mapping[str, Any], entities: Mapping[str, Mapping[str, Any]], evidence: Mapping[str, Mapping[str, Any]], definitions: Mapping[str, Any]) -> list[str]:
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
        for requirement in _mapping_list(slot.get("equipment_requirements")):
            type_ids = [requirement["public_type_id"]] if "public_type_id" in requirement else requirement.get("public_type_ids", [])
            for type_id in type_ids:
                if type_id not in entities or entities[type_id].get("entity_type") != requirement["kind"]:
                    problems.append(f"equipment requirement {slot_id}/{requirement['slot']} does not reference a same-kind public entity")
        for ref in _mapping_list(slot.get("evidence_refs")):
            if not _valid_ref(ref, evidence):
                problems.append(f"slot {slot_id} has an unresolved evidence reference")
    for source in [variant, *_mapping_list(variant.get("conditions"))]:
        for ref in _mapping_list(source.get("evidence_refs")):
            if not _valid_ref(ref, evidence):
                problems.append("variant or condition has an unresolved evidence reference")
    for condition in _mapping_list(variant.get("conditions")):
        subject = _mapping(condition.get("subject"))
        if subject.get("kind") in {"team_slot", "equipment_slot"} and str(subject.get("slot_id", "")) not in seen_global_slot_ids:
            problems.append(f"condition {condition.get('condition_id')} references a missing team slot")
        if subject.get("kind") == "character" and str(subject.get("character_id", "")) not in {str(s.get("character_id", "")) for s in slots}:
            problems.append(f"condition {condition.get('condition_id')} references a character outside this variant")
        if subject.get("kind") not in {"team_slot", "character", "equipment_slot"}:
            problems.append(f"public variant condition has unsupported subject {subject.get('kind')}")
        if condition.get("operator") not in _OPERATORS:
            problems.append(f"condition {condition.get('condition_id')} uses an unsupported operator")
        if not condition.get("unit") or not _mapping(condition.get("measurement_context")).get("phase"):
            problems.append(f"condition {condition.get('condition_id')} lacks unit or measurement context")
        if condition.get("requirement", "hard") not in {"hard", "soft"}:
            problems.append(f"condition {condition.get('condition_id')} has an unsupported requirement level")
        if condition.get("evidence_status", "unknown") not in {"confirmed", "suggested", "unknown"}:
            problems.append(f"condition {condition.get('condition_id')} has an unsupported evidence status")
        problems.extend(validate_condition(condition, definitions))
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
    scope["stage_id"] = stage.get("stage_id")
    scope["stage_revision"] = stage.get("revision")
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


def _equipment_options(slots: Sequence[Mapping[str, Any]], equipment: Sequence[Mapping[str, Any]], locked: set[str], stage: Mapping[str, Any], allow_rearrangement: bool) -> dict[str, Any]:
    requirements: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for slot in slots:
        for requirement in _mapping_list(slot.get("equipment_requirements")):
            requirements.append((slot, requirement))
    if not requirements:
        return {"current": {"assignments": [], "actions": []}, "rearranged": None, "rearrangement_candidates": [], "reasons": []}
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
        "rearrangement_candidates": rearranged or [],
        "search_limited": search_limited,
        "reasons": reasons,
    }


def _equipment_matches(item: Mapping[str, Any], requirement: Mapping[str, Any]) -> bool:
    if item.get("kind") != requirement["kind"]:
        return False
    if item.get("slot") != requirement["slot"]:
        return False
    if "public_type_id" in requirement:
        return item.get("public_type_id") == requirement["public_type_id"]
    if "public_type_ids" in requirement:
        return item.get("public_type_id") in requirement["public_type_ids"]
    return True


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
    for candidate in candidates:
        candidate["search_truncated"] = truncated
    return candidates


def _assignment_result(result: list[dict[str, Any]], requirements: Sequence[Any], equipment: Sequence[Any]) -> dict[str, Any]:
    return result[0]


def _troubleshooting(feedback: Any, bundle: Mapping[str, Any], variants: Sequence[Mapping[str, Any]], snapshot: Mapping[str, Any], task: Mapping[str, Any], task_scope: Mapping[str, Any], disabled: set[tuple[str, str, int]], definitions: Mapping[str, Any], evaluation_time: str | None, eligible_plans: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    if not isinstance(feedback, Mapping):
        return {"status": "not_requested", "suggestions": []}
    published = {str(v.get("id")): v for v in variants if _reviewed_and_published(v)}
    templates = _objects_by_id(bundle.get("templates"), "id")
    stages = _objects_by_id(bundle.get("stages"), "stage_id")
    selected_stage = stages.get(str(task_scope.get("stage_id", "")))
    matches: list[dict[str, Any]] = []
    unsupported: list[str] = []
    for rule in _mapping_list(bundle.get("troubleshooting")):
        if not _reviewed_and_published(rule) or _is_unavailable(rule, disabled, "troubleshooting") or not rule.get("evidence_refs"):
            continue
        rule_scope = _mapping(rule.get("scope"))
        required_scope = ("game_version", "environment", "mode_id", "cycle_id", "stage_id", "stage_revision")
        if not selected_stage or any(rule_scope.get(key) is None for key in required_scope):
            continue
        if _scope_mismatch(task_scope, rule_scope):
            continue
        if feedback.get("scope") is not None and feedback["scope"] != task_scope:
            continue
        if rule.get("applies_to_variant_ids"):
            source = next((variant for variant in variants if variant["id"] == feedback.get("variant_id") and variant["revision"] == feedback.get("variant_revision")), None)
            if not source or source["id"] not in rule["applies_to_variant_ids"]:
                continue
        if str(task_scope.get("stage_id")) not in _string_list(rule.get("stage_ids")):
            continue
        if not _mapping_list(rule.get("trigger_conditions")):
            unsupported.append(str(rule.get("id")))
            continue
        try:
            trigger = evaluate_conditions(rule.get("trigger_conditions", []), [], snapshot, task, definitions, feedback=feedback, evaluation_time=evaluation_time, troubleshooting=True)
        except UnsupportedSemantics:
            unsupported.append(str(rule.get("id")))
            continue
        if any(c["match_status"] == "unknown" for c in trigger):
            unsupported.append(str(rule.get("id")))
            continue
        if all(c["match_status"] == "satisfied" for c in trigger):
            target_id = rule.get("suggested_variant_id")
            suggestion: dict[str, Any] = {"rule_id": rule.get("id"), "rule_revision": rule.get("revision"), "evidence_refs": _mapping_list(rule.get("evidence_refs")), "trigger_results": trigger}
            target_variant = published.get(str(target_id)) if target_id else None
            target_template = templates.get(str(target_variant.get("template_id"))) if target_variant else None
            target_is_applicable = bool(target_template and _template_applies(target_template, selected_stage, task_scope))
            eligible_targets = [plan for plan in eligible_plans if plan["variant"]["id"] == target_id]
            if target_variant and target_is_applicable and eligible_targets and not _is_unavailable(target_variant, disabled, "variant"):
                suggestion["suggested_variant_id"] = str(target_id)
                suggestion["suggested_variant_revision"] = target_variant.get("revision")
                target_plan = next((plan for plan in eligible_targets if plan["plan_kind"] != "pending_confirmation"), eligible_targets[0])
                suggestion["eligibility"] = "confirmation_required" if target_plan["plan_kind"] == "pending_confirmation" else "available"
                suggestion["condition_results"] = target_plan["condition_results"]
                suggestion["pending_reasons"] = target_plan.get("pending_reasons", [])
            elif rule.get("action") == "recheck_conditions":
                suggestion["action"] = "recheck_conditions"
                suggestion["rechecked_variants"] = [{"variant": plan["variant"], "condition_results": plan["condition_results"]} for plan in eligible_plans]
            elif rule.get("action") == "review_cultivation_gaps":
                suggestion["action"] = "review_cultivation_gaps"
                suggestion["cultivation_gaps"] = [{"variant": plan["variant"], "cultivation": plan["cultivation"]} for plan in eligible_plans]
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
    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in {"evidence_refs", "citations"}:
                    refs.extend(dict(ref) for ref in child if _valid_ref(ref, evidence))
                else:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)
    walk([template, variant, *conditions])
    return _dedupe_refs(refs)


def _valid_ref(ref: Mapping[str, Any], index: Mapping[str, Mapping[str, Any]]) -> bool:
    item = index.get(str(ref.get("id", "")))
    return bool(item and item.get("revision") == ref.get("revision"))


def _is_unavailable(obj: Mapping[str, Any], disabled: set[tuple[str, str, int]], kind: str) -> bool:
    return (kind, obj.get("id"), obj.get("revision")) in disabled


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
    equipment = item.get("candidate_equipment")
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
        "cultivation_cost": item["cultivation_cost"],
        "evidence_refs": item["evidence_refs"],
        "ranking": {"known_condition_count": sum(c["match_status"] == "satisfied" for c in item["condition_results"]), "unknown_condition_count": sum(c["match_status"] == "unknown" for c in item["condition_results"]), "equipment_changes": len(equipment["actions"]) if equipment else 0, "allocation_search_truncated": allocation_truncated, "meaning": "仅用于适配顺序，不是通关概率"},
        "warnings": [c["condition_id"] for c in item["condition_results"] if c["match_status"] != "satisfied"] + (["equipment_allocation_search_truncated"] if allocation_truncated else []),
    }
    if plan_kind == "pending_confirmation":
        result["candidate_plan_kind"] = item["candidate_plan_kind"]
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
    mapping = request if type(request) is dict else {}
    return {
        "contract_version": _CONTRACT,
        "schema_id": "AnalysisResult",
        "schema_version": _CONTRACT,
        "planner_version": PLANNER_VERSION,
        "adapter_profile": ADAPTER_PROFILE,
        "request_id": mapping.get("request_id") if type(mapping.get("request_id")) is str else None,
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
