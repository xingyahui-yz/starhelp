"""Digest/closure recognition of A 313508f; executable conversion is refused."""

from __future__ import annotations

from typing import Any

from .common import A_BASELINE, digest, fail, original

A_LEGACY_PROFILE = "starhelp.knowledge.native.313508f"
KINDS = ("entity", "knowledge", "stage", "template", "variant", "troubleshooting", "resource")
RECORD_BODY = ("id", "revision", "scope", "payload", "content_hash", "evidence_refs", "dependency_refs")
EVIDENCE_BODY = ("id", "title", "url", "excerpt", "locator", "relation", "scope", "evidence_status", "content_hash", "license_status")


def verify_native_bundle(bundle: dict[str, Any]) -> str:
    manifest = bundle.get("manifest", {})
    if bundle.get("schema_id") != "PublicBundle" or bundle.get("contract_version") != "0.1-draft" or bundle.get("schema_version") != "0.1-draft" or manifest.get("schema_version") != "0.1-draft" or manifest.get("hash_algorithm") != "sha256-canonical-json-utf8":
        fail("unsupported_public_schema", "A baseline native schema does not match")
    records, evidence = bundle.get("records"), bundle.get("evidence")
    if type(records) is not dict or set(records) != set(KINDS) or type(evidence) is not list:
        fail("invalid_public_bundle", "A baseline record collections are incomplete")
    index, body, members = {}, [], []
    for kind in KINDS:
        if type(records[kind]) is not list:
            fail("invalid_public_bundle", "A record collection must be an array")
        for row in records[kind]:
            if type(row) is not dict or set(row) != set(RECORD_BODY) or type(row["id"]) is not str or type(row["revision"]) is not int or row["revision"] < 1:
                fail("invalid_public_bundle", "unsupported A baseline record wrapper")
            key = kind, row["id"], row["revision"]
            if key in index:
                fail("invalid_public_bundle", "duplicate A record")
            index[key] = row
            material = {"kind": kind, "id": row["id"], "scope": row["scope"], "payload": row["payload"], "evidence": row["evidence_refs"], "dependencies": row["dependency_refs"]}
            if digest(material) != row["content_hash"]:
                fail("producer_integrity_failed", "A original record hash mismatch")
            body.append({"kind": kind, **{key: row[key] for key in RECORD_BODY}})
            members.append({"kind": kind, "id": row["id"], "revision": row["revision"], "content_hash": row["content_hash"], "dependencies": row["dependency_refs"]})
    body.sort(key=lambda row: (row["kind"], row["id"]))
    members.sort(key=lambda row: (row["kind"], row["id"]))
    if manifest.get("members") != members:
        fail("producer_integrity_failed", "A original manifest members mismatch")
    evidences = {}
    for item in evidence:
        if type(item) is not dict or item.get("id") in evidences:
            fail("invalid_public_bundle", "invalid or duplicate A evidence")
        material = {key: item.get(key) for key in ("url", "title", "excerpt", "locator", "scope", "relation")}
        if digest(material) != item.get("content_hash"):
            fail("producer_integrity_failed", "A original evidence hash mismatch")
        if item.get("license_status") != "allowed" or item.get("evidence_status") not in {"confirmed", "suggested"} or item.get("validity_status", "valid") != "valid":
            fail("producer_evidence_unavailable", "original evidence is withdrawn, unknown, or lacks publication permission")
        evidences[item["id"]] = item
    used = set()
    for row in index.values():
        for ref in row["dependency_refs"]:
            if (ref["kind"], ref["id"], ref["revision"]) not in index:
                fail("producer_dependency_missing", "A dependency is unavailable")
        for ref in row["evidence_refs"]:
            used.add(ref["id"])
            if ref["id"] not in evidences:
                fail("producer_dependency_missing", "A evidence is unavailable")
    if used != set(evidences) or sorted(manifest.get("evidence_ids", [])) != sorted(used):
        fail("producer_dependency_missing", "A evidence membership is incomplete")
    evidence_body = sorted(({key: item[key] for key in EVIDENCE_BODY} for item in evidence), key=lambda item: item["id"])
    content_hash = digest({"records": body, "evidence": evidence_body})
    if content_hash != manifest.get("content_hash"):
        fail("producer_integrity_failed", "A original release content hash mismatch")
    for key, kind in {"knowledge": "knowledge", "stages": "stage", "templates": "template", "variants": "variant", "troubleshooting": "troubleshooting", "resources": "resource"}.items():
        if bundle.get(key) != records[kind]:
            fail("producer_integrity_failed", "A convenience collection differs from original records")
    expected_entities = [{"entity_id": row["id"], "revision": row["revision"], "entity_type": row["payload"]["entity_type"], "canonical_name": row["payload"]["canonical_name"], "game_version": row["scope"].get("game_version"), "environment": row["scope"]["environment"], "release_status": row["scope"]["release_status"], "payload": row["payload"], "content_hash": row["content_hash"], "evidence_refs": row["evidence_refs"]} for row in records["entity"]]
    if bundle.get("entities") != expected_entities:
        fail("producer_integrity_failed", "A entity convenience view differs from original records")
    return content_hash


def inspect_legacy(envelope: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    bundle, proof = original(envelope, "starhelp_knowledge", A_BASELINE, A_LEGACY_PROFILE)
    content_hash = verify_native_bundle(bundle)
    proof.update(index_release_id=bundle["manifest"]["index_release_id"], original_content_hash=content_hash, original_digest_and_closure_verified=True)
    return bundle, proof


def reject_legacy(envelope: Any) -> None:
    _, proof = inspect_legacy(envelope)
    fail("producer_semantics_missing", "A baseline export integrity is valid, but required executable semantics/provenance are absent", {
        "original_proof": proof,
        "missing": ["explicit consumer export profile", "required stage seats", "exact public goals", "typed attribute registry", "revisioned evidence identity", "digest-bound review/publication provenance"],
    })
