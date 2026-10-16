"""Check declared A-to-C field mappings without trusting approval flags alone."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..validation import canonical_hash, objects
from .common import digest, fail


def check_projection(native: dict[str, Any], view: dict[str, Any]) -> None:
    records = native["records"]
    mapping = {kind: {row["id"]: row for row in records[kind]} for kind in ("entity", "stage", "template", "variant", "troubleshooting")}
    public = {kind: {obj["stage_id"] if kind == "stage" else obj["id"]: obj for obj in view[plural]} for kind, plural in (("entity", "entities"), ("stage", "stages"), ("template", "templates"), ("variant", "variants"), ("troubleshooting", "troubleshooting"))}
    for kind in mapping:
        if set(mapping[kind]) != set(public[kind]):
            fail("projection_semantics_mismatch", "projected identities differ from the original member set")
        for identifier, row in mapping[kind].items():
            obj = public[kind][identifier]
            if obj["revision"] != row["revision"] or obj.get("evidence_refs") != row["evidence_refs"]:
                fail("projection_semantics_mismatch", "projection changed revision/evidence references")
            if kind in {"stage", "template", "variant", "troubleshooting"} and any(value is not None and obj.get("scope", {}).get(key) != value for key, value in row["scope"].items() if key in {"game_version", "environment", "mode_id", "cycle_id", "stage_id"}):
                fail("projection_semantics_mismatch", "projection changed original record applicability")
    for identifier, row in mapping["entity"].items():
        obj = public["entity"][identifier]
        if obj.get("entity_type") != row["payload"].get("entity_type") or obj.get("name") != row["payload"].get("canonical_name"):
            fail("projection_semantics_mismatch", "entity type/name mapping differs from the original")
        if "scope" in obj and obj["scope"] != row["scope"]:
            fail("projection_semantics_mismatch", "entity scope contradicts original applicability")
    for identifier, row in mapping["stage"].items():
        obj = public["stage"][identifier]
        if obj.get("partitions") != row["payload"].get("partitions") or obj.get("resource_reuse") != row["payload"].get("resource_reuse"):
            fail("projection_semantics_mismatch", "stage seats/resource semantics were changed or inferred")
        expected_scope = {key: row["scope"][key] for key in ("game_version", "environment", "mode_id", "cycle_id", "stage_id")}
        if obj.get("scope") != {**expected_scope, "stage_revision": row["revision"]}:
            fail("projection_semantics_mismatch", "stage scope/revision mapping differs")
    linked = {}
    for identifier, row in mapping["template"].items():
        obj, payload = public["template"][identifier], row["payload"]
        stage_refs = [ref for ref in row["dependency_refs"] if ref["kind"] == "stage"]
        expected_variants = [payload["primary_variant_id"], *payload["alternate_variant_ids"]]
        if len(stage_refs) != 1 or obj.get("stage_ids") != [stage_refs[0]["id"]] or obj.get("public_goals") != payload.get("public_goals") or set(obj.get("variant_ids", [])) != set(expected_variants):
            fail("projection_semantics_mismatch", "template goal/stage/complete-variant mapping differs")
        for index, variant_id in enumerate(expected_variants):
            if variant_id in linked:
                fail("unsupported_projection_semantics", "a complete variant linked to multiple templates is unsupported")
            linked[variant_id] = identifier, "main" if index == 0 else "complete_alternate"
    for identifier, row in mapping["variant"].items():
        obj, payload = public["variant"][identifier], row["payload"]
        if linked.get(identifier) != (obj.get("template_id"), obj.get("variant_kind")):
            fail("projection_semantics_mismatch", "complete main/alternate relationship differs")
        projected_slots = [slot for slots in obj["teams"].values() for slot in slots]
        if len(projected_slots) != len(payload["team"]):
            fail("projection_semantics_mismatch", "complete variant roster size changed")
        for slot in payload["team"]:
            candidates = [candidate for candidate in obj["teams"].get(slot["partition"], []) if candidate["slot_id"] == slot["slot_id"]]
            if len(candidates) != 1 or candidates[0].get("character_id") != slot["entity_id"] or "equipment_requirements" not in slot or candidates[0].get("equipment_requirements") != slot["equipment_requirements"]:
                fail("projection_semantics_mismatch", "partition/role/equipment semantics were changed or inferred")
        conditions = []
        for raw in payload["conditions"]:
            condition = deepcopy(raw)
            if raw["operator"] not in {"eq", "ne", "gt", "gte", "lt", "lte", "in"}:
                fail("unsupported_projection_semantics", "unsupported A predicate cannot be relabelled")
            condition["operator"] = "neq" if raw["operator"] == "ne" else raw["operator"]
            subject = raw["subject"]
            if subject["kind"] == "entity":
                if mapping["entity"].get(subject.get("entity_id"), {}).get("payload", {}).get("entity_type") != "character":
                    fail("unsupported_projection_semantics", "entity subject is not a declared character")
                condition["subject"] = {"kind": "character", "character_id": subject["entity_id"]}
            elif subject["kind"] != "team_slot":
                fail("unsupported_projection_semantics", "team-wide predicates have no finite supported mapping")
            conditions.append(condition)
        if obj.get("conditions") != conditions:
            fail("projection_semantics_mismatch", "condition value/unit/context/requirement mapping differs")
        for key in ("steps", "mechanics", "failure_conditions", "risks", "cultivation_requirements"):
            if obj.get(key, []) != payload.get(key, []):
                fail("projection_semantics_mismatch", "strategy/cultivation projection differs from the original")
    if view["manifest"].get("attribute_definitions") != native["manifest"].get("attribute_definitions"):
        fail("projection_semantics_mismatch", "attribute metadata was not supplied by the original producer")
    evidence = {item["id"]: item for item in native["evidence"]}
    if set(evidence) != {item["id"] for item in view["evidence"]}:
        fail("projection_semantics_mismatch", "evidence membership changed")
    for obj in view["evidence"]:
        original = evidence[obj["id"]]
        if obj["revision"] != 1 or any(obj.get(target) != original[source] for target, source in (("source_url", "url"), ("title", "title"), ("excerpt", "excerpt"), ("locator", "locator"), ("status", "evidence_status"), ("source_content_hash", "content_hash"))):
            fail("projection_semantics_mismatch", "evidence mapping differs from the original immutable identity")


def consumption_view(native: dict[str, Any], projected: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    """Retain explicit original scopes omitted by the producer's projected view.

    This happens only after original signature/hash/mapping verification. New
    digests describe this C-only consumption object, never an original signature.
    """
    view = deepcopy(projected)
    for plural, originals in (("entities", native["records"]["entity"]), ("evidence", native["evidence"])):
        scopes = {row["id"]: row["scope"] for row in originals}
        for obj in view[plural]:
            obj["scope"] = deepcopy(scopes[obj["id"]])
    index = objects(view)
    for member in view["manifest"]["members"]:
        key = member["kind"], member["id"], member["revision"]
        member["content_hash"] = canonical_hash(index[key])
    return view, {"profile": "starhelp.consumption.v0.1", "sha256": digest(view), "scope_mapping": "explicit original entity/evidence scopes retained", "purpose": "internal normalized consumption view; not a producer hash/signature"}
