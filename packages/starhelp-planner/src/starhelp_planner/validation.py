"""In-memory integrity and shape checks for the proposed local adapter profile."""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from typing import Any

COLLECTIONS = {"entity": ("entities", "id"), "stage": ("stages", "stage_id"), "template": ("templates", "id"), "variant": ("variants", "id"), "evidence": ("evidence", "id"), "troubleshooting": ("troubleshooting", "id")}
REFERENCE_KINDS = {"evidence_refs": "evidence", "citations": "evidence", "entity_refs": "entity", "enemy_refs": "entity", "character_refs": "entity", "stage_refs": "stage", "template_refs": "template", "variant_refs": "variant", "troubleshooting_refs": "troubleshooting"}
SCOPE_KEYS = ("game_version", "environment", "mode_id", "cycle_id", "stage_id", "stage_revision")
HASH_ALGORITHM = "sha256-json-v1"


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def validate_json_request(request: Any) -> None:
    remaining = 100_000
    active: set[int] = set()

    def walk(value: Any, depth: int) -> None:
        nonlocal remaining
        remaining -= 1
        if remaining < 0 or depth > 48:
            raise ValueError("payload exceeds supported size or depth")
        if value is None or type(value) in {str, bool, int}:
            return
        if type(value) is float:
            if not math.isfinite(value):
                raise ValueError("non-finite numeric value")
            return
        if type(value) not in {dict, list}:
            raise ValueError("only materialized JSON objects and arrays are supported")
        if id(value) in active:
            raise ValueError("cyclic input is unsupported")
        active.add(id(value))
        if isinstance(value, dict):
            if any(type(key) is not str for key in value):
                raise ValueError("JSON object keys must be strings")
            for child in value.values():
                walk(child, depth + 1)
        else:
            for child in value:
                walk(child, depth + 1)
        active.remove(id(value))

    walk(request, 0)
    if not isinstance(request, dict):
        raise ValueError("request must be an object")
    for key in ("public_bundle", "account_snapshot", "task"):
        if not isinstance(request.get(key), dict):
            raise ValueError(f"{key} must be an object")
    snapshot, task, bundle = request["account_snapshot"], request["task"], request["public_bundle"]
    for name, value in (("request_id", request.get("request_id")), ("profile_id", snapshot.get("profile_id")), ("snapshot_id", snapshot.get("snapshot_id"))):
        if type(value) is not str or not value:
            raise ValueError(f"{name} must be a nonempty string")
    for owner in (task, request.get("feedback")):
        if owner is not None and (not isinstance(owner, dict) or not isinstance(owner.get("fields", {}), dict) or any(not isinstance(field, dict) for field in owner.get("fields", {}).values())):
            raise ValueError("task/feedback fields must be materialized field objects")
    for key in ("characters", "equipment_instances"):
        object_array(snapshot.get(key), f"snapshot.{key}")
    for key in ("materials", "loadout_views"):
        if key in snapshot:
            object_array(snapshot[key], f"snapshot.{key}")
    for key in ("fixed_character_ids", "excluded_character_ids", "locked_local_instance_ids"):
        value = task.get(key, [])
        if not isinstance(value, list) or any(type(item) is not str or not item for item in value) or len(value) != len(set(value)):
            raise ValueError(f"task.{key} must be a unique array of IDs")
    for value in (request.get("authorization_generation"), snapshot.get("authorization_generation"), snapshot.get("snapshot_revision")):
        if type(value) is not int or value < 1:
            raise ValueError("snapshot revision and authorization generations must be positive integers")
    for plural, _ in COLLECTIONS.values():
        object_array(bundle.get(plural), f"bundle.{plural}")
    if not isinstance(bundle.get("manifest"), dict):
        raise ValueError("manifest must be an object")
    object_array(bundle["manifest"].get("members"), "manifest.members")
    for stage in bundle["stages"]:
        object_array(stage.get("partitions"), "stage.partitions")
        for partition in stage["partitions"]:
            object_array(partition.get("slots"), "partition.slots")
        reuse = stage.get("resource_reuse", {})
        if not isinstance(reuse, dict) or any(value != "exclusive" for value in reuse.values()):
            raise ValueError("only stage-wide exclusive resource semantics are currently supported")
    for variant in bundle["variants"]:
        teams = variant.get("teams")
        if not isinstance(teams, dict):
            raise ValueError("variant.teams must be a partition mapping")
        for slots in teams.values():
            object_array(slots, "variant.team")
            for slot in slots:
                object_array(slot.get("equipment_requirements", []), "slot.equipment_requirements")
                seats = [(req.get("kind"), req.get("slot")) for req in slot.get("equipment_requirements", [])]
                if any(kind not in {"light_cone", "relic"} or type(seat) is not str or not seat for kind, seat in seats) or len(seats) != len(set(seats)):
                    raise ValueError("equipment requirements need unique supported kind/slot pairs")
        for key in ("conditions", "cultivation_requirements", "steps", "mechanics", "failure_conditions", "risks"):
            object_array(variant.get(key, []), f"variant.{key}")
    for rule in bundle["troubleshooting"]:
        object_array(rule.get("trigger_conditions", []), "rule.trigger_conditions")
    validity = request.get("latest_known_validity", {})
    if not isinstance(validity, dict) or not isinstance(validity.get("withdrawn_public_refs", []), list):
        raise ValueError("latest_known_validity requires a withdrawal array")
    for ref in validity.get("withdrawn_public_refs", []):
        if not (type(ref) is str and ref or isinstance(ref, dict) and type(ref.get("id")) is str and type(ref.get("revision")) is int and ref["revision"] > 0):
            raise ValueError("withdrawals require an ID or an ID and positive revision")


