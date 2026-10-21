"""Versioned A-to-B distribution and A-to-C planner projection profiles.

These adapters keep the A release, B envelope and C member digest algorithms
separate. A projected planner view is emitted only when every required public
meaning is explicit in the approved A release.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import math
from typing import Any

from starhelp_knowledge.bundle import RECORD_COLLECTIONS, verify_public_bundle
from starhelp_knowledge.errors import IntegrityFailure, InvalidPayload, InvalidTransition, MissingDependency, UnsupportedCapability
from starhelp_knowledge.records import canonical_json

NATIVE_PROFILE = "starhelp.knowledge.native.v0.1-draft"
DISTRIBUTION_PROFILE = "starhelp.b-publicbundle-envelope.v1"
PLANNER_PROFILE = "starhelp.local.v0.2"
PLANNER_CAPABILITY = "starhelp.local-profile.v0.2"
DISTRIBUTION_CAPABILITY = "starhelp.knowledge-distribution.v1"
PLANNER_COLLECTIONS = {
    "entity": ("entities", "id"),
    "stage": ("stages", "stage_id"),
    "template": ("templates", "id"),
    "variant": ("variants", "id"),
    "evidence": ("evidence", "id"),
    "troubleshooting": ("troubleshooting", "id"),
}
_PLANNER_OPERATORS = {"eq", "ne", "gt", "gte", "lt", "lte", "in"}
_PLANNER_SCOPE_FIELDS = {
    "game_version", "environment", "mode_id", "cycle_id", "stage_id", "stage_revision",
}
_EQUIPMENT_KINDS = {"light_cone", "relic"}
_EQUIPMENT_REQUIREMENT_FIELDS = {
    "kind", "slot", "public_type_id", "public_type_ids", "evidence_refs",
}


def canonical_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError):
        raise InvalidPayload("distribution contains a non-JSON value") from None


def planner_member_hash(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def _identity(kind: str, item: dict[str, Any]) -> tuple[str, str, int]:
    return kind, item["id"] if kind != "stage" else item["stage_id"], item["revision"]


def _unique(items: list[Any], key: str, *, context: str) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for item in items:
        if not isinstance(item, dict) or not isinstance(item.get(key), str) or not item[key]:
            raise UnsupportedCapability(f"planner profile requires explicit {context} identities")
        if item[key] in result:
            raise InvalidPayload(f"planner profile has duplicate {context} identity")
        result[item[key]] = item
    return result


def _scope(scope: Any, *, stage_revision: int | None = None) -> dict[str, Any]:
    if not isinstance(scope, dict):
        raise UnsupportedCapability("planner profile requires an explicit public scope")
    if scope.get("target_kind") is not None:
        raise UnsupportedCapability("planner profile does not map target_kind")
    keys = ("game_version", "environment", "mode_id", "cycle_id", "stage_id")
    if any(not isinstance(scope.get(key), str) or not scope[key] for key in keys):
        raise UnsupportedCapability("planner profile requires game, environment, mode, cycle and stage scope")
    if type(stage_revision) is not int or stage_revision < 1:
        raise UnsupportedCapability("planner profile requires a stage revision")
    result = {**{key: scope[key] for key in keys}, "stage_revision": stage_revision}
    _validate_planner_scope(result, expected_stage_revision=stage_revision)
    return result


def _validate_planner_scope(scope: Any, *, expected_stage_revision: int | None = None) -> dict[str, Any]:
    if not isinstance(scope, dict) or set(scope) != _PLANNER_SCOPE_FIELDS:
        raise UnsupportedCapability("planner scope must contain exactly the six declared fields")
    string_fields = _PLANNER_SCOPE_FIELDS - {"stage_revision"}
    if any(type(scope.get(key)) is not str or not scope[key] for key in string_fields):
        raise UnsupportedCapability("planner scope identifiers must be non-empty strings")
    revision = scope.get("stage_revision")
    if type(revision) is not int or revision < 1:
        raise UnsupportedCapability("planner stage_revision must be a positive integer")
    if expected_stage_revision is not None and revision != expected_stage_revision:
        raise UnsupportedCapability("planner scope stage_revision does not match its stage")
    return scope


def _validate_equipment_requirements(
    value: Any,
    *,
    entities_by_id: dict[str, dict[str, Any]],
    evidence_by_id: dict[str, dict[str, Any]],
    declared_dependencies: set[tuple[str, str, int]] | None = None,
    expected_scope: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        raise UnsupportedCapability("equipment_requirements must be an explicit array")
    result: list[dict[str, Any]] = []
    seen_pairs: set[tuple[str, str]] = set()
    for requirement in value:
        if not isinstance(requirement, dict) or set(requirement) - _EQUIPMENT_REQUIREMENT_FIELDS:
            raise UnsupportedCapability("equipment requirement contains an unsupported matching field")
        if not {"kind", "slot"}.issubset(requirement):
            raise UnsupportedCapability("equipment requirement needs explicit kind and slot")
        kind, slot = requirement["kind"], requirement["slot"]
        if type(kind) is not str or kind not in _EQUIPMENT_KINDS or type(slot) is not str or not slot:
            raise UnsupportedCapability("equipment requirement kind or slot is unsupported")
        pair = (kind, slot)
        if pair in seen_pairs:
            raise InvalidPayload("equipment requirement repeats a kind and slot pair")
        seen_pairs.add(pair)

        has_single = "public_type_id" in requirement
        has_many = "public_type_ids" in requirement
        if has_single and has_many:
            raise InvalidPayload("equipment type restrictions are mutually exclusive")
        if has_single:
            identifiers = [requirement["public_type_id"]]
            if type(identifiers[0]) is not str or not identifiers[0]:
                raise InvalidPayload("public_type_id must be a non-empty string")
        elif has_many:
            raw_identifiers = requirement["public_type_ids"]
            if (
                not isinstance(raw_identifiers, list)
                or not raw_identifiers
                or any(type(identifier) is not str or not identifier for identifier in raw_identifiers)
                or len(raw_identifiers) != len(set(raw_identifiers))
            ):
                raise InvalidPayload("public_type_ids must be a non-empty list of unique IDs")
            identifiers = list(raw_identifiers)
        else:
            identifiers = []

        for identifier in identifiers:
            entity = entities_by_id.get(identifier)
            if entity is None:
                raise MissingDependency("equipment public type is outside the exact release")
            entity_type = entity.get("payload", {}).get("entity_type") if isinstance(entity.get("payload"), dict) else entity.get("entity_type")
            if entity_type != kind:
                raise UnsupportedCapability("equipment public type entity_type does not match requirement kind")
            revision = entity.get("revision")
            if declared_dependencies is not None and ("entity", identifier, revision) not in declared_dependencies:
                raise MissingDependency("equipment public type must be an explicit same-release dependency")
            if expected_scope is not None:
                try:
                    entity_scope = _scope(entity.get("scope"), stage_revision=expected_scope["stage_revision"])
                except (KeyError, TypeError):
                    raise UnsupportedCapability("equipment public type needs the exact planner scope") from None
                if entity_scope != expected_scope:
                    raise UnsupportedCapability("equipment public type scope does not match its variant")

        if "evidence_refs" in requirement:
            refs = requirement["evidence_refs"]
            if not isinstance(refs, list):
                raise InvalidPayload("equipment evidence_refs must be an array of revision references")
            seen_refs: set[tuple[str, int]] = set()
            for ref in refs:
                if not isinstance(ref, dict) or set(ref) != {"id", "revision"}:
                    raise InvalidPayload("equipment evidence_refs must contain only id and revision")
                evidence_id, revision = ref["id"], ref["revision"]
                if type(evidence_id) is not str or not evidence_id or type(revision) is not int or revision < 1:
                    raise InvalidPayload("equipment evidence reference is malformed")
                evidence = evidence_by_id.get(evidence_id)
                evidence_revision = evidence.get("revision", 1) if evidence else None
                if evidence is None or revision != evidence_revision:
                    raise MissingDependency("equipment evidence reference is outside the exact release")
                identity = (evidence_id, revision)
                if identity in seen_refs:
                    raise InvalidPayload("equipment evidence_refs contains a duplicate reference")
                seen_refs.add(identity)
        result.append(dict(requirement))
    return result


def _map_condition(
    condition: Any,
    entity_by_id: dict[str, dict[str, Any]],
    *,
    roster_entity_ids: set[str],
    roster_slot_ids: set[str],
) -> dict[str, Any]:
    if not isinstance(condition, dict):
        raise UnsupportedCapability("planner profile requires object conditions")
    operator = condition.get("operator")
    if not isinstance(operator, str) or operator not in _PLANNER_OPERATORS:
        raise UnsupportedCapability(f"planner profile does not support A condition operator {operator!r}")
    subject = condition.get("subject")
    if not isinstance(subject, dict):
        raise UnsupportedCapability("planner profile requires an explicit condition subject")
    if subject.get("kind") == "team_slot":
        slot_id = subject.get("slot_id")
        if not isinstance(slot_id, str) or slot_id not in roster_slot_ids:
            raise UnsupportedCapability("condition team slot is not present in its variant roster")
        mapped_subject = {"kind": "team_slot", "slot_id": slot_id}
    elif subject.get("kind") == "entity":
        entity_id = subject.get("entity_id")
        entity = entity_by_id.get(entity_id) if isinstance(entity_id, str) else None
        if (
            not entity
            or entity["payload"].get("entity_type") != "character"
            or entity_id not in roster_entity_ids
        ):
            raise UnsupportedCapability("A entity condition does not target a character in its variant roster")
        mapped_subject = {"kind": "character", "character_id": entity_id}
    else:
        raise UnsupportedCapability("planner profile does not map this condition subject")
    result = dict(condition)
    result["subject"] = mapped_subject
    result["operator"] = "neq" if operator == "ne" else operator
    return result


def _validate_attribute_definitions(manifest: dict[str, Any], conditions: list[dict[str, Any]]) -> dict[str, Any]:
    definitions = manifest.get("attribute_definitions")
    if not isinstance(definitions, dict):
        raise UnsupportedCapability("planner profile requires a release attribute registry")
    for condition in conditions:
        attribute = condition.get("attribute")
        definition = definitions.get(attribute) if isinstance(attribute, str) else None
        if not isinstance(definition, dict):
            raise UnsupportedCapability("condition uses an unregistered attribute")
        value_type = definition.get("value_type")
        if (
            not isinstance(value_type, str)
            or value_type not in {"number", "integer", "string", "boolean", "array"}
            or not isinstance(definition.get("unit"), str)
            or not definition["unit"]
            or not isinstance(definition.get("phases"), list)
            or not definition["phases"]
            or any(not isinstance(phase, str) for phase in definition["phases"])
            or not isinstance(definition.get("loadout_dependent"), bool)
        ):
            raise UnsupportedCapability("attribute registry lacks C type, unit, phase or loadout semantics")
        if condition.get("unit") != definition["unit"]:
            raise UnsupportedCapability("condition unit does not match the explicit attribute registry")
        context = condition.get("measurement_context")
        phase = context.get("phase") if isinstance(context, dict) else None
        if phase not in definition["phases"]:
            raise UnsupportedCapability("condition phase is not registered for its attribute")
        if not isinstance(context.get("assumptions"), list) or any(
            not isinstance(assumption, str) for assumption in context["assumptions"]
        ):
            raise UnsupportedCapability("condition assumptions do not match C measurement semantics")
        operator = condition.get("operator")
        value = condition.get("value")
        value_type = definition["value_type"]
        if operator in {"gt", "gte", "lt", "lte"} and value_type not in {"number", "integer"}:
            raise UnsupportedCapability("ordered conditions require a numeric registered attribute")
        if operator == "in":
            valid_value = isinstance(value, list) and all(
                _matches_attribute_type(item, value_type) for item in value
            )
        else:
            valid_value = _matches_attribute_type(value, value_type)
        if not valid_value:
            raise UnsupportedCapability("condition value does not match its registered attribute type")
    return definitions


def _matches_attribute_type(value: Any, value_type: str) -> bool:
    if value_type == "boolean":
        return type(value) is bool
    if value_type == "integer":
        return type(value) is int
    if value_type == "number":
        return type(value) is int or type(value) is float and math.isfinite(value)
    if value_type == "string":
        return isinstance(value, str)
    if value_type == "array":
        return isinstance(value, list)
    return False


def project_planner_view(
    native_bundle: dict[str, Any],
    *,
    producer_version: str,
    producer_commit: str,
    publication_state: str,
    publication_audit: dict[str, Any],
    approved_members: list[dict[str, Any]],
) -> dict[str, Any]:
    """Build a C 0.2 view from an integrity-checked, published A release."""
    native_digest = verify_public_bundle(native_bundle)
    manifest = native_bundle["manifest"]
    release_id = manifest.get("index_release_id")
    native_capabilities = manifest.get("required_capabilities", [])
    if not isinstance(native_capabilities, list) or native_capabilities:
        raise UnsupportedCapability("A release has capabilities with no explicit C 0.2 mapping")
    if publication_state not in {"active", "superseded"}:
        raise InvalidTransition("only a published release can produce a planner view")
    source_members = manifest.get("members")
    if not isinstance(source_members, list) or not source_members:
        raise IntegrityFailure()
    approved_by_identity: dict[tuple[str, str, int], dict[str, Any]] = {}
    for item in approved_members:
        if not isinstance(item, dict) or item.get("decision") != "approved":
            raise IntegrityFailure("every exported record needs an explicit approved review")
        identity = (item.get("kind"), item.get("id"), item.get("revision"))
        if identity in approved_by_identity or item.get("content_hash") is None:
            raise IntegrityFailure()
        approved_by_identity[identity] = item
    if set(approved_by_identity) != {
        (item.get("kind"), item.get("id"), item.get("revision")) for item in source_members
    }:
        raise IntegrityFailure("review proof does not cover the exact release member set")
    if any(approved_by_identity[(item["kind"], item["id"], item["revision"])]["content_hash"] != item["content_hash"] for item in source_members):
        raise IntegrityFailure("review hash differs from the published source member")

    source_records = native_bundle["records"]
    entities_by_id = _unique(source_records["entity"], "id", context="entity")
    stages_by_id = _unique(source_records["stage"], "id", context="stage")
    templates_by_id = _unique(source_records["template"], "id", context="template")
    variants_by_id = _unique(source_records["variant"], "id", context="variant")
    evidence_by_id = _unique(native_bundle["evidence"], "id", context="evidence")
    templates_for_variant: dict[str, list[tuple[str, str]]] = {}
    for template_id, template in templates_by_id.items():
        payload = template["payload"]
        if "public_goals" not in payload or not isinstance(payload["public_goals"], list) or not payload["public_goals"]:
            raise UnsupportedCapability("template lacks explicitly authored public_goals")
        if "alternate_variant_ids" not in payload or not isinstance(payload["alternate_variant_ids"], list):
            raise UnsupportedCapability("template lacks explicit alternate_variant_ids")
        variants = {payload.get("primary_variant_id"): "main"}
        variants.update({variant_id: "complete_alternate" for variant_id in payload["alternate_variant_ids"]})
        for variant_id in variants:
            if not isinstance(variant_id, str) or variant_id not in variants_by_id:
                raise MissingDependency("template references a variant outside this release")
            templates_for_variant.setdefault(variant_id, []).append((template_id, variants[variant_id]))

    conditions: list[dict[str, Any]] = []
    conditions_by_variant: dict[str, list[dict[str, Any]]] = {}
    for variant in source_records["variant"]:
        raw_conditions = variant["payload"].get("conditions")
        if not isinstance(raw_conditions, list):
            raise UnsupportedCapability("variant lacks an explicit conditions array")
        conditions_by_variant[variant["id"]] = raw_conditions
        conditions.extend(raw_conditions)
    definitions = _validate_attribute_definitions(manifest, conditions)

    planner_entities: list[dict[str, Any]] = []
    for source in source_records["entity"]:
        payload = source["payload"]
        entity_type, name = payload.get("entity_type"), payload.get("canonical_name")
        if not isinstance(entity_type, str) or not isinstance(name, str) or not name:
            raise UnsupportedCapability("planner entity needs explicit entity_type and canonical_name")
        planner_entities.append({
            "id": source["id"], "revision": source["revision"], "entity_type": entity_type,
            "name": name, "scope": source["scope"], "evidence_refs": source["evidence_refs"],
        })

    planner_stages: list[dict[str, Any]] = []
    stage_seats: dict[str, set[tuple[str, str]]] = {}
    for source in source_records["stage"]:
        payload = source["payload"]
        partitions = payload.get("partitions")
        reuse = payload.get("resource_reuse")
        if not isinstance(partitions, list) or not partitions or not isinstance(reuse, dict) or not reuse:
            raise UnsupportedCapability("stage lacks explicit partition seats or resource_reuse semantics")
        if any(value != "exclusive" for value in reuse.values()):
            raise UnsupportedCapability("C 0.2 only supports explicit exclusive resource reuse")
        seen_partitions: set[str] = set()
        seats: set[tuple[str, str]] = set()
        slot_ids: set[str] = set()
        mapped_partitions: list[dict[str, Any]] = []
        for partition in partitions:
            if not isinstance(partition, dict) or not isinstance(partition.get("partition_id"), str) or not isinstance(partition.get("slots"), list):
                raise UnsupportedCapability("stage partition needs a named partition and explicit slots")
            partition_id = partition["partition_id"]
            if partition_id in seen_partitions:
                raise InvalidPayload("duplicate stage partition")
            seen_partitions.add(partition_id)
            mapped_slots: list[dict[str, Any]] = []
            for slot in partition["slots"]:
                if not isinstance(slot, dict) or not isinstance(slot.get("slot_id"), str) or not slot["slot_id"]:
                    raise UnsupportedCapability("stage seat needs an explicit slot_id")
                seat = (partition_id, slot["slot_id"])
                if seat in seats or slot["slot_id"] in slot_ids:
                    raise InvalidPayload("duplicate stage seat")
                seats.add(seat)
                slot_ids.add(slot["slot_id"])
                mapped_slots.append({"slot_id": slot["slot_id"]})
            if not mapped_slots:
                raise UnsupportedCapability("each stage partition needs at least one explicit seat")
            mapped_partitions.append({"partition_id": partition_id, "slots": mapped_slots})
        stage_scope = _scope(source["scope"], stage_revision=source["revision"])
        mapped = {
            "stage_id": source["id"], "revision": source["revision"], "index_release_id": release_id,
            "scope": stage_scope, "partitions": mapped_partitions, "resource_reuse": dict(reuse),
            "evidence_refs": source["evidence_refs"],
        }
        for field in ("title", "enemy_refs", "mechanics", "objectives", "coverage_gaps"):
            if field in payload:
                mapped[field] = payload[field]
        stage_seats[source["id"]] = seats
        planner_stages.append(mapped)

    planner_templates: list[dict[str, Any]] = []
    template_context: dict[str, tuple[str, int, set[str]]] = {}
    for source in source_records["template"]:
        payload = source["payload"]
        stage_refs = [ref for ref in source["dependency_refs"] if ref["kind"] == "stage"]
        variant_refs = [ref for ref in source["dependency_refs"] if ref["kind"] == "variant"]
        if len(stage_refs) != 1 or not variant_refs:
            raise MissingDependency("planner template needs one stage and complete variants")
        stage_ref = stage_refs[0]
        stage = stages_by_id.get(stage_ref["id"])
        if stage is None or stage["revision"] != stage_ref["revision"] or source["scope"].get("stage_id") != stage_ref["id"]:
            raise MissingDependency("template stage must resolve in the exact release")
        variant_ids = [ref["id"] for ref in variant_refs]
        if set(variant_ids) != {payload.get("primary_variant_id"), *payload["alternate_variant_ids"]}:
            raise IntegrityFailure("template variant roles do not match its exact dependency set")
        mapped = {
            "id": source["id"], "revision": source["revision"], "index_release_id": release_id,
            "title": payload.get("title"), "approval_status": "approved", "publication_status": "published",
            "stage_ids": [stage_ref["id"]], "scope": _scope(source["scope"], stage_revision=stage["revision"]),
            "public_goals": payload["public_goals"], "variant_ids": variant_ids,
            "evidence_refs": source["evidence_refs"],
        }
        if not isinstance(mapped["title"], str) or not mapped["title"]:
            raise UnsupportedCapability("planner template needs an explicit title")
        template_context[source["id"]] = (stage_ref["id"], stage["revision"], set(variant_ids))
        planner_templates.append(mapped)

    planner_variants: list[dict[str, Any]] = []
    for source in source_records["variant"]:
        payload = source["payload"]
        owner = templates_for_variant.get(source["id"], [])
        if len(owner) != 1:
            raise UnsupportedCapability("each planner variant must belong to exactly one declared template")
        template_id, variant_kind = owner[0]
        template = templates_by_id[template_id]
        stage_ref = next(ref for ref in template["dependency_refs"] if ref["kind"] == "stage")
        stage_id = stage_ref["id"]
        raw_team = payload.get("team")
        if not isinstance(raw_team, list) or not raw_team:
            raise UnsupportedCapability("planner variant requires a complete team roster")
        teams: dict[str, list[dict[str, Any]]] = {}
        mapped_seats: set[tuple[str, str]] = set()
        roster_entity_ids: set[str] = set()
        roster_slot_ids: set[str] = set()
        stage = stages_by_id[stage_id]
        stage_scope = _scope(source["scope"], stage_revision=stage["revision"])
        declared_dependencies = {
            (ref["kind"], ref["id"], ref["revision"])
            for ref in source["dependency_refs"]
        }
        for slot in raw_team:
            if not isinstance(slot, dict):
                raise UnsupportedCapability("planner team slots must be explicit objects")
            partition, slot_id, entity_id = slot.get("partition"), slot.get("slot_id"), slot.get("entity_id")
            entity = entities_by_id.get(entity_id) if isinstance(entity_id, str) else None
            if not isinstance(partition, str) or not isinstance(slot_id, str) or not entity or entity["payload"].get("entity_type") != "character":
                raise UnsupportedCapability("planner team slot lacks an explicit partition, seat or character entity")
            seat = (partition, slot_id)
            if seat in mapped_seats or seat not in stage_seats[stage_id]:
                raise UnsupportedCapability("variant seat assignment is duplicate or outside the exact stage")
            mapped_seats.add(seat)
            roster_entity_ids.add(entity_id)
            roster_slot_ids.add(slot_id)
            if "equipment_requirements" not in slot or not isinstance(slot["equipment_requirements"], list):
                raise UnsupportedCapability("planner slot requires an explicit equipment_requirements list (empty means none)")
            team_slot = {
                "slot_id": slot_id, "character_id": entity_id,
                "equipment_requirements": _validate_equipment_requirements(
                    slot["equipment_requirements"],
                    entities_by_id=entities_by_id,
                    evidence_by_id=evidence_by_id,
                    declared_dependencies=declared_dependencies,
                    expected_scope=stage_scope,
                ),
            }
            if "evidence_refs" in slot:
                team_slot["evidence_refs"] = slot["evidence_refs"]
            teams.setdefault(partition, []).append(team_slot)
        if mapped_seats != stage_seats[stage_id]:
            raise UnsupportedCapability("variant does not fill every exact stage seat")
        mapped_conditions = [
            _map_condition(
                condition,
                entities_by_id,
                roster_entity_ids=roster_entity_ids,
                roster_slot_ids=roster_slot_ids,
            )
            for condition in conditions_by_variant[source["id"]]
        ]
        mapped = {
            "id": source["id"], "revision": source["revision"], "index_release_id": release_id,
            "template_id": template_id, "title": payload.get("title"), "variant_kind": variant_kind,
            "approval_status": "approved", "publication_status": "published",
            "evidence_refs": source["evidence_refs"], "teams": teams,
            "conditions": mapped_conditions,
        }
        if not isinstance(mapped["title"], str) or not mapped["title"]:
            raise UnsupportedCapability("planner variant needs an explicit title")
        mapped["conditions"] = [
            {**condition, "required_capabilities": [PLANNER_CAPABILITY], "schema_version": "0.1-draft", "index_release_id": release_id}
            for condition in mapped["conditions"]
        ]
        for field in ("steps", "mechanics", "failure_conditions", "risks", "cultivation_requirements"):
            if field in payload:
                mapped[field] = payload[field]
        if stage_scope != _scope(template["scope"], stage_revision=stage["revision"]):
            raise UnsupportedCapability("variant and template scopes do not match their stage")
        mapped["scope"] = stage_scope
        planner_variants.append(mapped)

    planner_evidence: list[dict[str, Any]] = []
    for source in native_bundle["evidence"]:
        mapped = {
            "id": source["id"], "revision": 1, "index_release_id": release_id,
            "title": source["title"], "source_url": source["url"], "locator": source["locator"],
            "excerpt": source["excerpt"], "status": source["evidence_status"], "scope": source["scope"],
            "source_content_hash": source["content_hash"],
        }
        planner_evidence.append(mapped)

    planner_troubleshooting: list[dict[str, Any]] = []
    for source in source_records["troubleshooting"]:
        payload = source["payload"]
        required = {"trigger_conditions", "stage_ids", "suggested_variant_id"}
        if not required.issubset(payload):
            raise UnsupportedCapability("troubleshooting record lacks explicit C trigger, stage or variant fields")
        mapped = {
            **payload, "id": source["id"], "revision": source["revision"],
            "index_release_id": release_id, "approval_status": "approved", "publication_status": "published",
            "scope": _scope(source["scope"], stage_revision=stages_by_id[payload["stage_ids"][0]]["revision"]),
            "evidence_refs": source["evidence_refs"],
        }
        planner_troubleshooting.append(mapped)

    collections = {
        "entities": planner_entities, "stages": planner_stages, "templates": planner_templates,
        "variants": planner_variants, "evidence": planner_evidence,
        "troubleshooting": planner_troubleshooting,
    }
    index: dict[tuple[str, str, int], dict[str, Any]] = {}
    for kind, (plural, id_key) in PLANNER_COLLECTIONS.items():
        for obj in collections[plural]:
            identity = (kind, obj[id_key], obj["revision"])
            if identity in index:
                raise IntegrityFailure("planner projection has duplicate member identity")
            index[identity] = obj
    member_manifest: list[dict[str, Any]] = []
    for identity, obj in index.items():
        dependencies = _declared_planner_dependencies(obj, index)
        member_manifest.append({
            "kind": identity[0], "id": identity[1], "revision": identity[2],
            "content_hash": planner_member_hash(obj),
            "dependencies": [
                {"kind": dep[0], "id": dep[1], "revision": dep[2]}
                for dep in sorted(dependencies)
            ],
        })
    member_manifest.sort(key=lambda item: (item["kind"], item["id"], item["revision"]))
    source_member_proof = [
        {key: item[key] for key in ("kind", "id", "revision", "content_hash")}
        for item in source_members
    ]
    ignored = sorted(set(source_records) - {"entity", "stage", "template", "variant", "troubleshooting"})
    review_ledger = [
        {
            "kind": key[0], "id": key[1], "revision": key[2],
            "decision": value["decision"], "reviewed_content_hash": value["content_hash"],
            "review_revision": value["review_revision"], "reviewed_at": value["reviewed_at"],
        }
        for key, value in sorted(approved_by_identity.items())
    ]
    return {
        "adapter_profile": PLANNER_PROFILE,
        "contract_version": "0.1-draft",
        "schema_id": "PublicBundle",
        "schema_version": "0.1-draft",
        "manifest": {
            "index_release_id": release_id,
            "required_capabilities": [PLANNER_CAPABILITY],
            "object_schemas": {kind: "0.1-draft" for kind in PLANNER_COLLECTIONS},
            "coverage": manifest.get("coverage", {}),
            "attribute_definitions": definitions,
            "integrity_algorithm": "sha256-json-v1",
            "members": member_manifest,
            "source_proof": {
                "source_profile": NATIVE_PROFILE,
                "source_schema_version": native_bundle["schema_version"],
                "source_release_id": release_id,
                "source_release_content_hash": native_digest,
                "source_hash_algorithm": manifest["hash_algorithm"],
                "source_members": source_member_proof,
                "source_evidence_ids": sorted(evidence_by_id),
                "producer_package_version": producer_version,
                "producer_commit": producer_commit,
                "publication_state": publication_state,
                "approved_reviews": review_ledger,
                "publication_audit": publication_audit,
                "unconsumed_record_kinds": ignored,
            },
        },
        **collections,
    }


def _resolve(kind: str, identifier: Any, index: dict[tuple[str, str, int], dict[str, Any]]) -> tuple[str, str, int]:
    if not isinstance(identifier, str):
        raise MissingDependency("planner reference has no stable identity")
    matches = [key for key in index if key[0] == kind and key[1] == identifier]
    if len(matches) != 1:
        raise MissingDependency("planner reference is missing or ambiguous")
    return matches[0]


def _declared_planner_dependencies(
    obj: dict[str, Any], index: dict[tuple[str, str, int], dict[str, Any]]
) -> set[tuple[str, str, int]]:
    reference_kinds = {
        "evidence_refs": "evidence", "citations": "evidence", "entity_refs": "entity",
        "enemy_refs": "entity", "character_refs": "entity", "stage_refs": "stage",
        "template_refs": "template", "variant_refs": "variant", "troubleshooting_refs": "troubleshooting",
    }
    result: set[tuple[str, str, int]] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            for key, child in value.items():
                if key in reference_kinds:
                    if not isinstance(child, list):
                        raise InvalidPayload("planner reference list is malformed")
                    for ref in child:
                        if not isinstance(ref, dict) or type(ref.get("revision")) is not int:
                            raise InvalidPayload("planner reference is malformed")
                        result.add((reference_kinds[key], ref.get("id"), ref["revision"]))
                elif key in {"character_id", "character_entity_id", "public_type_id", "material_id", "subject_entity_id"}:
                    result.add(_resolve("entity", child, index))
                elif key == "public_type_ids":
                    if not isinstance(child, list):
                        raise InvalidPayload("planner type reference list is malformed")
                    for identifier in child:
                        result.add(_resolve("entity", identifier, index))
                elif key == "template_id":
                    result.add(_resolve("template", child, index))
                elif key == "stage_ids":
                    if not isinstance(child, list):
                        raise InvalidPayload("planner stage reference list is malformed")
                    for identifier in child:
                        result.add(_resolve("stage", identifier, index))
                elif key in {"variant_ids", "applies_to_variant_ids"}:
                    if not isinstance(child, list):
                        raise InvalidPayload("planner variant reference list is malformed")
                    for identifier in child:
                        result.add(_resolve("variant", identifier, index))
                elif key == "suggested_variant_id":
                    result.add(_resolve("variant", child, index))
                else:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(obj)
    return result


def verify_planner_view(view: dict[str, Any], *, supported_capabilities: set[str]) -> str:
    if (
        not isinstance(view, dict)
        or view.get("adapter_profile") != PLANNER_PROFILE
        or view.get("contract_version") != "0.1-draft"
        or view.get("schema_id") != "PublicBundle"
        or view.get("schema_version") != "0.1-draft"
    ):
        raise UnsupportedCapability("planner consumer profile is not explicitly selected")
    manifest = view.get("manifest")
    if not isinstance(manifest, dict) or manifest.get("integrity_algorithm") != "sha256-json-v1":
        raise UnsupportedCapability("unsupported planner member integrity profile")
    expected_schemas = {kind: "0.1-draft" for kind in PLANNER_COLLECTIONS}
    if manifest.get("object_schemas") != expected_schemas:
        raise UnsupportedCapability("planner manifest does not declare the exact supported object schemas")
    required = manifest.get("required_capabilities")
    if (
        not isinstance(required, list)
        or any(not isinstance(capability, str) for capability in required)
        or len(required) != len(set(required))
        or PLANNER_CAPABILITY not in required
        or set(required) - supported_capabilities
    ):
        raise UnsupportedCapability("planner view requires an unsupported capability")
    release_id = manifest.get("index_release_id")
    if not isinstance(release_id, str) or not release_id:
        raise InvalidPayload("planner release identity is missing")

    def verify_nested_versions(value: Any) -> None:
        if isinstance(value, dict):
            if "index_release_id" in value and value["index_release_id"] != release_id:
                raise IntegrityFailure("planner view contains a cross-release object")
            if "schema_version" in value and value["schema_version"] != "0.1-draft":
                raise UnsupportedCapability("planner object schema is unsupported")
            nested_caps = value.get("required_capabilities")
            if nested_caps is not None and (
                not isinstance(nested_caps, list) or set(nested_caps) - supported_capabilities
            ):
                raise UnsupportedCapability("planner object requires an unsupported capability")
            for child in value.values():
                verify_nested_versions(child)
        elif isinstance(value, list):
            for child in value:
                verify_nested_versions(child)

    verify_nested_versions(view)
    index: dict[tuple[str, str, int], dict[str, Any]] = {}
    for kind, (plural, id_key) in PLANNER_COLLECTIONS.items():
        items = view.get(plural)
        if not isinstance(items, list):
            raise InvalidPayload("planner collection is missing")
        for item in items:
            if not isinstance(item, dict) or not isinstance(item.get(id_key), str) or type(item.get("revision")) is not int:
                raise InvalidPayload("planner member identity is malformed")
            identity = (kind, item[id_key], item["revision"])
            if identity in index:
                raise IntegrityFailure("planner projection has duplicate member identity")
            index[identity] = item
    entities_by_id = _unique(view.get("entities", []), "id", context="entity")
    evidence_by_id = _unique(view.get("evidence", []), "id", context="evidence")
    stages_by_id = _unique(view.get("stages", []), "stage_id", context="stage")
    templates_by_id = _unique(view.get("templates", []), "id", context="template")
    for stage in stages_by_id.values():
        scope = _validate_planner_scope(stage.get("scope"), expected_stage_revision=stage.get("revision"))
        if scope["stage_id"] != stage.get("stage_id"):
            raise IntegrityFailure("planner stage scope does not match its stage identity")
    for template in templates_by_id.values():
        scope = _validate_planner_scope(template.get("scope"))
        stage_ids = template.get("stage_ids")
        if not isinstance(stage_ids, list) or len(stage_ids) != 1 or stage_ids[0] not in stages_by_id:
            raise MissingDependency("planner template needs one exact stage")
        if scope != stages_by_id[stage_ids[0]]["scope"]:
            raise IntegrityFailure("planner template scope differs from its exact stage")
    for variant in view.get("variants", []):
        scope = _validate_planner_scope(variant.get("scope"))
        template = templates_by_id.get(variant.get("template_id"))
        if template is None:
            raise MissingDependency("planner variant template is outside the exact release")
        if scope != template["scope"]:
            raise IntegrityFailure("planner variant scope differs from its exact template")
        teams = variant.get("teams")
        if not isinstance(teams, dict):
            raise InvalidPayload("planner variant team mapping is malformed")
        for slots in teams.values():
            if not isinstance(slots, list):
                raise InvalidPayload("planner variant partition slots are malformed")
            for slot in slots:
                if not isinstance(slot, dict) or "equipment_requirements" not in slot:
                    raise UnsupportedCapability("planner slot needs an explicit equipment_requirements array")
                _validate_equipment_requirements(
                    slot["equipment_requirements"],
                    entities_by_id=entities_by_id,
                    evidence_by_id=evidence_by_id,
                    expected_scope=scope,
                )
    members = manifest.get("members")
    if not isinstance(members, list):
        raise InvalidPayload("planner manifest member list is missing")
    declared: dict[tuple[str, str, int], dict[str, Any]] = {}
    for member in members:
        if not isinstance(member, dict):
            raise InvalidPayload("planner manifest member is malformed")
        identity = (member.get("kind"), member.get("id"), member.get("revision"))
        obj = index.get(identity)
        if obj is None or identity in declared or member.get("content_hash") != planner_member_hash(obj):
            raise IntegrityFailure("planner member does not match its content hash")
        dependencies = member.get("dependencies")
        if not isinstance(dependencies, list):
            raise InvalidPayload("planner dependency list is malformed")
        expected = _declared_planner_dependencies(obj, index)
        actual = {(dep.get("kind"), dep.get("id"), dep.get("revision")) for dep in dependencies if isinstance(dep, dict)}
        if len(actual) != len(dependencies) or actual != expected or expected - set(index):
            raise MissingDependency("planner dependency closure is incomplete or inconsistent")
        declared[identity] = member
    if set(declared) != set(index):
        raise MissingDependency("planner manifest does not cover the exact object set")
    return hashlib.sha256(canonical_bytes(manifest)).hexdigest()


def build_distribution_envelope(
    native_bundle: dict[str, Any],
    planner_view: dict[str, Any],
    *,
    signing_private_key: Any,
    signing_key_id: str,
) -> dict[str, Any]:
    native_hash = verify_public_bundle(native_bundle)
    planner_hash = verify_planner_view(planner_view, supported_capabilities={PLANNER_CAPABILITY})
    if not isinstance(signing_key_id, str) or not signing_key_id or len(signing_key_id) > 160:
        raise InvalidPayload("invalid signing key ID")
    release_id = native_bundle["manifest"]["index_release_id"]
    native_object_id = f"native-release:{release_id}"
    planner_object_id = f"planner-view:{release_id}"
    objects = {
        native_object_id: {"kind": "starhelp_native_release", "refs": [], "bundle": native_bundle},
        planner_object_id: {"kind": "starhelp_planner_view", "refs": [native_object_id], "bundle": planner_view},
    }
    members = {object_id: hashlib.sha256(canonical_bytes(obj)).hexdigest() for object_id, obj in objects.items()}
    manifest = {
        "index_release_id": release_id,
        "required_capabilities": [DISTRIBUTION_CAPABILITY],
        "coverage": native_bundle["manifest"].get("coverage", {}),
        "signing_key_id": signing_key_id,
        "signature_algorithm": "ed25519",
        "distribution_profile": DISTRIBUTION_PROFILE,
        "native_profile": NATIVE_PROFILE,
        "planner_profile": PLANNER_PROFILE,
        "members": members,
        "source_release_content_hash": native_hash,
        "planner_manifest_hash": planner_hash,
    }
    signature = signing_private_key.sign(canonical_bytes(manifest)).hex()
    envelope = {
        "contract_version": "0.1-draft", "schema_id": "PublicBundle", "schema_version": "0.1-draft",
        "manifest": manifest, "signature": signature, "objects": objects,
    }
    verify_distribution_envelope(
        envelope,
        trusted_public_keys={signing_key_id: signing_private_key.public_key().public_bytes_raw()},
        trusted_key_id=signing_key_id,
        supported_distribution_capabilities={DISTRIBUTION_CAPABILITY},
        supported_planner_capabilities={PLANNER_CAPABILITY},
    )
    return envelope


def verify_distribution_envelope(
    envelope: dict[str, Any],
    *,
    trusted_public_keys: dict[str, bytes],
    trusted_key_id: str,
    supported_distribution_capabilities: set[str],
    supported_planner_capabilities: set[str],
) -> dict[str, Any]:
    """Verify the signed B envelope and both A-native and C-projection digests."""
    if not isinstance(envelope, dict) or envelope.get("schema_id") != "PublicBundle" or envelope.get("contract_version") != "0.1-draft" or envelope.get("schema_version") != "0.1-draft":
        raise UnsupportedCapability("unsupported B PublicBundle envelope version")
    manifest = envelope.get("manifest")
    if (
        not isinstance(manifest, dict)
        or manifest.get("distribution_profile") != DISTRIBUTION_PROFILE
        or manifest.get("native_profile") != NATIVE_PROFILE
        or manifest.get("planner_profile") != PLANNER_PROFILE
    ):
        raise UnsupportedCapability("unsupported B distribution profile")
    if manifest.get("signature_algorithm") != "ed25519" or manifest.get("signing_key_id") != trusted_key_id:
        raise IntegrityFailure("distribution signing identity does not match configured trust")
    required = manifest.get("required_capabilities")
    if (
        not isinstance(required, list)
        or any(not isinstance(capability, str) for capability in required)
        or len(required) != len(set(required))
        or DISTRIBUTION_CAPABILITY not in required
        or not set(required) <= supported_distribution_capabilities
    ):
        raise UnsupportedCapability("distribution requires an unsupported capability")
    objects = envelope.get("objects")
    members = manifest.get("members")
    if not isinstance(objects, dict) or not isinstance(members, dict) or not objects or set(objects) != set(members):
        raise MissingDependency("B member map does not equal the complete object set")
    release_id = manifest.get("index_release_id")
    if not isinstance(release_id, str) or not release_id:
        raise InvalidPayload("distribution release identity is missing")
    native_id, planner_id = f"native-release:{release_id}", f"planner-view:{release_id}"
    if set(objects) != {native_id, planner_id}:
        raise UnsupportedCapability("distribution contains objects outside the selected profile")
    for object_id, obj in objects.items():
        if (
            not isinstance(obj, dict)
            or set(obj) != {"kind", "refs", "bundle"}
            or not isinstance(obj.get("refs"), list)
            or any(not isinstance(ref, str) for ref in obj["refs"])
        ):
            raise InvalidPayload("B object references are malformed")
        if set(obj["refs"]) - set(objects):
            raise MissingDependency("B object dependency is missing")
        digest = hashlib.sha256(canonical_bytes(obj)).hexdigest()
        if not isinstance(members[object_id], str) or not hmac.compare_digest(digest, members[object_id]):
            raise IntegrityFailure("B object member hash mismatch")
    signature = envelope.get("signature")
    try:
        signature_bytes = bytes.fromhex(signature) if isinstance(signature, str) else b""
        public_bytes = trusted_public_keys.get(trusted_key_id)
        if public_bytes is None:
            raise ValueError
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        Ed25519PublicKey.from_public_bytes(public_bytes).verify(signature_bytes, canonical_bytes(manifest))
    except Exception:
        raise IntegrityFailure("distribution manifest signature verification failed") from None
    native_wrapper, planner_wrapper = objects.get(native_id), objects.get(planner_id)
    if (
        not isinstance(native_wrapper, dict)
        or native_wrapper.get("kind") != "starhelp_native_release"
        or native_wrapper.get("refs") != []
    ):
        raise MissingDependency("signed envelope lacks the A native release")
    if not isinstance(planner_wrapper, dict) or planner_wrapper.get("kind") != "starhelp_planner_view" or planner_wrapper.get("refs") != [native_id]:
        raise MissingDependency("signed envelope lacks the C planner view dependency")
    native_bundle = native_wrapper.get("bundle")
    planner_view = planner_wrapper.get("bundle")
    native_hash = verify_public_bundle(native_bundle)
    if native_hash != manifest.get("source_release_content_hash") or native_bundle["manifest"].get("index_release_id") != release_id:
        raise IntegrityFailure("embedded A release does not match the signed distribution")
    planner_hash = verify_planner_view(planner_view, supported_capabilities=supported_planner_capabilities)
    if planner_view["manifest"].get("index_release_id") != release_id or planner_hash != manifest.get("planner_manifest_hash"):
        raise IntegrityFailure("embedded planner view does not match its signed distribution")
    return {
        "distribution_profile": DISTRIBUTION_PROFILE,
        "planner_profile": PLANNER_PROFILE,
        "release_id": release_id,
        "signing_key_id": trusted_key_id,
        "signature_algorithm": "ed25519",
        "native_release_content_hash": native_hash,
        "planner_manifest_hash": planner_hash,
        "b_member_hashes": dict(members),
    }


def review_proof_for_release(service: Any, release_id: str) -> tuple[str, list[dict[str, Any]], dict[str, Any]]:
    """Read exact review/publication facts from A's own DB, omitting actor identities."""
    with service.database.reader() as db:
        release = db.execute("SELECT state FROM index_releases WHERE index_release_id=?", (release_id,)).fetchone()
        if release is None:
            raise MissingDependency("release does not exist")
        publication = db.execute(
            "SELECT event_id,operation_kind,expected_active_release_id,created_at FROM publication_events "
            "WHERE index_release_id=? AND operation_kind IN ('activate','rollback') ORDER BY created_at DESC LIMIT 1",
            (release_id,),
        ).fetchone()
        if publication is None:
            raise InvalidTransition("release lacks an explicit activation/rollback audit event")
        rows = db.execute(
            "SELECT pr.record_kind,pr.record_id,pr.revision,pr.content_hash,r.decision,r.content_hash AS review_hash,r.review_revision,r.created_at AS reviewed_at "
            "FROM release_members rm JOIN public_record_revisions pr "
            "ON pr.record_kind=rm.record_kind AND pr.record_id=rm.record_id AND pr.revision=rm.revision "
            "LEFT JOIN reviews r ON r.record_revision_id=pr.record_revision_id "
            "WHERE rm.index_release_id=? ORDER BY pr.record_kind,pr.record_id,r.review_revision",
            (release_id,),
        ).fetchall()
        approved: dict[tuple[str, str, int], dict[str, Any]] = {}
        for row in rows:
            identity = (row["record_kind"], row["record_id"], row["revision"])
            if row["decision"] == "approved" and row["review_hash"] == row["content_hash"]:
                approved[identity] = {
                    "kind": row["record_kind"], "id": row["record_id"], "revision": row["revision"],
                    "content_hash": row["content_hash"], "decision": "approved",
                    "review_revision": row["review_revision"], "reviewed_at": row["reviewed_at"],
                }
        if len(approved) != len({(row["record_kind"], row["record_id"], row["revision"]) for row in rows}):
            raise IntegrityFailure("release member lacks an exact approved review")
        publication_audit = {
            "event_id": publication["event_id"],
            "operation": publication["operation_kind"],
            "expected_previous_release_id": publication["expected_active_release_id"],
            "recorded_at": publication["created_at"],
        }
        return release["state"], list(approved.values()), publication_audit


def export_distribution_from_service(
    service: Any,
    release_id: str,
    *,
    producer_version: str,
    producer_commit: str,
    signing_private_key: Any,
    signing_key_id: str,
) -> dict[str, Any]:
    native_bundle = service.get_release_bundle(release_id)
    publication_state, approvals, publication_audit = review_proof_for_release(service, release_id)
    planner_view = project_planner_view(
        native_bundle,
        producer_version=producer_version,
        producer_commit=producer_commit,
        publication_state=publication_state,
        publication_audit=publication_audit,
        approved_members=approvals,
    )
    return build_distribution_envelope(
        native_bundle, planner_view, signing_private_key=signing_private_key, signing_key_id=signing_key_id
    )
