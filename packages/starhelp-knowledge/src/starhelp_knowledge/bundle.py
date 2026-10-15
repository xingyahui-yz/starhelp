"""Public bundle integrity and dependency verification."""

from __future__ import annotations

from typing import Any

from starhelp_knowledge.errors import IntegrityFailure, MissingDependency, UnsupportedSchema, WithdrawnEvidence
from starhelp_knowledge.records import content_hash, validate_public_record

RECORD_COLLECTIONS = ("entity", "knowledge", "stage", "template", "variant", "troubleshooting", "resource")


def bundle_content_body(bundle: dict[str, Any]) -> dict[str, Any]:
    records = [
        {
            "kind": kind,
            "id": record["id"],
            "revision": record["revision"],
            "scope": record["scope"],
            "payload": record["payload"],
            "content_hash": record["content_hash"],
            "evidence_refs": record["evidence_refs"],
            "dependency_refs": record["dependency_refs"],
        }
        for kind in RECORD_COLLECTIONS
        for record in bundle["records"][kind]
    ]
    evidence = [
        {
            "id": item["id"],
            "title": item["title"],
            "url": item["url"],
            "excerpt": item["excerpt"],
            "locator": item["locator"],
            "relation": item["relation"],
            "scope": item["scope"],
            "evidence_status": item["evidence_status"],
            "content_hash": item["content_hash"],
            "license_status": item["license_status"],
        }
        for item in bundle["evidence"]
    ]
    records.sort(key=lambda item: (item["kind"], item["id"]))
    evidence.sort(key=lambda item: item["id"])
    return {"records": records, "evidence": evidence}


def verify_public_bundle(bundle: dict[str, Any]) -> str:
    """Verify schema, per-member hashes, reference closure, and release content hash."""
    if not isinstance(bundle, dict) or bundle.get("schema_id") != "PublicBundle":
        raise UnsupportedSchema()
    manifest = bundle.get("manifest")
    if not isinstance(manifest, dict) or manifest.get("hash_algorithm") != "sha256-canonical-json-utf8":
        raise UnsupportedSchema()
    if bundle.get("schema_version") != manifest.get("schema_version"):
        raise UnsupportedSchema()
    if not isinstance(bundle.get("records"), dict) or set(bundle["records"]) != set(RECORD_COLLECTIONS):
        raise UnsupportedSchema()
    record_refs: set[tuple[str, str, int]] = set()
    evidence_by_id = {item.get("id"): item for item in bundle.get("evidence", []) if isinstance(item, dict)}
    if len(evidence_by_id) != len(bundle.get("evidence", [])):
        raise IntegrityFailure()
    for kind in RECORD_COLLECTIONS:
        if not isinstance(bundle["records"][kind], list):
            raise UnsupportedSchema()
        for record in bundle["records"][kind]:
            if not isinstance(record, dict):
                raise IntegrityFailure()
            record_id, revision = record.get("id"), record.get("revision")
            if not isinstance(record_id, str) or not isinstance(revision, int) or isinstance(revision, bool) or revision < 1:
                raise IntegrityFailure()
            ref = (kind, record_id, revision)
            if ref in record_refs:
                raise IntegrityFailure()
            record_refs.add(ref)
            if content_hash({
                "kind": kind,
                "id": record_id,
                "scope": record.get("scope"),
                "payload": record.get("payload"),
                "evidence": record.get("evidence_refs"),
                "dependencies": record.get("dependency_refs"),
            }) != record.get("content_hash"):
                raise IntegrityFailure()
            clean_scope, clean_payload, evidence_refs, dependencies = validate_public_record(
                kind,
                record_id,
                record.get("scope"),
                record.get("payload"),
                record.get("evidence_refs"),
                record.get("dependency_refs"),
            )
            if clean_scope != record.get("scope") or clean_payload != record.get("payload"):
                raise IntegrityFailure()
            for ref_evidence in evidence_refs:
                item = evidence_by_id.get(ref_evidence["id"])
                if item is None:
                    raise MissingDependency()
                if item.get("license_status") != "allowed" or item.get("evidence_status") == "unknown":
                    raise WithdrawnEvidence()
    for kind in RECORD_COLLECTIONS:
        for record in bundle["records"][kind]:
            for dependency in record["dependency_refs"]:
                if (dependency["kind"], dependency["id"], dependency["revision"]) not in record_refs:
                    raise MissingDependency()
    convenience_keys = {
        "knowledge": "knowledge",
        "stages": "stage",
        "templates": "template",
        "variants": "variant",
        "troubleshooting": "troubleshooting",
        "resources": "resource",
    }
    for key, kind in convenience_keys.items():
        if bundle.get(key) != bundle["records"][kind]:
            raise IntegrityFailure()
    expected_entities = [
        {
            "entity_id": item["id"],
            "revision": item["revision"],
            "entity_type": item["payload"]["entity_type"],
            "canonical_name": item["payload"]["canonical_name"],
            "game_version": item["scope"].get("game_version"),
            "environment": item["scope"]["environment"],
            "release_status": item["scope"]["release_status"],
            "payload": item["payload"],
            "content_hash": item["content_hash"],
            "evidence_refs": item["evidence_refs"],
        }
        for item in bundle["records"]["entity"]
    ]
    if bundle.get("entities") != expected_entities:
        raise IntegrityFailure()
    for item in evidence_by_id.values():
        evidence_material = {
            "url": item.get("url"),
            "title": item.get("title"),
            "excerpt": item.get("excerpt"),
            "locator": item.get("locator"),
            "scope": item.get("scope"),
            "relation": item.get("relation"),
        }
        if content_hash(evidence_material) != item.get("content_hash"):
            raise IntegrityFailure()
    expected_evidence_ids = {ref["id"] for records in bundle["records"].values() for record in records for ref in record["evidence_refs"]}
    if expected_evidence_ids != set(evidence_by_id):
        raise MissingDependency()
    manifest_members = manifest.get("members")
    expected_members = [
        {"kind": kind, "id": record["id"], "revision": record["revision"], "content_hash": record["content_hash"], "dependencies": record["dependency_refs"]}
        for kind in RECORD_COLLECTIONS
        for record in bundle["records"][kind]
    ]
    expected_members.sort(key=lambda item: (item["kind"], item["id"]))
    if manifest_members != expected_members or sorted(manifest.get("evidence_ids", [])) != sorted(expected_evidence_ids):
        raise IntegrityFailure()
    digest = content_hash(bundle_content_body(bundle))
    if digest != manifest.get("content_hash"):
        raise IntegrityFailure()
    return digest
