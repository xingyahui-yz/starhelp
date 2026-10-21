"""Verify A's versioned signed producer view before passing it to native rules."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime
from typing import Any

from ..validation import validate_bundle
from .a_legacy import verify_native_bundle
from .common import digest, fail, original
from .signature import verify_manifest_signature
from .projection import check_projection, consumption_view

DISTRIBUTION_PROFILE = "starhelp.b-publicbundle-envelope.v1"
DISTRIBUTION_CAPABILITY = "starhelp.knowledge-distribution.v1"
# Actual export/independent A verification and fixed B Ed25519 validation passed.
A_PRODUCERS = {
    "b790a52aea4fabdb362d35c37d9b511b737e1fe4": "0.2.0",
    "00d4a5844e74050359227c274de712878bf9187c": "0.2.0",
    "dcb1e3ee220b85229bedc6c79d72ebe495825f37": "0.3.0",
}
ACCEPTED_A_COMMITS = frozenset(A_PRODUCERS)


def _identity(item: dict[str, Any]) -> tuple[str, str, int]:
    return item["kind"], item["id"], item["revision"]


def _approval_proof(view: dict[str, Any], native: dict[str, Any], commit: str, release: str, content_hash: str) -> dict[str, Any]:
    source = view["manifest"].get("source_proof")
    if type(source) is not dict or source.get("source_profile") != "starhelp.knowledge.native.v0.1-draft" or source.get("source_schema_version") != "0.1-draft" or source.get("source_hash_algorithm") != "sha256-canonical-json-utf8" or source.get("source_release_id") != release or source.get("source_release_content_hash") != content_hash or source.get("producer_commit") != commit or source.get("producer_package_version") != A_PRODUCERS[commit]:
        fail("producer_provenance_mismatch", "planner source proof does not identify the pinned original producer/release")
    if source.get("publication_state") not in {"active", "superseded"}:
        fail("producer_approval_unproven", "release publication is not established")
    members = {_identity(item): item for item in native["manifest"]["members"]}
    source_members, reviews = source.get("source_members"), source.get("approved_reviews")
    if type(source_members) is not list or type(reviews) is not list:
        fail("producer_approval_unproven", "original member and review ledgers are required")
    exported = {_identity(item): item for item in source_members}
    reviewed = {_identity(item): item for item in reviews}
    if len(exported) != len(source_members) or len(reviewed) != len(reviews) or set(members) != set(exported) or set(members) != set(reviewed):
        fail("producer_approval_unproven", "review/source proof does not cover the exact original member set")
    for key, member in members.items():
        review = reviewed[key]
        if exported[key].get("content_hash") != member["content_hash"] or review.get("reviewed_content_hash") != member["content_hash"] or review.get("decision") != "approved" or type(review.get("review_revision")) is not int or review["review_revision"] < 1:
            fail("producer_approval_unproven", "approved review is not bound to this exact revision/digest")
        if datetime.fromisoformat(review["reviewed_at"].replace("Z", "+00:00")).tzinfo is None:
            fail("producer_approval_unproven", "review time is not explicit")
    audit = source.get("publication_audit", {})
    if type(audit) is not dict or audit.get("operation") not in {"activate", "rollback"} or type(audit.get("event_id")) is not str or not audit["event_id"] or datetime.fromisoformat(audit["recorded_at"].replace("Z", "+00:00")).tzinfo is None:
        fail("producer_approval_unproven", "explicit publication audit is missing")
    if sorted(source.get("source_evidence_ids", [])) != sorted(item["id"] for item in native["evidence"]):
        fail("producer_provenance_mismatch", "evidence provenance differs from the original release")
    for kind, plural in (("entity", "entities"), ("stage", "stages"), ("template", "templates"), ("variant", "variants"), ("troubleshooting", "troubleshooting")):
        for item in view[plural]:
            identifier = item["stage_id"] if kind == "stage" else item["id"]
            if (kind, identifier, item["revision"]) not in members:
                fail("producer_provenance_mismatch", "projected member identity has no original approved revision")
            if kind in {"template", "variant", "troubleshooting"} and (item.get("approval_status") != "approved" or item.get("publication_status") != "published"):
                fail("producer_approval_unproven", "projected executable object lacks approved/published provenance")
    return deepcopy(source)


def adapt_distribution(envelope: dict[str, Any], trust: Any) -> tuple[dict[str, Any], dict[str, Any]]:
    commit = envelope.get("producer_commit")
    if commit not in ACCEPTED_A_COMMITS:
        fail("unsupported_producer_version", "A producer commit has not been pinned for consumption")
    distribution, proof = original(envelope, "starhelp_knowledge", commit, DISTRIBUTION_PROFILE)
    manifest = distribution.get("manifest", {})
    if distribution.get("schema_id") != "PublicBundle" or distribution.get("contract_version") != "0.1-draft" or distribution.get("schema_version") != "0.1-draft" or manifest.get("distribution_profile") != DISTRIBUTION_PROFILE or manifest.get("signature_algorithm") != "ed25519" or manifest.get("native_profile") != "starhelp.knowledge.native.v0.1-draft" or manifest.get("planner_profile") != "starhelp.local.v0.2":
        fail("unsupported_public_schema", "A distribution does not match the supported layered profile")
    if manifest.get("required_capabilities") != [DISTRIBUTION_CAPABILITY]:
        fail("unsupported_producer_capability", "unknown or missing mandatory distribution capability")
    signature_proof = verify_manifest_signature(manifest, distribution.get("signature"), trust)
    objects, members = distribution.get("objects"), manifest.get("members")
    release = manifest.get("index_release_id")
    if type(release) is not str or not release or release != envelope.get("expected_release_id"):
        fail("producer_release_mismatch", "original release differs from the explicitly requested release")
    if type(objects) is not dict or type(members) is not dict or set(objects) != set(members):
        fail("producer_dependency_missing", "signed member/object closure is incomplete")
    native_id, planner_id = f"native-release:{release}", f"planner-view:{release}"
    if set(objects) != {native_id, planner_id}:
        fail("unsupported_public_schema", "unknown object layout for this producer distribution profile")
    for identifier, obj in objects.items():
        if type(obj) is not dict or digest(obj) != members[identifier] or type(obj.get("refs")) is not list or any(type(ref) is not str or ref not in objects for ref in obj["refs"]):
            fail("producer_integrity_failed", "original signed object hash/reference does not match")
    if objects[native_id].get("kind") != "starhelp_native_release" or objects[native_id]["refs"] != [] or objects[planner_id].get("kind") != "starhelp_planner_view" or objects[planner_id]["refs"] != [native_id]:
        fail("producer_dependency_missing", "planner/native relationship is not explicit")
    native, view = objects[native_id]["bundle"], objects[planner_id]["bundle"]
    content_hash = verify_native_bundle(native)
    if native["manifest"]["index_release_id"] != release or content_hash != manifest.get("source_release_content_hash") or native["manifest"].get("required_capabilities") != []:
        fail("producer_provenance_mismatch", "native release/capabilities differ from the signed consumer profile")
    if view.get("adapter_profile") != "starhelp.local.v0.2" or view.get("contract_version") != "0.1-draft" or view.get("schema_version") != "0.1-draft" or view["manifest"].get("index_release_id") != release or digest(view["manifest"]) != manifest.get("planner_manifest_hash"):
        fail("producer_integrity_failed", "original projected view/manifest does not match its signed digest")
    issues = validate_bundle(view, {"starhelp.local-profile.v0.2"}, "0.1-draft")
    if issues:
        fail("invalid_projected_bundle", "original projected public members are incompatible", issues)
    approvals = _approval_proof(view, native, commit, release, content_hash)
    check_projection(native, view)
    normalized, normalized_proof = consumption_view(native, view)
    proof.update(signature_proof)
    proof.update(index_release_id=release, original_content_hash=content_hash, original_distribution_members=deepcopy(members), original_planner_manifest_hash=manifest["planner_manifest_hash"], approval_and_publication_source=approvals, internal_hashes_are_signatures=False)
    proof["signature_verification"] = "verified mathematically against caller-pinned synthetic-test key"
    proof["normalized_consumption"] = normalized_proof
    proof["original_member_provenance"] = [{"kind": kind, **{key: row[key] for key in ("id", "revision", "scope", "content_hash", "evidence_refs", "dependency_refs")}} for kind, rows in native["records"].items() for row in rows]
    proof["original_evidence_provenance"] = deepcopy(native["evidence"])
    return normalized, proof
