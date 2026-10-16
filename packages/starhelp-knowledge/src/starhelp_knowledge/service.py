"""Public knowledge domain services backed by a single SQLite database."""

from __future__ import annotations

import json
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlparse

from starhelp_knowledge.bundle import verify_public_bundle
from starhelp_knowledge.database import KnowledgeDatabase
from starhelp_knowledge.errors import (
    Conflict,
    CoverageInsufficient,
    IntegrityFailure,
    InvalidPayload,
    InvalidTransition,
    MissingDependency,
    NotFound,
    PermissionDenied,
    WithdrawnEvidence,
)
from starhelp_knowledge.policy import CONTRACT_VERSION, Principal, validate_public_query
from starhelp_knowledge.records import canonical_json, content_hash, validate_public_record

UPDATE_STAGES = ("discover", "fetch", "normalize", "extract", "review")

def now_iso() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


def decode(value: str | None, default: Any = None) -> Any:
    return default if value is None else json.loads(value)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


class KnowledgeService:
    def __init__(self, database: KnowledgeDatabase) -> None:
        self.database = database
        self.database.migrate()

    def add_source(
        self, principal: Principal, *, source_id: str, name: str, platform: str, source_role: str
    ) -> None:
        principal.require("update")
        if source_role not in {"reference", "guide", "trend"}:
            raise InvalidPayload("invalid source role")
        if not all(isinstance(value, str) and 1 <= len(value) <= 200 for value in (source_id, name, platform)):
            raise InvalidPayload("invalid source")
        with self.database.transaction() as db:
            db.execute(
                "INSERT INTO sources(source_id,name,platform,source_role,enabled,created_at) VALUES(?,?,?,?,0,?)",
                (source_id, name, platform, source_role, now_iso()),
            )
            self._audit(db, principal, "source_created", "source", source_id)

    def set_source_policy(
        self,
        principal: Principal,
        *,
        source_id: str,
        permission_status: str,
        terms_reference: str | None,
        allowed_domains: list[str],
        allowed_paths: list[str],
        rate_policy: dict[str, Any],
        storage_policy: dict[str, Any],
        checked_at: str | None,
    ) -> str:
        principal.require("update")
        if permission_status not in {"unknown", "allowed", "restricted", "disallowed"}:
            raise InvalidPayload("invalid source policy")
        if not all(isinstance(items, list) and len(items) <= 100 for items in (allowed_domains, allowed_paths)):
            raise InvalidPayload("invalid source policy")
        if any(not isinstance(item, str) or len(item) > 300 for item in allowed_domains + allowed_paths):
            raise InvalidPayload("invalid source policy")
        if not isinstance(rate_policy, dict) or not isinstance(storage_policy, dict):
            raise InvalidPayload("invalid source policy")
        if storage_policy.get("mode", "minimal_excerpt") not in {"minimal_excerpt", "full_text_allowed", "metadata_only"}:
            raise InvalidPayload("invalid storage policy")
        if permission_status == "allowed":
            principal.require("admin")
            if not isinstance(terms_reference, str) or not terms_reference.startswith("https://") or not checked_at:
                raise InvalidPayload("allowed source policy requires dated terms evidence")
        policy_id = _new_id("pol")
        with self.database.transaction() as db:
            if db.execute("SELECT 1 FROM sources WHERE source_id=?", (source_id,)).fetchone() is None:
                raise NotFound()
            row = db.execute(
                "SELECT COALESCE(MAX(revision),0)+1 AS revision FROM source_policy_revisions WHERE source_id=?",
                (source_id,),
            ).fetchone()
            revision = int(row["revision"])
            db.execute(
                "INSERT INTO source_policy_revisions VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    policy_id, source_id, revision, permission_status, terms_reference,
                    canonical_json(allowed_domains), canonical_json(allowed_paths),
                    canonical_json(rate_policy), canonical_json(storage_policy), checked_at,
                ),
            )
            db.execute("UPDATE sources SET enabled=? WHERE source_id=?", (int(permission_status == "allowed"), source_id))
            self._audit(db, principal, "source_policy_recorded", "source", source_id, details={"policy_revision": revision, "permission_status": permission_status})
        return policy_id

    def record_source_capabilities(
        self,
        principal: Principal,
        *,
        source_id: str,
        adapter_version: str,
        status: str,
        capabilities: dict[str, Any],
        coverage: dict[str, Any],
        evidence: list[dict[str, Any]],
    ) -> str:
        principal.require("update")
        if status not in {"declared", "verified", "partial", "unavailable", "unknown"}:
            raise InvalidPayload("invalid capability status")
        if not isinstance(capabilities, dict) or not isinstance(coverage, dict) or not isinstance(evidence, list):
            raise InvalidPayload("invalid capability snapshot")
        # A verified claim must point to concrete checks and an explicitly recorded time.
        if status == "verified" and (not evidence or not all(isinstance(item, dict) and item.get("checked_at") for item in evidence)):
            raise InvalidPayload("verified capability requires dated evidence")
        if status == "verified":
            principal.require("admin")
        snapshot_id = _new_id("cap")
        with self.database.transaction() as db:
            if db.execute("SELECT 1 FROM sources WHERE source_id=?", (source_id,)).fetchone() is None:
                raise NotFound()
            db.execute(
                "INSERT INTO source_capability_snapshots VALUES(?,?,?,?,?,?,?,?)",
                (snapshot_id, source_id, adapter_version, status, canonical_json(capabilities), canonical_json(coverage), canonical_json(evidence), now_iso()),
            )
            self._audit(db, principal, "source_capabilities_recorded", "source", source_id, details={"snapshot_id": snapshot_id, "status": status})
        return snapshot_id

    def source_report(self, principal: Principal) -> dict[str, Any]:
        principal.require("update")
        with self.database.reader() as db:
            sources = db.execute("SELECT * FROM sources ORDER BY source_id").fetchall()
            report: list[dict[str, Any]] = []
            for source in sources:
                policy = db.execute(
                    "SELECT * FROM source_policy_revisions WHERE source_id=? ORDER BY revision DESC LIMIT 1",
                    (source["source_id"],),
                ).fetchone()
                capability = db.execute(
                    "SELECT * FROM source_capability_snapshots WHERE source_id=? ORDER BY observed_at DESC LIMIT 1",
                    (source["source_id"],),
                ).fetchone()
                report.append({
                    "source_id": source["source_id"],
                    "name": source["name"],
                    "platform": source["platform"],
                    "source_role": source["source_role"],
                    "enabled": bool(source["enabled"]),
                    "policy": None if policy is None else {
                        "revision": policy["revision"],
                        "permission_status": policy["permission_status"],
                        "terms_reference": policy["terms_reference"],
                        "checked_at": policy["checked_at"],
                        "allowed_domains": decode(policy["allowed_domains_json"], []),
                        "allowed_paths": decode(policy["allowed_paths_json"], []),
                        "rate_policy": decode(policy["rate_policy_json"], {}),
                        "storage_policy": decode(policy["storage_policy_json"], {}),
                    },
                    "capabilities": None if capability is None else {
                        "snapshot_id": capability["snapshot_id"],
                        "adapter_version": capability["adapter_version"],
                        "status": capability["status"],
                        "capabilities": decode(capability["capabilities_json"], {}),
                        "coverage": decode(capability["coverage_json"], {}),
                        "evidence": decode(capability["evidence_json"], []),
                        "observed_at": capability["observed_at"],
                    },
                })
            allowed_ids = [source["source_id"] for source in report if source["enabled"]]
            verified_ids = [source["source_id"] for source in report if source["capabilities"] and source["capabilities"]["status"] == "verified"]
            return {"sources": report, "source_policy_allowed_ids": allowed_ids, "capability_verified_ids": verified_ids, "production_adapter_configured": False}

    def add_public_evidence(
        self,
        principal: Principal,
        *,
        source_id: str,
        external_content_id: str | None,
        canonical_url: str,
        content_kind: str,
        title: str,
        author_id: str | None,
        excerpt: str | None,
        locator: dict[str, Any],
        license_status: str,
        published_at: str | None,
        relation: str,
        evidence_status: str,
        scope: dict[str, Any],
    ) -> str:
        principal.require("update")
        if license_status != "allowed":
            raise PermissionDenied()
        if evidence_status not in {"confirmed", "suggested", "unknown"} or relation not in {"supports", "refutes", "qualifies", "context"}:
            raise InvalidPayload("invalid evidence status")
        if not isinstance(locator, dict) or not isinstance(scope, dict):
            raise InvalidPayload("invalid evidence")
        if excerpt is not None and (not isinstance(excerpt, str) or len(excerpt) > 4000):
            raise InvalidPayload("excerpt exceeds minimal storage limit")
        parsed = urlparse(canonical_url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise InvalidPayload("evidence URL must use HTTPS")
        document_id = _new_id("doc")
        document_revision_id = _new_id("docrev")
        evidence_id = _new_id("ev")
        timestamp = now_iso()
        with self.database.transaction() as db:
            source = db.execute("SELECT enabled FROM sources WHERE source_id=?", (source_id,)).fetchone()
            if source is None:
                raise NotFound()
            policy = db.execute(
                "SELECT * FROM source_policy_revisions WHERE source_id=? ORDER BY revision DESC LIMIT 1",
                (source_id,),
            ).fetchone()
            if policy is None or policy["permission_status"] != "allowed" or not source["enabled"]:
                raise PermissionDenied()
            allowed_domains = decode(policy["allowed_domains_json"], [])
            if not any(parsed.hostname == host or parsed.hostname.endswith("." + host) for host in allowed_domains):
                raise PermissionDenied()
            allowed_paths = decode(policy["allowed_paths_json"], [])
            if allowed_paths and not any(parsed.path == prefix or parsed.path.startswith(prefix.rstrip("/") + "/") for prefix in allowed_paths):
                raise PermissionDenied()
            storage = decode(policy["storage_policy_json"], {})
            if storage.get("mode") == "metadata_only" and excerpt:
                excerpt = None
            if storage.get("mode") != "full_text_allowed" and excerpt is not None and len(excerpt) > int(storage.get("max_excerpt_chars", 4000)):
                raise InvalidPayload("excerpt exceeds source policy")
            evidence_content = {"url": canonical_url, "title": title, "excerpt": excerpt, "locator": locator, "scope": scope, "relation": relation}
            digest = content_hash(evidence_content)
            db.execute(
                "INSERT INTO documents VALUES(?,?,?,?,?,?)",
                (document_id, source_id, external_content_id, canonical_url, content_kind, timestamp),
            )
            db.execute(
                "INSERT INTO document_revisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (document_revision_id, document_id, 1, title, author_id, excerpt, canonical_json(locator), digest, license_status, published_at, timestamp, "valid"),
            )
            db.execute(
                "INSERT INTO evidence VALUES(?,?,?,?,?,?,?,?,?,?)",
                (evidence_id, document_revision_id, canonical_json(locator), excerpt, relation, canonical_json(scope), evidence_status, digest, "valid", timestamp),
            )
            self._audit(db, principal, "public_evidence_added", "evidence", evidence_id, details={"source_id": source_id, "license_status": license_status})
        return evidence_id

    def create_candidate(
        self,
        principal: Principal,
        *,
        kind: str,
        record_id: str,
        scope: dict[str, Any],
        payload: dict[str, Any],
        evidence_refs: list[dict[str, Any]],
        dependency_refs: list[dict[str, Any]],
    ) -> dict[str, Any]:
        principal.require("update")
        clean_scope, clean_payload, clean_evidence, clean_deps = validate_public_record(
            kind, record_id, scope, payload, evidence_refs, dependency_refs
        )
        record_revision_id = _new_id("rev")
        timestamp = now_iso()
        material = {"kind": kind, "id": record_id, "scope": clean_scope, "payload": clean_payload, "evidence": clean_evidence, "dependencies": clean_deps}
        digest = content_hash(material)
        with self.database.transaction() as db:
            for ref in clean_evidence:
                evidence = db.execute(
                    "SELECT e.validity_status,e.evidence_status,d.license_status FROM evidence e "
                    "JOIN document_revisions d ON d.document_revision_id=e.document_revision_id WHERE e.evidence_id=?",
                    (ref["id"],),
                ).fetchone()
                if evidence is None or evidence["license_status"] != "allowed":
                    raise InvalidPayload("candidate evidence is missing or lacks publication permission")
                if evidence["validity_status"] != "valid":
                    raise WithdrawnEvidence()
                if evidence["evidence_status"] == "unknown":
                    raise InvalidPayload("unknown evidence cannot support a public candidate")
            row = db.execute("SELECT current_revision FROM public_records WHERE record_kind=? AND record_id=?", (kind, record_id)).fetchone()
            revision = 1 if row is None else int(row["current_revision"]) + 1
            if row is None:
                db.execute("INSERT INTO public_records VALUES(?,?,?)", (record_id, kind, revision))
            else:
                db.execute("UPDATE public_records SET current_revision=? WHERE record_kind=? AND record_id=?", (revision, kind, record_id))
            db.execute(
                "INSERT INTO public_record_revisions VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                (record_revision_id, kind, record_id, revision, "candidate", canonical_json(clean_scope), canonical_json(clean_payload), canonical_json(clean_evidence), canonical_json(clean_deps), digest, principal.actor_id, timestamp),
            )
            if kind == "entity":
                db.execute(
                    "INSERT INTO entities(entity_id,entity_type,canonical_name,created_at) VALUES(?,?,?,?) "
                    "ON CONFLICT(entity_id) DO UPDATE SET entity_type=excluded.entity_type,canonical_name=excluded.canonical_name",
                    (record_id, clean_payload["entity_type"], clean_payload["canonical_name"], timestamp),
                )
                db.execute(
                    "INSERT INTO entity_revisions VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                    (_new_id("entityrev"), record_id, revision, clean_scope.get("game_version"), clean_scope["environment"], clean_scope["release_status"], "0.1-draft", canonical_json(clean_payload), digest, "valid", timestamp),
                )
            self._audit(db, principal, "candidate_created", kind, record_id, revision=revision, details={"content_hash": digest, "evidence_count": len(clean_evidence), "dependency_count": len(clean_deps)})
        return {"record_id": record_id, "record_kind": kind, "revision": revision, "state": "candidate", "content_hash": digest}

    def review_candidate(
        self,
        principal: Principal,
        *,
        kind: str,
        record_id: str,
        revision: int,
        expected_content_hash: str,
        decision: str,
        note: str,
    ) -> dict[str, Any]:
        principal.require("review")
        if decision not in {"approved", "rejected"} or not isinstance(note, str) or len(note) > 2000:
            raise InvalidPayload("invalid review")
        with self.database.transaction() as db:
            row = db.execute(
                "SELECT * FROM public_record_revisions WHERE record_kind=? AND record_id=? AND revision=?",
                (kind, record_id, revision),
            ).fetchone()
            if row is None:
                raise NotFound()
            if row["state"] != "candidate":
                raise InvalidTransition()
            if row["created_by"] == principal.actor_id:
                raise PermissionDenied()
            if row["content_hash"] != expected_content_hash:
                raise Conflict()
            review_id = _new_id("review")
            review_revision = int(db.execute("SELECT COALESCE(MAX(review_revision),0)+1 AS n FROM reviews WHERE record_revision_id=?", (row["record_revision_id"],)).fetchone()["n"])
            db.execute(
                "INSERT INTO reviews VALUES(?,?,?,?,?,?,?,?)",
                (review_id, row["record_revision_id"], review_revision, decision, principal.actor_id, note, expected_content_hash, now_iso()),
            )
            db.execute("UPDATE public_record_revisions SET state=? WHERE record_revision_id=?", (decision, row["record_revision_id"]))
            self._audit(db, principal, f"candidate_{decision}", kind, record_id, revision=revision, details={"review_id": review_id, "content_hash": expected_content_hash})
        return {"record_id": record_id, "record_kind": kind, "revision": revision, "state": decision, "review_id": review_id}

    def build_release(
        self,
        principal: Principal,
        *,
        members: list[dict[str, Any]],
        coverage: dict[str, Any],
        required_capabilities: list[str],
        attribute_definitions: dict[str, Any] | None = None,
        schema_version: str = "0.1-draft",
    ) -> dict[str, Any]:
        principal.require("publish")
        if not isinstance(members, list) or not members or len(members) > 10000:
            raise InvalidPayload("release must list at least one public member")
        if (
            not isinstance(coverage, dict)
            or not isinstance(required_capabilities, list)
            or any(not isinstance(cap, str) for cap in required_capabilities)
            or attribute_definitions is not None and not isinstance(attribute_definitions, dict)
        ):
            raise InvalidPayload("invalid release manifest")
        release_id = _new_id("rel")
        with self.database.transaction() as db:
            active = db.execute("SELECT value FROM app_state WHERE key='active_release_id'").fetchone()
            parent_id = None if active is None else active["value"]
            rows: list[dict[str, Any]] = []
            seen: set[tuple[str, str]] = set()
            for ref in members:
                if not isinstance(ref, dict) or set(ref) != {"kind", "id", "revision"}:
                    raise InvalidPayload("invalid release member")
                key = (ref["kind"], ref["id"])
                if key in seen:
                    raise InvalidPayload("duplicate release member")
                seen.add(key)
                row = db.execute(
                    "SELECT * FROM public_record_revisions WHERE record_kind=? AND record_id=? AND revision=?",
                    (ref["kind"], ref["id"], ref["revision"]),
                ).fetchone()
                if row is None or row["state"] != "approved":
                    raise InvalidTransition("only explicitly approved revisions can be published")
                rows.append(dict(row))
            member_map = {(row["record_kind"], row["record_id"], row["revision"]): row for row in rows}
            evidence_rows: dict[str, dict[str, Any]] = {}
            for row in rows:
                for dep in decode(row["dependency_refs_json"], []):
                    if (dep["kind"], dep["id"], dep["revision"]) not in member_map:
                        raise MissingDependency()
                for evidence_ref in decode(row["evidence_refs_json"], []):
                    evidence = db.execute(
                        "SELECT e.*,d.document_revision_id,d.license_status,d.title,d.published_at,d.observed_at,doc.canonical_url "
                        "FROM evidence e JOIN document_revisions d USING(document_revision_id) "
                        "JOIN documents doc ON doc.document_id=d.document_id WHERE e.evidence_id=?",
                        (evidence_ref["id"],),
                    ).fetchone()
                    if evidence is None:
                        raise MissingDependency()
                    if evidence["validity_status"] != "valid" or evidence["license_status"] != "allowed":
                        raise WithdrawnEvidence()
                    if evidence["evidence_status"] == "unknown":
                        raise InvalidPayload("unknown evidence cannot be published")
                    evidence_rows[evidence_ref["id"]] = dict(evidence)
            member_manifest = [
                {"kind": row["record_kind"], "id": row["record_id"], "revision": row["revision"], "content_hash": row["content_hash"], "dependencies": decode(row["dependency_refs_json"], [])}
                for row in sorted(rows, key=lambda item: (item["record_kind"], item["record_id"]))
            ]
            manifest = {
                "contract_version": CONTRACT_VERSION,
                "schema_id": "PublicBundleManifest",
                "schema_version": schema_version,
                "hash_algorithm": "sha256-canonical-json-utf8",
                "index_release_id": release_id,
                "parent_release_id": parent_id,
                "required_capabilities": sorted(set(required_capabilities)),
                "attribute_definitions": attribute_definitions or {},
                "coverage": coverage,
                "members": member_manifest,
                "evidence_ids": sorted(evidence_rows),
                "created_at": now_iso(),
            }
            body = self._release_body(rows, evidence_rows)
            digest = content_hash(body)
            manifest["content_hash"] = digest
            db.execute(
                "INSERT INTO index_releases VALUES(?,?,?,?,?,?,?,?,?,?)",
                (release_id, parent_id, schema_version, canonical_json(sorted(set(required_capabilities))), canonical_json(coverage), canonical_json(manifest), digest, "built", principal.actor_id, now_iso()),
            )
            for row in rows:
                db.execute(
                    "INSERT INTO release_members VALUES(?,?,?,?,?,?)",
                    (release_id, row["record_kind"], row["record_id"], row["revision"], row["content_hash"], row["dependency_refs_json"]),
                )
            self._audit(db, principal, "release_built", "release", release_id, details={"member_count": len(rows), "evidence_count": len(evidence_rows), "content_hash": digest})
        return {"index_release_id": release_id, "state": "built", "content_hash": digest, "member_count": len(rows)}

    def validate_release(self, principal: Principal, release_id: str, *, idempotency_key: str) -> dict[str, Any]:
        principal.require("publish")
        with self.database.transaction() as db:
            prior = self._publication_receipt(db, principal, idempotency_key, "validate", release_id)
            if prior is not None:
                return prior
            row = db.execute("SELECT * FROM index_releases WHERE index_release_id=?", (release_id,)).fetchone()
            if row is None:
                raise NotFound()
            if row["state"] not in {"built", "validated", "active"}:
                raise InvalidTransition()
            bundle = self._build_bundle(db, row)
            self._verify_bundle_hash(row, bundle)
            db.execute("UPDATE index_releases SET state=CASE WHEN state='built' THEN 'validated' ELSE state END WHERE index_release_id=?", (release_id,))
            result = {"index_release_id": release_id, "state": "validated", "content_hash": row["content_hash"]}
            self._record_publication(db, principal, release_id, "validate", idempotency_key, None, result)
            self._audit(db, principal, "release_validated", "release", release_id, details={"content_hash": row["content_hash"]})
            return result

    def activate_release(
        self,
        principal: Principal,
        release_id: str,
        *,
        expected_active_release_id: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        principal.require("publish")
        with self.database.transaction() as db:
            prior = self._publication_receipt(db, principal, idempotency_key, "activate", release_id)
            if prior is not None:
                return prior
            row = db.execute("SELECT * FROM index_releases WHERE index_release_id=?", (release_id,)).fetchone()
            if row is None or row["state"] not in {"validated", "active"}:
                raise InvalidTransition()
            active = db.execute("SELECT value FROM app_state WHERE key='active_release_id'").fetchone()
            active_id = None if active is None else active["value"]
            if active_id != expected_active_release_id:
                raise Conflict()
            self._check_release_not_disabled(db, release_id)
            if active_id and active_id != release_id:
                db.execute("UPDATE index_releases SET state='superseded' WHERE index_release_id=? AND state='active'", (active_id,))
            db.execute("UPDATE index_releases SET state='active' WHERE index_release_id=?", (release_id,))
            db.execute("INSERT INTO app_state(key,value) VALUES('active_release_id',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (release_id,))
            result = {"index_release_id": release_id, "state": "active", "previous_release_id": active_id}
            self._record_publication(db, principal, release_id, "activate", idempotency_key, expected_active_release_id, result)
            self._audit(db, principal, "release_activated", "release", release_id, details={"previous_release_id": active_id})
            return result

    def rollback_release(
        self,
        principal: Principal,
        target_release_id: str,
        *,
        expected_active_release_id: str | None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        principal.require("publish")
        with self.database.transaction() as db:
            prior = self._publication_receipt(db, principal, idempotency_key, "rollback", target_release_id)
            if prior is not None:
                return prior
            target = db.execute("SELECT * FROM index_releases WHERE index_release_id=?", (target_release_id,)).fetchone()
            if target is None or target["state"] not in {"superseded", "active"}:
                raise InvalidTransition()
            active = db.execute("SELECT value FROM app_state WHERE key='active_release_id'").fetchone()
            active_id = None if active is None else active["value"]
            if active_id != expected_active_release_id:
                raise Conflict()
            self._check_release_not_disabled(db, target_release_id)
            self._build_bundle(db, target)
            if active_id and active_id != target_release_id:
                db.execute("UPDATE index_releases SET state='superseded' WHERE index_release_id=? AND state='active'", (active_id,))
            db.execute("UPDATE index_releases SET state='active' WHERE index_release_id=?", (target_release_id,))
            db.execute("INSERT INTO app_state(key,value) VALUES('active_release_id',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (target_release_id,))
            result = {"index_release_id": target_release_id, "state": "active", "rollback_from": active_id}
            self._record_publication(db, principal, target_release_id, "rollback", idempotency_key, expected_active_release_id, result)
            self._audit(db, principal, "release_rolled_back", "release", target_release_id, details={"rollback_from": active_id})
            return result

    def disable_record(
        self, principal: Principal, *, kind: str, record_id: str, revision: int | None, reason: str
    ) -> None:
        principal.require("publish")
        if kind not in {"entity", "knowledge", "stage", "template", "variant", "troubleshooting", "resource", "evidence"}:
            raise InvalidPayload("invalid disabled reference")
        if not isinstance(reason, str) or not 1 <= len(reason) <= 1000:
            raise InvalidPayload("invalid disable reason")
        rev = -1 if revision is None else revision
        with self.database.transaction() as db:
            db.execute(
                "INSERT INTO disabled_refs VALUES(?,?,?,?,?,?) ON CONFLICT(record_kind,record_id,revision) DO UPDATE SET reason=excluded.reason,actor_id=excluded.actor_id,disabled_at=excluded.disabled_at",
                (kind, record_id, rev, reason, principal.actor_id, now_iso()),
            )
            if kind == "evidence":
                db.execute("UPDATE evidence SET validity_status='disabled' WHERE evidence_id=?", (record_id,))
            else:
                db.execute("UPDATE public_record_revisions SET state='disabled' WHERE record_kind=? AND record_id=? AND (?=-1 OR revision=?)", (kind, record_id, rev, rev))
            self._audit(db, principal, "record_disabled", kind, record_id, revision=revision)

    def get_release_bundle(self, release_id: str | None = None) -> dict[str, Any]:
        with self.database.reader() as db:
            if release_id is None:
                active = db.execute("SELECT value FROM app_state WHERE key='active_release_id'").fetchone()
                if active is None:
                    raise NotFound("no active public release")
                release_id = active["value"]
            row = db.execute("SELECT * FROM index_releases WHERE index_release_id=?", (release_id,)).fetchone()
            if row is None or row["state"] not in {"validated", "active", "superseded"}:
                raise NotFound("public release is unavailable")
            bundle = self._build_bundle(db, row)
            self._verify_bundle_hash(row, bundle)
            return bundle

    def get_complete_template(self, release_id: str, template_id: str) -> dict[str, Any]:
        bundle = self.get_release_bundle(release_id)
        templates = [item for item in bundle["templates"] if item["id"] == template_id]
        if not templates:
            raise NotFound()
        template = templates[0]
        dependencies = template["dependency_refs"]
        variants: list[dict[str, Any]] = []
        stages: list[dict[str, Any]] = []
        for ref in dependencies:
            collection = bundle["stages"] if ref["kind"] == "stage" else bundle["variants"]
            matches = [item for item in collection if item["id"] == ref["id"] and item["revision"] == ref["revision"]]
            if len(matches) != 1:
                raise MissingDependency()
            (stages if ref["kind"] == "stage" else variants).append(matches[0])
        evidence_refs = {ref["id"] for ref in template["evidence_refs"]}
        for variant in variants:
            evidence_refs.update(ref["id"] for ref in variant["evidence_refs"])
        evidence = [item for item in bundle["evidence"] if item["id"] in evidence_refs]
        if len(evidence) != len(evidence_refs):
            raise MissingDependency()
        return {
            "contract_version": CONTRACT_VERSION,
            "schema_id": "CompleteTemplate",
            "schema_version": bundle["schema_version"],
            "index_release_id": release_id,
            "template": template,
            "stages": stages,
            "variants": variants,
            "evidence": evidence,
            "manifest_hash": bundle["manifest"]["content_hash"],
        }

    def search_public(self, query: dict[str, Any]) -> dict[str, Any]:
        """Run local public retrieval, then report whether controlled search can run.

        No network search adapter is enabled until M0 verifies a source's permission,
        capabilities, and coverage. This method never forwards the question elsewhere.
        """
        normalized = validate_public_query(query)
        if normalized["query_kind"] != "public_question":
            raise InvalidPayload("public search requires a public question")
        existing: dict[str, Any]
        try:
            local_query = {**normalized, "query_kind": "search"}
            existing = self.search(local_query)
        except NotFound:
            existing = {"contract_version": CONTRACT_VERSION, "index_release_id": None, "results": [], "retrieval": {"method": "none"}}
        results = existing.get("results", [])
        needs_search = not results
        return {
            "contract_version": CONTRACT_VERSION,
            "index_release_id": existing.get("index_release_id"),
            "local_results": results,
            "temporary_evidence": [],
            "triggered": needs_search,
            "trigger_reason": "no_local_match" if needs_search else None,
            "provider_status": "not_configured",
            "message": "No authorized public search adapter is configured; no request was sent externally.",
            "candidate_queue": "not_created",
        }

    def search(self, query: dict[str, Any]) -> dict[str, Any]:
        normalized = validate_public_query(query)
        release_id = normalized.get("index_release_id")
        if normalized["query_kind"] == "release_discovery":
            with self.database.reader() as db:
                rows = db.execute(
                    "SELECT index_release_id,parent_release_id,schema_version,coverage_json,content_hash,state,created_at "
                    "FROM index_releases WHERE state IN ('active','superseded') ORDER BY created_at DESC"
                ).fetchall()
                return {"contract_version": CONTRACT_VERSION, "releases": [dict(row) | {"coverage": decode(row["coverage_json"], {})} for row in rows]}
        if release_id is None:
            with self.database.reader() as db:
                active = db.execute("SELECT value FROM app_state WHERE key='active_release_id'").fetchone()
                if active is None:
                    raise NotFound("no active public release")
                release_id = active["value"]
        bundle = self.get_release_bundle(release_id)
        if normalized["query_kind"] == "stage_templates":
            stage_id = normalized["scope"].get("stage_id")
            matched_templates = [
                item for item in bundle["templates"]
                if item.get("scope", {}).get("stage_id") == stage_id and _scope_matches(item.get("scope", {}), normalized["scope"])
            ]
            return {"contract_version": CONTRACT_VERSION, "index_release_id": release_id, "templates": matched_templates, "coverage": bundle["manifest"].get("coverage", {})}
        if normalized["query_kind"] == "entity":
            ids = set(normalized["public_entity_ids"])
            return {"contract_version": CONTRACT_VERSION, "index_release_id": release_id, "entities": [entity for entity in bundle["entities"] if entity["entity_id"] in ids]}
        terms = [term.casefold() for term in (normalized.get("public_question") or "").split() if term]
        if not terms:
            terms = [term.casefold() for term in (normalized.get("query_text") or "").split() if term]
        results: list[dict[str, Any]] = []
        for kind in ("knowledge", "stage", "template", "variant", "troubleshooting", "resource"):
            for record in bundle["records"][kind]:
                if not _scope_matches(record["scope"], normalized["scope"]):
                    continue
                if normalized["public_entity_ids"]:
                    referenced_ids = set(_collect_ids(record["payload"]))
                    if not referenced_ids.intersection(normalized["public_entity_ids"]):
                        continue
                haystack = canonical_json({"payload": record["payload"], "scope": record["scope"]}).casefold()
                if terms and not all(term in haystack for term in terms):
                    continue
                results.append({"kind": kind, **record})
        results.sort(key=lambda item: (item["kind"], item["id"]))
        return {"contract_version": CONTRACT_VERSION, "index_release_id": release_id, "results": results[: normalized["limit"]], "retrieval": {"method": "deterministic_keyword", "calibrated": False}}

    def create_update_run(
        self, principal: Principal, *, idempotency_key: str, source_id: str | None, public_scope: dict[str, Any]
    ) -> dict[str, Any]:
        principal.require("update")
        if not isinstance(public_scope, dict):
            raise InvalidPayload("invalid update scope")
        validate_public_query({"query_kind": "search", "scope": public_scope})
        request_hash = content_hash({"source_id": source_id, "public_scope": public_scope})
        timestamp = now_iso()
        with self.database.transaction() as db:
            existing = db.execute("SELECT * FROM update_runs WHERE request_actor=? AND request_key=?", (principal.actor_id, idempotency_key)).fetchone()
            if existing:
                if existing["request_hash"] != request_hash:
                    raise Conflict()
                return {"run_id": existing["run_id"], "status": existing["status"], "idempotent_replay": True}
            if source_id is not None:
                source = db.execute("SELECT enabled FROM sources WHERE source_id=?", (source_id,)).fetchone()
                policy = db.execute("SELECT permission_status FROM source_policy_revisions WHERE source_id=? ORDER BY revision DESC LIMIT 1", (source_id,)).fetchone()
                if source is None or not source["enabled"] or policy is None or policy["permission_status"] != "allowed":
                    raise PermissionDenied()
            run_id = _new_id("run")
            db.execute("INSERT INTO update_runs VALUES(?,?,?,?,?,?,?,?,?)", (run_id, idempotency_key, principal.actor_id, request_hash, "queued", source_id, canonical_json(public_scope), timestamp, timestamp))
            task_ids: dict[str, str] = {}
            for stage in UPDATE_STAGES:
                task_id = _new_id("task")
                task_ids[stage] = task_id
                db.execute("INSERT INTO update_tasks VALUES(?,?,?,?,?,?,?,?,?,?,?)", (task_id, run_id, stage, "pending", None, None, "{}", request_hash, None, 0, timestamp))
            self._audit(db, principal, "update_run_created", "run", run_id, details={"source_id": source_id, "task_id": task_id})
            return {"run_id": run_id, "task_id": task_ids["discover"], "task_ids": task_ids, "status": "queued", "idempotent_replay": False}

    def claim_update_task(self, principal: Principal, task_id: str, *, lease_seconds: int = 60) -> dict[str, Any]:
        principal.require("update")
        if not 1 <= lease_seconds <= 3600:
            raise InvalidPayload("invalid lease duration")
        timestamp = datetime.now(UTC)
        with self.database.transaction() as db:
            task = db.execute("SELECT * FROM update_tasks WHERE task_id=?", (task_id,)).fetchone()
            if task is None:
                raise NotFound()
            expires = None if task["lease_expires_at"] is None else datetime.fromisoformat(task["lease_expires_at"])
            if task["state"] == "completed":
                return {"task_id": task_id, "state": "completed", "checkpoint": decode(task["checkpoint_json"], {}), "idempotent_replay": True}
            if task["state"] in {"cancelled", "waiting_review"}:
                raise InvalidTransition()
            if task["state"] not in {"pending", "failed", "running"}:
                raise InvalidTransition()
            stage_position = UPDATE_STAGES.index(task["stage"]) if task["stage"] in UPDATE_STAGES else -1
            if stage_position > 0:
                earlier = db.execute(
                    "SELECT state FROM update_tasks WHERE run_id=? AND stage IN (%s)" % ",".join("?" for _ in UPDATE_STAGES[:stage_position]),
                    (task["run_id"], *UPDATE_STAGES[:stage_position]),
                ).fetchall()
                if len(earlier) != stage_position or any(row["state"] != "completed" for row in earlier):
                    raise InvalidTransition("previous update stages are not complete")
            if task["state"] == "running" and expires and expires > timestamp and task["lease_owner"] != principal.actor_id:
                raise Conflict("task has an active lease")
            lease_expires = (timestamp + timedelta(seconds=lease_seconds)).isoformat(timespec="seconds")
            db.execute("UPDATE update_tasks SET state='running',lease_owner=?,lease_expires_at=?,attempts=attempts+1,updated_at=? WHERE task_id=?", (principal.actor_id, lease_expires, timestamp.isoformat(timespec="seconds"), task_id))
            db.execute("UPDATE update_runs SET status='running',updated_at=? WHERE run_id=? AND status IN ('queued','running','failed')", (timestamp.isoformat(timespec="seconds"), task["run_id"]))
            self._audit(db, principal, "task_claimed", "task", task_id)
            return {"task_id": task_id, "state": "running", "lease_expires_at": lease_expires, "checkpoint": decode(task["checkpoint_json"], {}), "attempt": task["attempts"] + 1}

    def retry_update_task(self, principal: Principal, task_id: str, *, idempotency_key: str) -> dict[str, Any]:
        principal.require("update")
        with self.database.transaction() as db:
            prior = self._command_receipt(db, principal, idempotency_key, "retry_task", {"task_id": task_id})
            if prior is not None:
                return prior
            task = db.execute("SELECT * FROM update_tasks WHERE task_id=?", (task_id,)).fetchone()
            if task is None:
                raise NotFound()
            if task["state"] != "failed":
                raise InvalidTransition()
            timestamp = now_iso()
            db.execute("UPDATE update_tasks SET state='pending',lease_owner=NULL,lease_expires_at=NULL,updated_at=? WHERE task_id=?", (timestamp, task_id))
            db.execute("UPDATE update_runs SET status='queued',updated_at=? WHERE run_id=?", (timestamp, task["run_id"]))
            result = {"task_id": task_id, "state": "pending", "checkpoint_preserved": True}
            self._store_command_receipt(db, principal, idempotency_key, "retry_task", {"task_id": task_id}, result)
            self._audit(db, principal, "task_retry_queued", "task", task_id, details={"checkpoint_preserved": True})
            return result

    def cancel_update_task(self, principal: Principal, task_id: str, *, idempotency_key: str) -> dict[str, Any]:
        principal.require("update")
        with self.database.transaction() as db:
            prior = self._command_receipt(db, principal, idempotency_key, "cancel_task", {"task_id": task_id})
            if prior is not None:
                return prior
            task = db.execute("SELECT * FROM update_tasks WHERE task_id=?", (task_id,)).fetchone()
            if task is None:
                raise NotFound()
            if task["state"] == "completed":
                raise InvalidTransition()
            timestamp = now_iso()
            db.execute("UPDATE update_tasks SET state='cancelled',lease_owner=NULL,lease_expires_at=NULL,updated_at=? WHERE run_id=? AND state IN ('pending','running','failed','waiting_review')", (timestamp, task["run_id"]))
            db.execute("UPDATE update_runs SET status='cancelled',updated_at=? WHERE run_id=?", (timestamp, task["run_id"]))
            result = {"task_id": task_id, "run_id": task["run_id"], "state": "cancelled"}
            self._store_command_receipt(db, principal, idempotency_key, "cancel_task", {"task_id": task_id}, result)
            self._audit(db, principal, "task_cancelled", "task", task_id)
            return result

    def resume_after_review(self, principal: Principal, task_id: str, *, idempotency_key: str) -> dict[str, Any]:
        principal.require("update")
        with self.database.transaction() as db:
            prior = self._command_receipt(db, principal, idempotency_key, "resume_after_review", {"task_id": task_id})
            if prior is not None:
                return prior
            task = db.execute("SELECT * FROM update_tasks WHERE task_id=?", (task_id,)).fetchone()
            if task is None:
                raise NotFound()
            if task["state"] != "waiting_review":
                raise InvalidTransition()
            checkpoint = decode(task["checkpoint_json"], {})
            refs = checkpoint.get("review_refs", [])
            if not refs:
                raise InvalidTransition()
            decisions: list[str] = []
            for ref in refs:
                row = db.execute(
                    "SELECT state,content_hash FROM public_record_revisions WHERE record_kind=? AND record_id=? AND revision=?",
                    (ref["kind"], ref["id"], ref["revision"]),
                ).fetchone()
                if row is None or row["content_hash"] != ref["content_hash"] or row["state"] not in {"approved", "rejected"}:
                    raise Conflict("referenced candidates still need a matching human review")
                decisions.append(row["state"])
            timestamp = now_iso()
            db.execute("UPDATE update_tasks SET state='pending',lease_owner=NULL,lease_expires_at=NULL,updated_at=? WHERE task_id=?", (timestamp, task_id))
            db.execute("UPDATE update_runs SET status='queued',updated_at=? WHERE run_id=?", (timestamp, task["run_id"]))
            result = {"task_id": task_id, "state": "pending", "review_decisions": decisions}
            self._store_command_receipt(db, principal, idempotency_key, "resume_after_review", {"task_id": task_id}, result)
            self._audit(db, principal, "task_resumed_after_review", "task", task_id, details={"decisions": decisions})
            return result

    def checkpoint_update_task(
        self, principal: Principal, task_id: str, *, checkpoint: dict[str, Any], output_hash: str | None, state: str = "running"
    ) -> dict[str, Any]:
        principal.require("update")
        if state not in {"running", "waiting_review", "completed", "failed", "cancelled"} or not isinstance(checkpoint, dict):
            raise InvalidPayload("invalid checkpoint")
        safe_checkpoint = {key: checkpoint[key] for key in ("step", "cursor", "counts", "last_error_code", "review_refs") if key in checkpoint}
        safe_checkpoint.setdefault("counts", {})
        if any(
            value is not None
            and not isinstance(value, str | int | dict | list)
            for key, value in safe_checkpoint.items()
            if key != "review_refs"
        ):
            raise InvalidPayload("invalid checkpoint")
        if state == "waiting_review":
            refs = safe_checkpoint.get("review_refs")
            if not isinstance(refs, list) or not refs:
                raise InvalidPayload("review checkpoint must name the public candidate revisions awaiting review")
            for ref in refs:
                if not isinstance(ref, dict) or set(ref) != {"kind", "id", "revision", "content_hash"} or not all(isinstance(ref.get(key), str) for key in ("kind", "id", "content_hash")) or not isinstance(ref.get("revision"), int):
                    raise InvalidPayload("invalid review checkpoint reference")
        timestamp = now_iso()
        with self.database.transaction() as db:
            task = db.execute("SELECT * FROM update_tasks WHERE task_id=?", (task_id,)).fetchone()
            if task is None:
                raise NotFound()
            if task["lease_owner"] != principal.actor_id and task["state"] != "completed":
                raise PermissionDenied()
            if task["state"] == "completed":
                existing = decode(task["checkpoint_json"], {})
                if existing == safe_checkpoint and task["output_hash"] == output_hash:
                    return {"task_id": task_id, "state": "completed", "idempotent_replay": True}
                raise InvalidTransition()
            db.execute("UPDATE update_tasks SET state=?,checkpoint_json=?,output_hash=?,lease_owner=CASE WHEN ? IN ('completed','failed','cancelled','waiting_review') THEN NULL ELSE lease_owner END,lease_expires_at=CASE WHEN ? IN ('completed','failed','cancelled','waiting_review') THEN NULL ELSE lease_expires_at END,updated_at=? WHERE task_id=?", (state, canonical_json(safe_checkpoint), output_hash, state, state, timestamp, task_id))
            if state == "waiting_review":
                run_state = "waiting_review"
            elif state in {"failed", "cancelled"}:
                run_state = state
            else:
                pending = db.execute("SELECT 1 FROM update_tasks WHERE run_id=? AND state!='completed' LIMIT 1", (task["run_id"],)).fetchone()
                run_state = "running" if pending else "completed"
            db.execute("UPDATE update_runs SET status=?,updated_at=? WHERE run_id=?", (run_state, timestamp, task["run_id"]))
            self._audit(db, principal, "task_checkpointed", "task", task_id, details={"state": state, "output_hash": output_hash})
            return {"task_id": task_id, "state": state, "checkpoint": safe_checkpoint, "output_hash": output_hash}

    def update_run_status(self, run_id: str) -> dict[str, Any]:
        with self.database.reader() as db:
            run = db.execute("SELECT run_id,status,public_scope_json,created_at,updated_at FROM update_runs WHERE run_id=?", (run_id,)).fetchone()
            if run is None:
                raise NotFound()
            tasks = db.execute("SELECT task_id,stage,state,checkpoint_json,attempts,updated_at FROM update_tasks WHERE run_id=? ORDER BY stage", (run_id,)).fetchall()
            return {"run_id": run["run_id"], "status": run["status"], "public_scope": decode(run["public_scope_json"], {}), "created_at": run["created_at"], "updated_at": run["updated_at"], "tasks": [{"task_id": task["task_id"], "stage": task["stage"], "state": task["state"], "checkpoint": decode(task["checkpoint_json"], {}), "attempts": task["attempts"], "updated_at": task["updated_at"]} for task in tasks]}

    def _build_bundle(self, db: Any, release_row: Any) -> dict[str, Any]:
        if release_row["state"] in {"withdrawn"}:
            raise WithdrawnEvidence()
        members = db.execute(
            "SELECT rm.*,pr.state,pr.scope_json,pr.payload_json,pr.evidence_refs_json,pr.dependency_refs_json "
            "FROM release_members rm JOIN public_record_revisions pr "
            "ON pr.record_kind=rm.record_kind AND pr.record_id=rm.record_id AND pr.revision=rm.revision "
            "WHERE rm.index_release_id=? ORDER BY rm.record_kind,rm.record_id",
            (release_row["index_release_id"],),
        ).fetchall()
        records: dict[str, list[dict[str, Any]]] = {kind: [] for kind in ("entity", "knowledge", "stage", "template", "variant", "troubleshooting", "resource")}
        evidence_ids: set[str] = set()
        entity_rows: list[dict[str, Any]] = []
        for row in members:
            if row["state"] in {"withdrawn", "disabled", "rejected", "candidate"}:
                raise WithdrawnEvidence()
            if self._is_disabled(db, row["record_kind"], row["record_id"], row["revision"]):
                raise WithdrawnEvidence()
            evidence_ids.update(ref["id"] for ref in decode(row["evidence_refs_json"], []))
            records[row["record_kind"]].append({
                "id": row["record_id"], "revision": row["revision"], "scope": decode(row["scope_json"], {}),
                "payload": decode(row["payload_json"], {}), "content_hash": row["content_hash"],
                "evidence_refs": decode(row["evidence_refs_json"], []), "dependency_refs": decode(row["dependency_refs_json"], []),
            })
        evidence_payload: list[dict[str, Any]] = []
        for evidence_id in sorted(evidence_ids):
            row = db.execute(
                "SELECT e.*,d.title,doc.canonical_url,d.published_at,d.observed_at,d.license_status "
                "FROM evidence e JOIN document_revisions d USING(document_revision_id) "
                "JOIN documents doc ON doc.document_id=d.document_id WHERE e.evidence_id=?",
                (evidence_id,),
            ).fetchone()
            if row is None:
                raise MissingDependency()
            if row["validity_status"] != "valid" or row["license_status"] != "allowed" or self._is_disabled(db, "evidence", evidence_id, None):
                raise WithdrawnEvidence()
            evidence_payload.append({
                "id": evidence_id, "title": row["title"], "url": row["canonical_url"], "excerpt": row["excerpt"],
                "locator": decode(row["locator_json"], {}), "relation": row["relation"], "scope": decode(row["scope_json"], {}),
                "evidence_status": row["evidence_status"], "content_hash": row["content_hash"],
                "published_at": row["published_at"], "observed_at": row["observed_at"], "license_status": row["license_status"],
            })
        entity_rows = [
            {"entity_id": item["id"], "revision": item["revision"], "entity_type": item["payload"]["entity_type"], "canonical_name": item["payload"]["canonical_name"], "game_version": item["scope"].get("game_version"), "environment": item["scope"]["environment"], "release_status": item["scope"]["release_status"], "payload": item["payload"], "content_hash": item["content_hash"], "evidence_refs": item["evidence_refs"]}
            for item in records["entity"]
        ]
        manifest = decode(release_row["manifest_json"], {})
        bundle = {
            "contract_version": CONTRACT_VERSION,
            "schema_id": "PublicBundle",
            "schema_version": release_row["schema_version"],
            "manifest": manifest,
            "entities": entity_rows,
            "stages": records["stage"],
            "templates": records["template"],
            "variants": records["variant"],
            "knowledge": records["knowledge"],
            "troubleshooting": records["troubleshooting"],
            "resources": records["resource"],
            "records": records,
            "evidence": evidence_payload,
        }
        return bundle

    def _release_body(self, rows: list[dict[str, Any]], evidence_rows: dict[str, dict[str, Any]]) -> dict[str, Any]:
        records = [
            {"kind": row["record_kind"], "id": row["record_id"], "revision": row["revision"], "scope": decode(row["scope_json"], {}), "payload": decode(row["payload_json"], {}), "content_hash": row["content_hash"], "evidence_refs": decode(row["evidence_refs_json"], []), "dependency_refs": decode(row["dependency_refs_json"], [])}
            for row in sorted(rows, key=lambda item: (item["record_kind"], item["record_id"]))
        ]
        evidence = []
        for evidence_id, row in sorted(evidence_rows.items()):
            evidence.append({"id": evidence_id, "title": row["title"], "url": row["canonical_url"], "excerpt": row["excerpt"], "locator": decode(row["locator_json"], {}), "relation": row["relation"], "scope": decode(row["scope_json"], {}), "evidence_status": row["evidence_status"], "content_hash": row["content_hash"], "license_status": row["license_status"]})
        return {"records": records, "evidence": evidence}

    def _verify_bundle_hash(self, release_row: Any, bundle: dict[str, Any]) -> None:
        if verify_public_bundle(bundle) != release_row["content_hash"] or bundle["manifest"].get("content_hash") != release_row["content_hash"]:
            raise IntegrityFailure()

    def _check_release_not_disabled(self, db: Any, release_id: str) -> None:
        rows = db.execute("SELECT record_kind,record_id,revision FROM release_members WHERE index_release_id=?", (release_id,)).fetchall()
        for row in rows:
            if self._is_disabled(db, row["record_kind"], row["record_id"], row["revision"]):
                raise WithdrawnEvidence()
            revision = db.execute("SELECT evidence_refs_json,state FROM public_record_revisions WHERE record_kind=? AND record_id=? AND revision=?", (row["record_kind"], row["record_id"], row["revision"])).fetchone()
            if revision is None or revision["state"] in {"withdrawn", "disabled", "rejected"}:
                raise WithdrawnEvidence()
            for ref in decode(revision["evidence_refs_json"], []):
                evidence = db.execute("SELECT validity_status FROM evidence WHERE evidence_id=?", (ref["id"],)).fetchone()
                if evidence is None or evidence["validity_status"] != "valid" or self._is_disabled(db, "evidence", ref["id"], None):
                    raise WithdrawnEvidence()

    def _is_disabled(self, db: Any, kind: str, record_id: str, revision: int | None) -> bool:
        exact_revision = -1 if revision is None else revision
        return db.execute(
            "SELECT 1 FROM disabled_refs WHERE record_kind=? AND record_id=? AND revision IN (-1,?) LIMIT 1",
            (kind, record_id, exact_revision),
        ).fetchone() is not None

    def _publication_receipt(self, db: Any, principal: Principal, key: str, operation: str, release_id: str) -> dict[str, Any] | None:
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise InvalidPayload("invalid idempotency key")
        row = db.execute("SELECT * FROM publication_events WHERE actor_id=? AND idempotency_key=?", (principal.actor_id, key)).fetchone()
        if row is None:
            return None
        if row["operation_kind"] != operation or row["index_release_id"] != release_id:
            raise Conflict()
        return decode(row["result_json"], {})

    def _command_receipt(self, db: Any, principal: Principal, key: str, command: str, request: dict[str, Any]) -> dict[str, Any] | None:
        if not isinstance(key, str) or not 1 <= len(key) <= 200:
            raise InvalidPayload("invalid idempotency key")
        request_hash = content_hash(request)
        row = db.execute("SELECT * FROM command_receipts WHERE actor_id=? AND idempotency_key=?", (principal.actor_id, key)).fetchone()
        if row is None:
            return None
        if row["command_kind"] != command or row["request_hash"] != request_hash:
            raise Conflict()
        return decode(row["result_json"], {})

    def _store_command_receipt(self, db: Any, principal: Principal, key: str, command: str, request: dict[str, Any], result: dict[str, Any]) -> None:
        db.execute("INSERT INTO command_receipts VALUES(?,?,?,?,?,?)", (principal.actor_id, key, command, content_hash(request), canonical_json(result), now_iso()))

    def _record_publication(self, db: Any, principal: Principal, release_id: str, operation: str, key: str, expected: str | None, result: dict[str, Any]) -> None:
        db.execute("INSERT INTO publication_events VALUES(?,?,?,?,?,?,?,?)", (_new_id("pub"), release_id, operation, principal.actor_id, key, expected, canonical_json(result), now_iso()))

    def _audit(self, db: Any, principal: Principal, action: str, kind: str, target_id: str, *, revision: int | None = None, result: str = "success", details: dict[str, Any] | None = None) -> None:
        db.execute("INSERT INTO audit_events VALUES(?,?,?,?,?,?,?,?,?)", (_new_id("audit"), principal.actor_id, action, kind, target_id, revision, result, canonical_json(details or {}), now_iso()))


def _scope_matches(record_scope: dict[str, Any], query_scope: dict[str, Any]) -> bool:
    for field in ("game_version", "environment", "release_status", "mode_id", "cycle_id", "stage_id"):
        requested = query_scope.get(field)
        if requested is not None and record_scope.get(field) != requested:
            return False
    # Unknown/unreleased data never leaks into a default live/released query.
    if query_scope.get("environment") is None and record_scope.get("environment") not in {None, "live"}:
        return False
    if query_scope.get("release_status") is None and record_scope.get("release_status") not in {None, "released"}:
        return False
    return True


def _collect_ids(value: Any) -> set[str]:
    result: set[str] = set()
    if isinstance(value, dict):
        for key, item in value.items():
            if key.endswith("_id") and isinstance(item, str):
                result.add(item)
            result.update(_collect_ids(item))
    elif isinstance(value, list):
        for item in value:
            result.update(_collect_ids(item))
    return result


def release_members_by_kind(rows: list[Any], kind: str) -> list[dict[str, Any]]:
    return [{"id": row["record_id"], "revision": row["revision"]} for row in rows if row["record_kind"] == kind]
