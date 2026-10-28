from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from uuid import UUID

try:
    from cryptography.hazmat.primitives import serialization
except ImportError:  # The desktop crypto extra is optional for source-only installs.
    serialization = None

from starhelp_desktop.analysis import ProducerAnalysisRunner
from starhelp_desktop.bundles import (
    BundleValidator,
    Ed25519Keyring,
    PublicBundleCache,
    PublicBundleSynchronizer,
)
from starhelp_desktop.lifecycle import ProfileLifecycle
from starhelp_desktop.models import ProfileAuthorization
from starhelp_desktop.planner import LocalPlannerProcess, bundled_planner_command
from starhelp_desktop.profiles import _snapshot_from_dict
from starhelp_desktop.producer_request import (
    build_producer_analysis_request,
    select_public_task,
)
from starhelp_desktop.reports import ReportLifecycle
from starhelp_desktop.storage import EncryptedPrivateStore
from test_account_core import TestProtector


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "producer-interop-s3"
PUBLIC_BUNDLE = FIXTURE_ROOT / "starhelp-interop-min-v0.1-s3.bpublic.json"
ACCOUNT_SNAPSHOT = FIXTURE_ROOT / "synthetic-b-snapshot-045965b.json"
PUBLIC_KEY = FIXTURE_ROOT / "fixture-ed25519-public.pem"
PROFILE_ID = UUID("11111111-1111-4111-8111-111111111111")
AUTHORIZATION_GENERATION = 7
PUBLICATION_COMMIT = "dcb1e3ee220b85229bedc6c79d72ebe495825f37"
SNAPSHOT_SERIALIZER_COMMIT = "103741e02c90ac672017f783058bdd8dacae982e"
SNAPSHOT_FORMAT_PROFILE = "starhelp.desktop.snapshot.interop-min.v0.1"


