from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
import unittest
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

try:
    from cryptography.hazmat.primitives import serialization
except ImportError:  # The desktop crypto extra is optional for source-only installs.
    serialization = None

from starhelp_desktop.bundles import (
    BundleValidator,
    Ed25519Keyring,
    PublicBundleCache,
    PublicBundleSynchronizer,
)
from starhelp_desktop.lifecycle import ProfileLifecycle
from starhelp_desktop.planner import LocalPlannerProcess, bundled_planner_command
from starhelp_desktop.models import ProfileAuthorization
from starhelp_desktop.profiles import _snapshot_from_dict, _snapshot_to_dict
from starhelp_desktop.storage import EncryptedPrivateStore
from test_account_core import TestProtector


FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "producer-interop-v1"
PUBLIC_BUNDLE = FIXTURE_ROOT / "knowledge-planner-fixture-v1.bpublic.json"
ACCOUNT_SNAPSHOT = FIXTURE_ROOT / "synthetic-b-snapshot-045965b.json"
PUBLIC_KEY = FIXTURE_ROOT / "fixture-ed25519-public.pem"
PROFILE_ID = UUID("11111111-1111-4111-8111-111111111111")
AUTHORIZATION_GENERATION = 7
PUBLICATION_COMMIT = "00d4a5844e74050359227c274de712878bf9187c"
SNAPSHOT_SERIALIZER_COMMIT = "045965bce4fbc38a3baa79b594535c9dd983d776"


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
            "cd848169254d78586d9ae197f944688463fb72a513d2b38aba7e888feed4d13b",
        )
        self.assertEqual(
            hashlib.sha256(snapshot_fixture_bytes).hexdigest(),
            "a0c9fd982bd78e11e2ead2460b08b4ed13b4cb52afbe7f9274a6ecd35bd0cbd5",
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
        self.assertEqual(validated.release_id, "rel_fixture_0001")
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
        snapshot_bytes = json.dumps(
            _snapshot_to_dict(snapshot), ensure_ascii=False, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
        planner_bundle = bundle["objects"]["planner-view:rel_fixture_0001"]["bundle"]
        stage = planner_bundle["stages"][0]
        template = planner_bundle["templates"][0]
        request_id = "fixture:desktop-process-interop"
        task = {
            "scope": stage["scope"],
            "public_goal": template["public_goals"][0],
            "fixed_character_ids": [],
            "excluded_character_ids": [],
            "locked_local_instance_ids": [],
            "allow_rearrangement": False,
        }
        producer_request = {
            "schema_id": "ProducerAnalysisRequest",
            "schema_version": "0.1",
            "adapter_profile": "starhelp.producers.v0.1",
            "request_id": request_id,
            "public_bundle": {
                "producer": "starhelp_knowledge",
                "producer_commit": PUBLICATION_COMMIT,
                "format_profile": "starhelp.b-publicbundle-envelope.v1",
                "expected_release_id": validated.release_id,
                "raw_json": bundle_bytes.decode("utf-8"),
                "sha256": hashlib.sha256(bundle_bytes).hexdigest(),
            },
            "account_snapshot": {
                "producer": "starhelp_desktop",
                "producer_commit": SNAPSHOT_SERIALIZER_COMMIT,
                "format_profile": "starhelp.desktop.snapshot.045965b",
                "raw_json": snapshot_bytes.decode("utf-8"),
                "sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
            },
            "authorization_context": {
                "profile_id": str(PROFILE_ID),
                "active": True,
                "generation": AUTHORIZATION_GENERATION,
            },
            "distribution_trust": {
                "purpose": "synthetic-test",
                "public_keys": {"starhelp-fixture-ed25519-v1": public_key.hex()},
            },
            "task": task,
            "evaluation_time": "2026-10-16T00:10:00Z",
            "latest_known_validity": {"withdrawn_public_refs": []},
        }
        wrapper = {
            "contract_version": "0.1-draft",
            "schema_id": "AnalysisRequest",
            "schema_version": "0.1-draft",
            "request_id": request_id,
            "authorization_generation": AUTHORIZATION_GENERATION,
            "public_bundle": bundle,
            "account_snapshot": {
                "profile_id": str(PROFILE_ID),
                "snapshot_revision": snapshot.revision,
                "authorization_generation": AUTHORIZATION_GENERATION,
                "authorization_state": "active",
            },
            "task": task,
            "producer_request": producer_request,
        }

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
            result = planner.analyze(
                request=wrapper,
                profile_id=PROFILE_ID,
                authorization_generation=AUTHORIZATION_GENERATION,
                lifecycle=lifecycle,
            )
            withdrawn_wrapper = json.loads(json.dumps(wrapper))
            evidence = planner_bundle["evidence"][0]
            withdrawn_wrapper["producer_request"]["latest_known_validity"][
                "withdrawn_public_refs"
            ] = [{"id": evidence["id"], "revision": evidence["revision"]}]
            withdrawn_result = planner.analyze(
                request=withdrawn_wrapper,
                profile_id=PROFILE_ID,
                authorization_generation=AUTHORIZATION_GENERATION,
                lifecycle=lifecycle,
            )

        self.assertEqual(result.planner_version, "0.2.0")
        self.assertEqual(result.result["component_version"], "0.3.0")
        self.assertEqual(result.result["status"], "plans_available")
        self.assertEqual(result.result["snapshot_revision"], snapshot.revision)
        self.assertEqual(result.result["authorization_generation"], AUTHORIZATION_GENERATION)
        self.assertEqual(result.result["index_release_id"], validated.release_id)
        self.assertEqual(len(result.result["current_equipment_plans"]), 2)
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

        component_root = Path(__file__).resolve().parents[1]
        bundled_worker = (
            component_root / "dist" / "StarHelp" / "planner-worker" / "StarHelpPlannerWorker.exe"
        )
        if bundled_worker.is_file():
            completed = subprocess.run(
                [str(bundled_worker)],
                input=(
                    json.dumps(wrapper, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    + b"\n"
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=60,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, "bundled planner worker failed")
            response = json.loads(completed.stdout.decode("utf-8"))
            self.assertEqual(response["protocol"], "starhelp-local-planner")
            self.assertEqual(response["result"]["status"], "plans_available")
            self.assertEqual(response["result"]["request_id"], request_id)
            self.assertTrue(response["result"]["citations"])

            completed = subprocess.run(
                [str(bundled_worker)],
                input=(
                    json.dumps(withdrawn_wrapper, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
                    + b"\n"
                ),
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                timeout=60,
                check=False,
            )
            self.assertEqual(completed.returncode, 0, "bundled planner worker rejected withdrawal result")
            withdrawn_response = json.loads(completed.stdout.decode("utf-8"))["result"]
            self.assertEqual(withdrawn_response["status"], "error")
            self.assertEqual(withdrawn_response["error"]["code"], "withdrawn_public_object")
            self.assertEqual(withdrawn_response["request_id"], request_id)
            self.assertEqual(withdrawn_response["snapshot_revision"], snapshot.revision)
            self.assertEqual(
                withdrawn_response["authorization_generation"], AUTHORIZATION_GENERATION
            )


if __name__ == "__main__":
    unittest.main()
