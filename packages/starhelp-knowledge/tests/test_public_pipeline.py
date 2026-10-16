from __future__ import annotations

import json
import io
import copy
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

from starhelp_knowledge.database import KnowledgeDatabase
from starhelp_knowledge.cli import main as cli_main
from starhelp_knowledge.bundle import verify_public_bundle
from starhelp_knowledge.errors import Conflict, IntegrityFailure, InvalidPayload, InvalidTransition, PermissionDenied, SourceBlocked, WithdrawnEvidence
from starhelp_knowledge.http import KnowledgeApplication
from starhelp_knowledge.policy import Principal, TokenAuthenticator, validate_public_query
from starhelp_knowledge.records import validate_public_record
from starhelp_knowledge.service import KnowledgeService
from starhelp_knowledge.sources import VerifiedJSONSourceAdapter


UPDATER = Principal("fixture:curator", frozenset({"updater"}))
REVIEWER = Principal("fixture:reviewer", frozenset({"reviewer"}))
PUBLISHER = Principal("fixture:publisher", frozenset({"publisher"}))
ADMIN = Principal("fixture:source-admin", frozenset({"admin"}))


class PublicPipelineTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.service = KnowledgeService(KnowledgeDatabase(Path(self.tempdir.name) / "knowledge.sqlite3"))
        self.evidence_ref = self._make_synthetic_evidence()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _make_synthetic_evidence(self) -> list[dict[str, object]]:
        self.service.add_source(UPDATER, source_id="fixture:source", name="Synthetic fixture", platform="test", source_role="reference")
        self.service.set_source_policy(
            ADMIN,
            source_id="fixture:source",
            permission_status="allowed",
            terms_reference="https://example.test/terms",
            allowed_domains=["example.test"],
            allowed_paths=["/public"],
            rate_policy={"mode": "fixture"},
            storage_policy={"mode": "minimal_excerpt", "max_excerpt_chars": 1000},
            checked_at="2026-10-15T00:00:00Z",
        )
        evidence_id = self.service.add_public_evidence(
            UPDATER,
            source_id="fixture:source",
            external_content_id="fixture:doc:1",
            canonical_url="https://example.test/public/fixture",
            content_kind="fixture",
            title="Synthetic public evidence",
            author_id=None,
            excerpt="Synthetic fixture, not real game data.",
            locator={"kind": "fixture", "value": "1"},
            license_status="allowed",
            published_at=None,
            relation="supports",
            evidence_status="confirmed",
            scope={"environment": "live", "game_version": "fixture:game:v1"},
        )
        return [{"id": evidence_id, "revision": 1}]

    def approve(self, kind: str, record_id: str, candidate: dict[str, object]) -> None:
        self.service.review_candidate(
            REVIEWER,
            kind=kind,
            record_id=record_id,
            revision=candidate["revision"],
            expected_content_hash=candidate["content_hash"],
            decision="approved",
            note="Synthetic test review only.",
        )

    def build_synthetic_release(self) -> dict[str, object]:
        scope = {
            "game_version": "fixture:game:v1",
            "environment": "live",
            "release_status": "released",
            "mode_id": "fixture:mode:memory",
            "cycle_id": "fixture:cycle:1",
            "stage_id": "fixture:stage:1",
        }
        entity_refs = []
        for index, name in enumerate(("Unit A", "Unit B", "Unit C", "Unit D"), start=1):
            entity_id = f"fixture:entity:{index}"
            candidate = self.service.create_candidate(
                UPDATER,
                kind="entity",
                record_id=entity_id,
                scope=scope,
                payload={"entity_type": "character", "canonical_name": name},
                evidence_refs=self.evidence_ref,
                dependency_refs=[],
            )
            self.approve("entity", entity_id, candidate)
            entity_refs.append({"kind": "entity", "id": entity_id, "revision": candidate["revision"]})
        stage_candidate = self.service.create_candidate(
            UPDATER,
            kind="stage",
            record_id="fixture:stage:1",
            scope=scope,
            payload={"partitions": ["upper", "lower"], "coverage_status": "synthetic"},
            evidence_refs=self.evidence_ref,
            dependency_refs=[],
        )
        self.approve("stage", "fixture:stage:1", stage_candidate)
        variant_candidate = self.service.create_candidate(
            UPDATER,
            kind="variant",
            record_id="fixture:variant:1",
            scope=scope,
            payload={
                "team": [
                    {"slot_id": f"fixture:slot:{i}", "entity_id": entity_ref["id"], "partition": "upper" if i < 3 else "lower"}
                    for i, entity_ref in enumerate(entity_refs, start=1)
                ],
                "conditions": [{
                    "condition_id": "fixture:condition:speed",
                    "subject": {"kind": "team_slot", "slot_id": "fixture:slot:1"},
                    "attribute": "fixture:attribute:speed",
                    "operator": "gte",
                    "value": 100,
                    "unit": "fixture:flat",
                    "measurement_context": {"phase": "pre_battle", "assumptions": []},
                    "requirement": "hard",
                    "evidence_status": "confirmed",
                    "evidence_refs": self.evidence_ref,
                }],
                "steps": [{"order": 1, "text": "Synthetic step."}],
            },
            evidence_refs=self.evidence_ref,
            dependency_refs=entity_refs,
        )
        self.approve("variant", "fixture:variant:1", variant_candidate)
        template_candidate = self.service.create_candidate(
            UPDATER,
            kind="template",
            record_id="fixture:template:1",
            scope=scope,
            payload={"title": "Synthetic full template", "status": "synthetic", "primary_variant_id": "fixture:variant:1", "alternate_variant_ids": []},
            evidence_refs=self.evidence_ref,
            dependency_refs=[
                {"kind": "stage", "id": "fixture:stage:1", "revision": stage_candidate["revision"]},
                {"kind": "variant", "id": "fixture:variant:1", "revision": variant_candidate["revision"]},
            ],
        )
        self.approve("template", "fixture:template:1", template_candidate)
        refs = [
            {"kind": "entity", "id": f"fixture:entity:{index}", "revision": 1}
            for index in range(1, 5)
        ]
        refs.extend(
            [
                {"kind": "stage", "id": "fixture:stage:1", "revision": stage_candidate["revision"]},
                {"kind": "variant", "id": "fixture:variant:1", "revision": variant_candidate["revision"]},
                {"kind": "template", "id": "fixture:template:1", "revision": template_candidate["revision"]},
            ]
        )
        return self.service.build_release(
            PUBLISHER,
            members=refs,
            coverage={"status": "synthetic", "reason": "fixture-only"},
            required_capabilities=["fixture:complete-variant:v1"],
        )

    def test_public_query_allowlist_does_not_echo_private_field_name(self) -> None:
        with self.assertRaises(InvalidPayload) as caught:
            validate_public_query({"query_kind": "search", "owned_character_ids": ["secret"]})
        self.assertNotIn("owned_character_ids", str(caught.exception))

    def test_complete_variant_conditions_only_accept_finite_operators(self) -> None:
        with self.assertRaises(InvalidPayload):
            validate_public_record(
                "variant",
                "fixture:variant:bad",
                {"game_version": "fixture:v", "mode_id": "fixture:m", "cycle_id": "fixture:c", "stage_id": "fixture:s"},
                {
                    "team": [{"slot_id": "fixture:slot:1", "entity_id": "fixture:entity:1"}],
                    "conditions": [{
                        "condition_id": "fixture:condition:bad",
                        "subject": {"kind": "team_slot", "slot_id": "fixture:slot:1"},
                        "attribute": "fixture:attribute:value",
                        "operator": "python_eval",
                        "value": "1 + 1",
                        "unit": "fixture:unit",
                        "measurement_context": {"phase": "pre_battle", "assumptions": []},
                        "requirement": "hard",
                        "evidence_status": "confirmed",
                        "evidence_refs": [{"id": "fixture:evidence:1", "revision": 1}],
                    }],
                    "steps": [{"order": 1, "text": "synthetic"}],
                },
                [{"id": "fixture:evidence:1", "revision": 1}],
                [{"kind": "entity", "id": "fixture:entity:1", "revision": 1}],
            )

    def test_wsgI_rejects_private_query_extensions_without_echo(self) -> None:
        app = KnowledgeApplication(self.service, TokenAuthenticator())
        payload = {"query_kind": "search", "owned_character_ids": ["private-value"]}
        body = json.dumps(payload).encode("utf-8")
        environ = {
            "REQUEST_METHOD": "POST",
            "PATH_INFO": "/v1/query",
            "QUERY_STRING": "",
            "CONTENT_LENGTH": str(len(body)),
            "wsgi.input": io.BytesIO(body),
        }
        response: dict[str, object] = {}
        def start_response(status: str, headers: list[tuple[str, str]]) -> None:
            response["status"] = status
        result = b"".join(app(environ, start_response)).decode("utf-8")
        self.assertTrue(str(response["status"]).startswith("400"))
        self.assertNotIn("private-value", result)
        self.assertNotIn("owned_character_ids", result)

    def test_source_allow_policy_requires_admin_and_domain_and_path(self) -> None:
        self.service.add_source(UPDATER, source_id="fixture:blocked-source", name="Blocked", platform="test", source_role="guide")
        with self.assertRaises(PermissionDenied):
            self.service.set_source_policy(
                UPDATER,
                source_id="fixture:blocked-source",
                permission_status="allowed",
                terms_reference="https://example.test/terms",
                allowed_domains=["example.test"],
                allowed_paths=["/public"],
                rate_policy={},
                storage_policy={"mode": "minimal_excerpt"},
                checked_at="2026-10-15T00:00:00Z",
            )
        self.service.set_source_policy(
            ADMIN,
            source_id="fixture:blocked-source",
            permission_status="allowed",
            terms_reference="https://example.test/terms",
            allowed_domains=["example.test"],
            allowed_paths=["/public"],
            rate_policy={},
            storage_policy={"mode": "minimal_excerpt"},
            checked_at="2026-10-15T00:00:00Z",
        )
        with self.assertRaises(PermissionDenied):
            self.service.add_public_evidence(
                UPDATER,
                source_id="fixture:blocked-source",
                external_content_id="fixture:other",
                canonical_url="https://example.test/private/content",
                content_kind="fixture",
                title="Synthetic",
                author_id=None,
                excerpt=None,
                locator={},
                license_status="allowed",
                published_at=None,
                relation="supports",
                evidence_status="confirmed",
                scope={},
            )

    def test_roles_are_separate_and_tokens_are_hashed(self) -> None:
        reader = Principal("fixture:reader", frozenset({"reader"}))
        with self.assertRaises(PermissionDenied):
            reader.require("review")
        with self.assertRaises(PermissionDenied):
            reader.require("publish")
        auth = TokenAuthenticator({"invited": {"token_sha256": "a" * 64, "roles": ["reader"]}})
        self.assertIsNone(auth.authenticate("not-the-token"))

    def test_create_token_can_provision_a_least_privilege_multi_role_maintainer(self) -> None:
        auth_path = Path(self.tempdir.name) / "auth.json"
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = cli_main([
                "create-token",
                "--auth-config", str(auth_path),
                "--actor-id", "fixture:maintainer-token",
                "--role", "updater",
                "--role", "reviewer",
            ])
        self.assertEqual(exit_code, 0)
        output = json.loads(stdout.getvalue())
        stored_actor = json.loads(auth_path.read_text(encoding="utf-8"))["actors"]["fixture:maintainer-token"]
        principal = TokenAuthenticator({"fixture:maintainer-token": stored_actor}).authenticate(output["token"])
        self.assertIsNotNone(principal)
        self.assertEqual(principal.roles, frozenset({"updater", "reviewer"}))
        self.assertEqual(output["roles"], ["updater", "reviewer"])

    def test_explicit_review_publication_and_release_scoped_complete_fetch(self) -> None:
        release = self.build_synthetic_release()
        validated = self.service.validate_release(PUBLISHER, release["index_release_id"], idempotency_key="validate-1")
        self.assertEqual(validated["state"], "validated")
        activated = self.service.activate_release(
            PUBLISHER, release["index_release_id"], expected_active_release_id=None, idempotency_key="activate-1"
        )
        self.assertEqual(activated["state"], "active")
        bundle = self.service.get_release_bundle()
        self.assertEqual(bundle["manifest"]["index_release_id"], release["index_release_id"])
        self.assertEqual(verify_public_bundle(bundle), bundle["manifest"]["content_hash"])
        modified = copy.deepcopy(bundle)
        modified["templates"][0]["payload"]["title"] = "tampered"
        with self.assertRaises(IntegrityFailure):
            verify_public_bundle(modified)
        self.assertEqual(len(bundle["templates"]), 1)
        full = self.service.get_complete_template(release["index_release_id"], "fixture:template:1")
        self.assertEqual(len(full["variants"]), 1)
        self.assertEqual(len(full["stages"]), 1)
        search = self.service.search({"query_kind": "stage_templates", "scope": {"stage_id": "fixture:stage:1"}})
        self.assertEqual(len(search["templates"]), 1)
        no_match = self.service.search({"query_kind": "stage_templates", "scope": {"stage_id": "fixture:stage:no-match"}})
        self.assertEqual(no_match["templates"], [])
        self.assertEqual(no_match["coverage"]["status"], "synthetic")
        self.assertEqual(self.service.validate_release(PUBLISHER, release["index_release_id"], idempotency_key="validate-1"), validated)

    def test_verified_transport_requires_matching_permission_and_capability(self) -> None:
        policy = {
            "source_id": "fixture:source",
            "permission_status": "allowed",
            "allowed_domains": ["example.test"],
            "allowed_paths": ["/public"],
            "rate_policy": {"min_interval_seconds": 0},
        }
        snapshot = {"source_id": "fixture:source", "adapter_version": "adapter-1", "status": "verified"}
        adapter = VerifiedJSONSourceAdapter(
            source_id="fixture:source",
            adapter_version="adapter-1",
            endpoint="https://example.test/public/index.json",
            source_policy=policy,
            capability_snapshot=snapshot,
        )
        self.assertEqual(adapter.capabilities().status, "verified")
        with self.assertRaises(SourceBlocked):
            VerifiedJSONSourceAdapter(
                source_id="fixture:other",
                adapter_version="adapter-1",
                endpoint="https://example.test/public/index.json",
                source_policy=policy,
                capability_snapshot=snapshot,
            )
        with self.assertRaises(SourceBlocked):
            VerifiedJSONSourceAdapter(
                source_id="fixture:source",
                adapter_version="adapter-1",
                endpoint="https://example.test.evil.invalid/public/index.json",
                source_policy=policy,
                capability_snapshot=snapshot,
            )

    def test_rollback_cannot_restore_a_disabled_release_member(self) -> None:
        first = self.build_synthetic_release()
        self.service.validate_release(PUBLISHER, first["index_release_id"], idempotency_key="validate-old")
        self.service.activate_release(PUBLISHER, first["index_release_id"], expected_active_release_id=None, idempotency_key="activate-old")
        second = self.service.build_release(
            PUBLISHER,
            members=[
                {"kind": "entity", "id": f"fixture:entity:{index}", "revision": 1}
                for index in range(1, 5)
            ] + [
                {"kind": "stage", "id": "fixture:stage:1", "revision": 1},
                {"kind": "variant", "id": "fixture:variant:1", "revision": 1},
                {"kind": "template", "id": "fixture:template:1", "revision": 1},
            ],
            coverage={"status": "synthetic", "reason": "fixture-only"},
            required_capabilities=["fixture:complete-variant:v1"],
        )
        self.service.validate_release(PUBLISHER, second["index_release_id"], idempotency_key="validate-new")
        self.service.activate_release(PUBLISHER, second["index_release_id"], expected_active_release_id=first["index_release_id"], idempotency_key="activate-new")
        reviewer_publisher = Principal(REVIEWER.actor_id, frozenset({"reviewer", "publisher"}))
        with self.assertRaises(PermissionDenied):
            self.service.rollback_release(
                reviewer_publisher,
                first["index_release_id"],
                expected_active_release_id=second["index_release_id"],
                idempotency_key="rollback-by-reviewer",
            )
        rolled_back = self.service.rollback_release(
            PUBLISHER,
            first["index_release_id"],
            expected_active_release_id=second["index_release_id"],
            idempotency_key="rollback-valid-release",
        )
        self.assertEqual(rolled_back["state"], "active")
        self.assertEqual(rolled_back["rollback_from"], second["index_release_id"])
        self.service.disable_record(PUBLISHER, kind="entity", record_id="fixture:entity:1", revision=1, reason="synthetic test withdrawal")
        with self.assertRaises(WithdrawnEvidence):
            self.service.rollback_release(PUBLISHER, second["index_release_id"], expected_active_release_id=first["index_release_id"], idempotency_key="rollback-disabled")
        with self.assertRaises(WithdrawnEvidence):
            self.service.get_release_bundle()

    def test_unapproved_member_and_wrong_role_are_rejected(self) -> None:
        stage = self.service.create_candidate(
            UPDATER,
            kind="stage",
            record_id="fixture:stage:no-review",
            scope={"game_version": "fixture:v", "mode_id": "fixture:m", "cycle_id": "fixture:c", "stage_id": "fixture:stage:no-review"},
            payload={"partitions": ["upper", "lower"]},
            evidence_refs=self.evidence_ref,
            dependency_refs=[],
        )
        with self.assertRaises(PermissionDenied):
            self.service.review_candidate(
                UPDATER,
                kind="stage",
                record_id="fixture:stage:no-review",
                revision=stage["revision"],
                expected_content_hash=stage["content_hash"],
                decision="approved",
                note="Updater role lacks reviewer permission.",
            )
        with self.assertRaises(InvalidTransition):
            self.service.build_release(
                PUBLISHER,
                members=[{"kind": "stage", "id": "fixture:stage:no-review", "revision": stage["revision"]}],
                coverage={"status": "unknown"},
                required_capabilities=[],
            )
        with self.assertRaises(PermissionDenied):
            self.service.validate_release(UPDATER, "fixture:unknown-release", idempotency_key="wrong-role")

    def test_single_maintainer_can_explicitly_review_own_candidate_with_separate_publisher(self) -> None:
        maintainer = Principal("fixture:maintainer", frozenset({"updater", "reviewer"}))
        stage = self.service.create_candidate(
            maintainer,
            kind="stage",
            record_id="fixture:stage:single-maintainer",
            scope={"game_version": "fixture:v", "mode_id": "fixture:m", "cycle_id": "fixture:c", "stage_id": "fixture:stage:single-maintainer"},
            payload={"partitions": ["upper"]},
            evidence_refs=self.evidence_ref,
            dependency_refs=[],
        )
        with self.assertRaises(Conflict):
            self.service.review_candidate(
                maintainer,
                kind="stage",
                record_id="fixture:stage:single-maintainer",
                revision=stage["revision"],
                expected_content_hash="wrong-content-hash",
                decision="approved",
                note="A stale or mismatched hash cannot be approved.",
            )
        approved = self.service.review_candidate(
            maintainer,
            kind="stage",
            record_id="fixture:stage:single-maintainer",
            revision=stage["revision"],
            expected_content_hash=stage["content_hash"],
            decision="approved",
            note="Explicit author review using the immutable content hash.",
        )
        self.assertEqual(approved["state"], "approved")
        with self.assertRaises(InvalidTransition):
            self.service.review_candidate(
                maintainer,
                kind="stage",
                record_id="fixture:stage:single-maintainer",
                revision=stage["revision"],
                expected_content_hash=stage["content_hash"],
                decision="approved",
                note="Duplicate review must not replay as a new action.",
            )
        maintainer_with_publish = Principal(maintainer.actor_id, frozenset({"updater", "reviewer", "publisher"}))
        with self.assertRaises(PermissionDenied):
            self.service.build_release(
                maintainer_with_publish,
                members=[{"kind": "stage", "id": "fixture:stage:single-maintainer", "revision": 1}],
                coverage={"status": "synthetic"},
                required_capabilities=[],
            )
        release = self.service.build_release(
            PUBLISHER,
            members=[{"kind": "stage", "id": "fixture:stage:single-maintainer", "revision": 1}],
            coverage={"status": "synthetic"},
            required_capabilities=[],
        )
        with self.assertRaises(PermissionDenied):
            self.service.validate_release(
                maintainer_with_publish,
                release["index_release_id"],
                idempotency_key="self-reviewer-validate",
            )
        self.service.validate_release(PUBLISHER, release["index_release_id"], idempotency_key="separate-roles-validate")
        with self.assertRaises(PermissionDenied):
            self.service.activate_release(
                maintainer_with_publish,
                release["index_release_id"],
                expected_active_release_id=None,
                idempotency_key="self-reviewer-activate",
            )
        self.service.activate_release(
            PUBLISHER,
            release["index_release_id"],
            expected_active_release_id=None,
            idempotency_key="separate-roles-activate",
        )
        with self.service.database.reader() as db:
            events = db.execute(
                "SELECT action,actor_id FROM audit_events WHERE target_id IN (?,?) ORDER BY rowid",
                ("fixture:stage:single-maintainer", release["index_release_id"]),
            ).fetchall()
        self.assertEqual(
            [event["action"] for event in events],
            ["candidate_created", "candidate_approved", "release_built", "release_validated", "release_activated"],
        )
        self.assertEqual(
            [event["actor_id"] for event in events],
            [maintainer.actor_id, maintainer.actor_id, PUBLISHER.actor_id, PUBLISHER.actor_id, PUBLISHER.actor_id],
        )
        self.assertNotEqual(maintainer.actor_id, PUBLISHER.actor_id)

    def test_update_run_idempotency_and_checkpoint_recovery(self) -> None:
        first = self.service.create_update_run(UPDATER, idempotency_key="run-1", source_id=None, public_scope={"mode_id": "fixture:m"})
        replay = self.service.create_update_run(UPDATER, idempotency_key="run-1", source_id=None, public_scope={"mode_id": "fixture:m"})
        self.assertEqual(replay["run_id"], first["run_id"])
        self.assertTrue(replay["idempotent_replay"])
        with self.assertRaises(Conflict):
            self.service.create_update_run(UPDATER, idempotency_key="run-1", source_id=None, public_scope={"mode_id": "other"})
        task = self.service.claim_update_task(UPDATER, first["task_id"], lease_seconds=60)
        self.assertEqual(task["state"], "running")
        checkpoint = {"step": "discover", "cursor": "cursor-1", "counts": {"seen": 3}}
        saved = self.service.checkpoint_update_task(UPDATER, first["task_id"], checkpoint=checkpoint, output_hash="abc", state="failed")
        self.assertEqual(saved["state"], "failed")
        resumed = self.service.claim_update_task(UPDATER, first["task_id"], lease_seconds=60)
        self.assertEqual(resumed["checkpoint"], checkpoint)
        done = self.service.checkpoint_update_task(UPDATER, first["task_id"], checkpoint=checkpoint, output_hash="final", state="completed")
        self.assertEqual(done["state"], "completed")
        self.assertTrue(self.service.claim_update_task(UPDATER, first["task_id"])["idempotent_replay"])

    def test_update_stages_pause_for_explicit_review_before_resume(self) -> None:
        candidate = self.service.create_candidate(
            UPDATER,
            kind="entity",
            record_id="fixture:entity:review-gate",
            scope={"game_version": "fixture:v", "environment": "live", "release_status": "released"},
            payload={"entity_type": "character", "canonical_name": "Synthetic unit"},
            evidence_refs=self.evidence_ref,
            dependency_refs=[],
        )
        run = self.service.create_update_run(UPDATER, idempotency_key="review-run", source_id=None, public_scope={"mode_id": "fixture:mode"})
        task_ids = run["task_ids"]
        for stage in ("discover", "fetch", "normalize", "extract"):
            task_id = task_ids[stage]
            self.service.claim_update_task(UPDATER, task_id)
            self.service.checkpoint_update_task(UPDATER, task_id, checkpoint={"step": stage}, output_hash=f"hash:{stage}", state="completed")
        review_task = task_ids["review"]
        self.service.claim_update_task(UPDATER, review_task)
        checkpoint = {
            "step": "awaiting_review",
            "review_refs": [{
                "kind": "entity",
                "id": "fixture:entity:review-gate",
                "revision": candidate["revision"],
                "content_hash": candidate["content_hash"],
            }],
        }
        self.service.checkpoint_update_task(UPDATER, review_task, checkpoint=checkpoint, output_hash="pending-review", state="waiting_review")
        with self.assertRaises(Conflict):
            self.service.resume_after_review(UPDATER, review_task, idempotency_key="resume-before-review")
        self.approve("entity", "fixture:entity:review-gate", candidate)
        resumed = self.service.resume_after_review(UPDATER, review_task, idempotency_key="resume-after-review")
        self.assertEqual(resumed["review_decisions"], ["approved"])
        self.service.claim_update_task(UPDATER, review_task)
        self.service.checkpoint_update_task(UPDATER, review_task, checkpoint={"step": "done"}, output_hash="reviewed", state="completed")
        self.assertEqual(self.service.update_run_status(run["run_id"])["status"], "completed")

    def test_local_search_does_not_send_or_echo_question(self) -> None:
        result = self.service.search_public({"query_kind": "public_question", "public_question": "fixture question"})
        self.assertTrue(result["triggered"])
        self.assertEqual(result["provider_status"], "not_configured")
        self.assertEqual(result["temporary_evidence"], [])
        self.assertNotIn("fixture question", json.dumps(result))


if __name__ == "__main__":
    unittest.main()