@unittest.skipUnless(
    serialization is not None, "install the desktop crypto extra for signed interop"
)
class ProducerPlannerInteropTests(unittest.TestCase):
    def test_signed_public_bundle_and_current_snapshot_serializer_run_in_local_bridge(self) -> None:
        bundle_bytes = PUBLIC_BUNDLE.read_bytes()
        snapshot_fixture_bytes = ACCOUNT_SNAPSHOT.read_bytes()
        key_bytes = PUBLIC_KEY.read_bytes()
        self.assertEqual(
            hashlib.sha256(bundle_bytes).hexdigest(),
            "f777d05bdb269b2e92a612e4fc96a9ad076f9d5b2bc36760c34c1209ff323772",
        )
        self.assertEqual(
            hashlib.sha256(snapshot_fixture_bytes).hexdigest(),
            "e7269a57b83e3145bd647262c4a88d1663718d4078c502f0cd4829108d9b3b58",
        )
        self.assertEqual(
            hashlib.sha256(key_bytes).hexdigest(),
            "7fe277b94d7e7d57dd3fceeaad77495fdff04861c02c3b1cc624c736aac8a29e",
        )
        public_key = serialization.load_pem_public_key(key_bytes).public_bytes(
            serialization.Encoding.Raw, serialization.PublicFormat.Raw
        )
        verifier = Ed25519Keyring({"starhelp-fixture-ed25519-v1": public_key})
        validated = BundleValidator().validate(
            bundle_bytes,
            supported_capabilities=frozenset({
                "starhelp.knowledge-distribution.v1", "starhelp.local-profile.v0.2",
            }),
            signature_verifier=verifier,
        )
        self.assertEqual(validated.release_id, "rel_fixture_s3_0001")
        self.assertEqual(validated.payload_json, bundle_bytes)
        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as cache_directory:
            cache = PublicBundleCache(Path(cache_directory))
            cache.activate(validated)
            reloader = PublicBundleSynchronizer(
                cache,
                signature_verifier=verifier,
                supported_capabilities=frozenset({
                    "starhelp.knowledge-distribution.v1", "starhelp.local-profile.v0.2",
                }),
            )
            cached = reloader.load_current()
            self.assertIsNotNone(cached)
            self.assertEqual(cached.payload_json, bundle_bytes)
            bundle = cached.payload()

        snapshot = _snapshot_from_dict(json.loads(snapshot_fixture_bytes.decode("utf-8")))
        planner_bundle = bundle["objects"][f"planner-view:{validated.release_id}"]["bundle"]
        stage = planner_bundle["stages"][0]
        template = planner_bundle["templates"][0]
        request_id = "fixture:desktop-process-interop"
        task = select_public_task(
            bundle,
            stage_id=stage["stage_id"],
            template_id=template["id"],
            goal_kind=template["public_goals"][0]["kind"],
            allow_rearrangement=True,
        )

        def select_from_mutated_bundle(
            mutate: Callable[[dict[str, Any]], object],
        ) -> dict[str, Any]:
            changed = json.loads(json.dumps(bundle))
            changed_view = changed["objects"][f"planner-view:{validated.release_id}"]["bundle"]
            mutate(changed_view)
            return select_public_task(
                changed,
                stage_id=stage["stage_id"],
                template_id=template["id"],
                goal_kind=template["public_goals"][0]["kind"],
                allow_rearrangement=True,
            )

        malformed_scopes = (
            ("missing key", lambda view: view["stages"][0]["scope"].pop("cycle_id")),
            ("extra key", lambda view: view["templates"][0]["scope"].update(extra="value")),
            ("boolean revision", lambda view: view["stages"][0]["scope"].update(stage_revision=True)),
            ("zero revision", lambda view: view["stages"][0]["scope"].update(stage_revision=0)),
            ("mismatched scopes", lambda view: view["templates"][0]["scope"].update(mode_id="other")),
        )
        for label, mutate in malformed_scopes:
            with self.subTest(scope_case=label), self.assertRaisesRegex(ValueError, "scope"):
                select_from_mutated_bundle(mutate)

        with self.assertRaisesRegex(ValueError, "missing or ambiguous"):
            select_public_task(
                bundle,
                stage_id="fixture:stage:unpublished",
                template_id=template["id"],
                goal_kind=template["public_goals"][0]["kind"],
            )
        feedback = {
            "scope": task["scope"],
            "fields": {
                "fixture:failure_kind": {
                    "value": "fixture:survival",
                    "state": "user_reported",
                    "unit": "fixture:label",
                    "measurement_context": {
                        "phase": "fixture:reported",
                        "assumptions": [],
                    },
                },
            },
        }
        request_args = {
            "validated_bundle": validated,
            "task": task,
            "snapshot": snapshot,
            "authorization_generation": AUTHORIZATION_GENERATION,
            "distribution_trust_purpose": "synthetic-test",
            "distribution_public_keys": {"starhelp-fixture-ed25519-v1": public_key},
            "bundle_producer_commit": PUBLICATION_COMMIT,
            "bundle_format_profile": "starhelp.b-publicbundle-envelope.v1",
            "snapshot_producer_commit": SNAPSHOT_SERIALIZER_COMMIT,
            "snapshot_format_profile": SNAPSHOT_FORMAT_PROFILE,
            "evaluation_time": datetime(2026, 10, 21, 0, 0, tzinfo=UTC),
            "feedback": feedback,
            "request_id": request_id,
        }
        wrapper = build_producer_analysis_request(**request_args)
        self.assertEqual(wrapper["feedback"], feedback)
        self.assertEqual(wrapper["producer_request"]["feedback"], feedback)
        captured_snapshot_bytes = wrapper["producer_request"]["account_snapshot"][
            "raw_json"
        ].encode("utf-8")
        self.assertEqual(captured_snapshot_bytes, snapshot_fixture_bytes)
        self.assertEqual(
            wrapper["producer_request"]["account_snapshot"]["sha256"],
            hashlib.sha256(captured_snapshot_bytes).hexdigest(),
        )
        invalid_feedback = {**feedback, "unexpected": "not-local-feedback-schema"}
        with self.assertRaisesRegex(ValueError, "supported local fields"):
            build_producer_analysis_request(**{**request_args, "feedback": invalid_feedback})
        invalid_feedback = {
            "fields": {
                "fixture:failure_kind": {
                    **feedback["fields"]["fixture:failure_kind"],
                    "state": "confirmed",
                },
            },
        }
        with self.assertRaisesRegex(ValueError, "user-reported"):
            build_producer_analysis_request(**{**request_args, "feedback": invalid_feedback})
        oversized_feedback = {
            "fields": {
                "fixture:failure_kind": {
                    **feedback["fields"]["fixture:failure_kind"],
                    "value": "x" * (64 * 1024),
                },
            },
        }
        with self.assertRaisesRegex(ValueError, "64 KiB"):
            build_producer_analysis_request(**{**request_args, "feedback": oversized_feedback})
        altered_task = json.loads(json.dumps(task))
        altered_task["scope"]["stage_revision"] = True
        with self.assertRaisesRegex(ValueError, "stage_revision must be a positive integer"):
            build_producer_analysis_request(**{**request_args, "task": altered_task})
        altered_task = json.loads(json.dumps(task))
        altered_task["public_goal"]["kind"] = "fixture:goal:other"
        with self.assertRaisesRegex(ValueError, "do not match a template"):
            build_producer_analysis_request(**{**request_args, "task": altered_task})
        with self.assertRaisesRegex(ValueError, "snapshot revision must be a positive integer"):
            build_producer_analysis_request(**{
                **request_args,
                "snapshot": replace(snapshot, revision=0),
            })
        with self.assertRaisesRegex(ValueError, "does not include the bundle's signing key"):
            build_producer_analysis_request(**{
                **request_args,
                "distribution_public_keys": {"unrelated-test-key": public_key},
            })

        with tempfile.TemporaryDirectory(dir=Path(__file__).parent) as directory:
            root = Path(directory)
            store = EncryptedPrivateStore(root / "private", TestProtector())
            lifecycle = ProfileLifecycle(store, root / "temp")
            lifecycle.authorize(
                ProfileAuthorization(
                    profile_id=PROFILE_ID,
                    active=True,
                    generation=AUTHORIZATION_GENERATION,
                    source_id="synthetic-fixture",
                    scopes=frozenset({"analysis"}),
                    confirmed_at=datetime(2026, 10, 16, tzinfo=UTC),
                )
            )
            planner = LocalPlannerProcess(
                command=bundled_planner_command(),
                required_capabilities=frozenset({
                    "starhelp.producers.v0.1", "starhelp.local-profile.v0.2",
                }),
            )
            reports = ReportLifecycle(store, lifecycle)
            execution = ProducerAnalysisRunner(planner, reports).run(
                request=wrapper,
                profile_id=PROFILE_ID,
                authorization_generation=AUTHORIZATION_GENERATION,
                lifecycle=lifecycle,
            )
            result = execution.planner_result
            self.assertIsNotNone(execution.temporary_report)
            assert execution.temporary_report is not None
            self.assertEqual(execution.temporary_report.task["feedback"], feedback)
            self.assertEqual(store.list_profile_keys(PROFILE_ID, "report"), ())
            self.assertIn("ev_fixture_s3_0001@1", execution.temporary_report.public_refs)
            reports.save_explicitly(
                execution.temporary_report,
                current_snapshot_revision=snapshot.revision,
                current_public_release_id=validated.release_id,
            )
            saved_reports = reports.list_saved(
                profile_id=PROFILE_ID,
                generation=AUTHORIZATION_GENERATION,
                current_snapshot_revision=snapshot.revision,
                current_public_release_id=validated.release_id,
            )
            self.assertEqual(len(saved_reports), 1)
            self.assertEqual(saved_reports[0].public_release_id, validated.release_id)
            self.assertEqual(saved_reports[0].snapshot_revision, snapshot.revision)
            withdrawn_wrapper = json.loads(json.dumps(wrapper))
            evidence = planner_bundle["evidence"][0]
            withdrawn_wrapper["producer_request"]["latest_known_validity"][
                "withdrawn_public_refs"
            ] = [{"id": evidence["id"], "revision": evidence["revision"]}]
            withdrawn_execution = ProducerAnalysisRunner(planner, reports).run(
                request=withdrawn_wrapper,
                profile_id=PROFILE_ID,
                authorization_generation=AUTHORIZATION_GENERATION,
                lifecycle=lifecycle,
            )
            withdrawn_result = withdrawn_execution.planner_result
            self.assertIsNone(withdrawn_execution.temporary_report)

        self.assertEqual(result.planner_version, "0.2.0")
        self.assertEqual(result.result["component_version"], "0.4.0")
        self.assertEqual(result.result["status"], "plans_available")
        self.assertEqual(result.result["snapshot_revision"], snapshot.revision)
        self.assertEqual(result.result["authorization_generation"], AUTHORIZATION_GENERATION)
        self.assertEqual(result.result["index_release_id"], validated.release_id)
        self.assertEqual(wrapper["task"]["scope"], stage["scope"])
        self.assertEqual(
            wrapper["producer_request"]["public_bundle"]["sha256"],
            hashlib.sha256(bundle_bytes).hexdigest(),
        )
        self.assertEqual(result.result["current_equipment_plans"], [])
        self.assertEqual(len(result.result["rearrangement_plans"]), 2)
        self.assertEqual(
            {item["variant"]["id"] for item in result.result["rearrangement_plans"]},
            {"fixture:s3:alpha:variant:main", "fixture:s3:alpha:variant:alternate"},
        )
        self.assertTrue(result.result["citations"])
        self.assertTrue(result.result["adapter_metadata"])
        self.assertEqual(withdrawn_result.result["status"], "error")
        withdrawn_error = withdrawn_result.result.get("error")
        self.assertIsInstance(withdrawn_error, dict)
        self.assertEqual(withdrawn_error.get("code"), "withdrawn_public_object")
        self.assertEqual(withdrawn_result.result["request_id"], request_id)
        self.assertEqual(withdrawn_result.result["snapshot_revision"], snapshot.revision)
        self.assertEqual(
            withdrawn_result.result["authorization_generation"], AUTHORIZATION_GENERATION
        )

if __name__ == "__main__":
    unittest.main()