def object_array(value: Any, name: str) -> None:
    if not isinstance(value, list) or any(not isinstance(item, dict) for item in value):
        raise ValueError(f"{name} must be an array of objects")


def identity(record: Mapping[str, Any]) -> tuple[str, str, int] | None:
    kind, identifier, revision = record.get("kind"), record.get("id"), record.get("revision")
    if type(kind) is str and kind in COLLECTIONS and type(identifier) is str and identifier and type(revision) is int and revision > 0:
        return kind, identifier, revision
    return None


def objects(bundle: Mapping[str, Any]) -> dict[tuple[str, str, int], Mapping[str, Any]]:
    return {(kind, obj[id_key], obj["revision"]): obj for kind, (plural, id_key) in COLLECTIONS.items() for obj in bundle.get(plural, [])}


def declared_dependencies(obj: Mapping[str, Any], index: Mapping[tuple[str, str, int], Mapping[str, Any]]) -> set[tuple[str, str, int]]:
    result: set[tuple[str, str, int]] = set()

    def by_id(kind: str, identifier: Any) -> None:
        if identifier is not None:
            matches = [key for key in index if key[0] == kind and key[1] == identifier]
            result.add(matches[0] if len(matches) == 1 else (kind, str(identifier), -1))

    def walk(value: Any) -> None:
        if isinstance(value, Mapping):
            for key, child in value.items():
                if key in REFERENCE_KINDS:
                    for ref in child:
                        result.add((REFERENCE_KINDS[key], ref.get("id", ""), ref.get("revision", -1)))
                elif key in {"character_id", "character_entity_id", "public_type_id", "material_id", "subject_entity_id"}:
                    by_id("entity", child)
                elif key in {"public_type_ids"}:
                    for identifier in child:
                        by_id("entity", identifier)
                elif key == "template_id":
                    by_id("template", child)
                elif key == "stage_ids":
                    for identifier in child:
                        by_id("stage", identifier)
                elif key in {"variant_ids", "applies_to_variant_ids"}:
                    for identifier in child:
                        by_id("variant", identifier)
                elif key == "suggested_variant_id":
                    by_id("variant", child)
                else:
                    walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(obj)
    return result


def validate_bundle(bundle: Mapping[str, Any], capabilities: set[str], version: str) -> list[dict[str, str]]:
    issues: list[dict[str, str]] = []

    def issue(code: str, message: str) -> None:
        issues.append({"code": code, "message": message})

    manifest = bundle["manifest"]
    release = manifest.get("index_release_id")
    if manifest.get("integrity_algorithm") != HASH_ALGORITHM:
        issue("unsupported_capability", "unsupported or missing canonical integrity algorithm")
    definitions = manifest.get("attribute_definitions")
    if not isinstance(definitions, dict) or any(not isinstance(definition, dict) or definition.get("value_type") not in {"number", "integer", "string", "boolean", "array"} or type(definition.get("loadout_dependent")) is not bool or type(definition.get("unit")) is not str or not isinstance(definition.get("phases"), list) or any(type(phase) is not str for phase in definition.get("phases", [])) for definition in definitions.values()):
        issue("unsupported_schema", "unsupported or missing attribute registry")
    index: dict[tuple[str, str, int], Any] = {}
    for kind, (plural, id_key) in COLLECTIONS.items():
        identifiers: set[str] = set()
        for obj in bundle[plural]:
            identifier, revision = obj.get(id_key), obj.get("revision")
            if not isinstance(identifier, str) or not identifier or type(revision) is not int or revision < 1:
                issue("invalid_payload", f"{kind} requires a string identity and positive integer revision")
                continue
            if identifier in identifiers:
                issue("invalid_payload", f"multiple revisions or duplicate objects for {kind} {identifier}")
            identifiers.add(identifier)
            index[(kind, identifier, revision)] = obj
    if issues:
        return issues
    member_map: dict[tuple[str, str, int], Any] = {}
    for member in manifest["members"]:
        key = identity(member)
        if key not in index or key in member_map:
            issue("missing_member", "manifest member is orphaned, ambiguous, or duplicated")
            continue
        member_map[key] = member
        if member.get("content_hash") != canonical_hash(index[key]):
            issue("integrity_failed", f"content hash mismatch for {key[0]} {key[1]}")
        dependencies = member.get("dependencies")
        if not isinstance(dependencies, list) or any(not isinstance(dep, dict) for dep in dependencies):
            issue("missing_member", "manifest dependencies must be explicit object arrays")
            continue
        declared = {identity(dep) for dep in dependencies}
        if any(dep not in index for dep in declared):
            issue("missing_member", "manifest dependency is unavailable")
        try:
            required = declared_dependencies(index[key], index)
        except (TypeError, KeyError, ValueError, AttributeError):
            issue("invalid_payload", "malformed public reference")
            continue
        if not required <= declared:
            issue("missing_member", f"undeclared or unresolved dependency of {key[1]}")
    if set(index) != set(member_map):
        issue("missing_member", "manifest membership must equal the embedded object set")

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if "index_release_id" in value and value["index_release_id"] != release:
                issue("release_mismatch", "cross-release object or reference")
            if "schema_version" in value and value["schema_version"] != version:
                issue("unsupported_schema", "unsupported nested object schema")
            if "required_capabilities" in value:
                required = value["required_capabilities"]
                if not isinstance(required, list) or any(not isinstance(cap, str) or cap not in capabilities for cap in required):
                    issue("unsupported_capability", "unknown mandatory object capability")
            for key, child in value.items():
                if key in {"local_instance_id", "profile_id", "snapshot_id", "snapshot_revision", "local_source_id", "uid", "authorization_generation", "match_status", "ownership", "equipped_by", "identity_state", "feedback", "fixed_character_ids", "excluded_character_ids", "locked_local_instance_ids"}:
                    issue("invalid_payload", "public bundle contains a private identity field")
                if key.endswith("_refs") or key == "citations":
                    if key not in REFERENCE_KINDS or not isinstance(child, list) or any(not isinstance(ref, dict) for ref in child):
                        issue("unsupported_schema", f"unsupported or malformed reference field {key}")
                    else:
                        for ref in child:
                            if identity({**ref, "kind": REFERENCE_KINDS[key]}) not in index:
                                issue("missing_member", f"unresolved typed {key} reference")
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(bundle)
    return issues


def disabled_objects(bundle: Mapping[str, Any], withdrawn: set[str], incompatible: set[tuple[str, str, int]] | None = None) -> set[tuple[str, str, int]]:
    index = objects(bundle)
    members = {identity(member): member for member in bundle["manifest"]["members"]}
    disabled = {key for key, obj in index.items() if key[1] in withdrawn or f"{key[1]}@{key[2]}" in withdrawn or obj.get("enabled") is False or obj.get("status") in {"withdrawn", "disabled", "rejected", "expired"}}
    disabled.update(incompatible or set())
    changed = True
    while changed:
        changed = False
        for key, obj in index.items():
            # Reverse roster links declare alternatives, not their availability.
            # An unavailable alternative must not revoke its siblings via the template.
            dependencies = declared_dependencies({k: v for k, v in obj.items() if k != "variant_ids"}, index)
            dependencies.update(identity(dep) for dep in members[key]["dependencies"] if not (key[0] == "template" and dep["kind"] == "variant" and dep["id"] in obj.get("variant_ids", [])))
            if key not in disabled and dependencies & disabled:
                disabled.add(key)
                changed = True
    return disabled


def refresh_fixture_members(bundle: dict[str, Any], *, rebuild: bool = False) -> None:
    """Re-publish synthetic test data only; never approves or seals production content."""
    if not str(bundle.get("manifest", {}).get("index_release_id", "")).startswith("fixture:"):
        raise ValueError("fixture publisher refuses production bundles")
    index = objects(bundle)
    manifest = bundle["manifest"]
    manifest["integrity_algorithm"] = HASH_ALGORITHM
    if rebuild:
        manifest["members"] = [{"kind": kind, "id": identifier, "revision": revision} for kind, identifier, revision in index]
    for member in manifest["members"]:
        key = (member["kind"], member["id"], member["revision"])
        if key in index:
            member["content_hash"] = canonical_hash(index[key])
            member["dependencies"] = [{"kind": dep[0], "id": dep[1], "revision": dep[2]} for dep in sorted(declared_dependencies(index[key], index))]
