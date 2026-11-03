from __future__ import annotations

import hashlib
import json
import tempfile
import threading
import unittest
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from starhelp_desktop.analysis_v2 import ProducerAnalysisRunnerV2
from starhelp_desktop.bundles import BundleRejected, BundleValidator, PublicBundleCache
from starhelp_desktop.distribution_metadata import (
    CATALOG_PROFILE,
    REVOCATIONS_PROFILE,
    DistributionMetadataRejected,
    DistributionMetadataSynchronizer,
    DistributionMetadataTrust,
    DistributionMetadataVerifier,
)
from starhelp_desktop.distribution_http import FixedOriginDistributionSource
from starhelp_desktop.distribution_state import DistributionSecurityStore, VerifiedMetadataPair
from starhelp_desktop.lifecycle import ProfileLifecycle
from starhelp_desktop.local_backend import KnowledgeBackendController, LocalBackendConfig
from starhelp_desktop.planner import PlannerResult
from starhelp_desktop.planner_v2 import _parse_response_v2
from starhelp_desktop.planner_v2_worker import _decode_object
from starhelp_desktop.profiles import ProfileRepository
from starhelp_desktop.producer_v2 import (
    CumulativeRevocations,
    PublicObjectIdentity,
    ReleaseIdentity,
    build_outer_request_v2,
    build_producer_request_v2,
    build_public_basis_sha256,
    canonical_json_bytes,
    load_request_producer_from_source_lock,
    validate_public_basis,
)
from starhelp_desktop.reports import ReportLifecycle, ReportValidity
from starhelp_desktop.storage import EncryptedPrivateStore
from starhelp_desktop.synthetic_demo_v2 import prepare_synthetic_demo_v2


class _IdentityProtector:
    def protect(self, data: bytes) -> bytes:
        return data

    def unprotect(self, data: bytes) -> bytes:
        return data


class _SyntheticPrivateProtector:
    def protect(self, data: bytes) -> bytes:
        return bytes(value ^ 0xA5 for value in data)

    def unprotect(self, data: bytes) -> bytes:
        return bytes(value ^ 0xA5 for value in data)


class _AuthorizedPlanner:
    def __init__(self, result: dict[str, object]) -> None:
        self.result = result

    def analyze(self, **_kwargs: object) -> PlannerResult:
        return PlannerResult(
            "0.5.1",
            frozenset({"starhelp.producers.v0.2", "starhelp.public-basis.v1",
                       "starhelp.request-producer.v1"}),
            self.result,
        )


class DistributionHttpSourceTests(unittest.TestCase):
    def test_fixed_origin_sends_only_public_query_fields_and_rejects_redirects(self) -> None:
        requests: list[tuple[str, dict[str, str]]] = []

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:
                headers = {key.lower(): value for key, value in self.headers.items()}
                requests.append((self.path, headers))
                if self.path == "/v1/distributions/redirect":
                    self.send_response(302)
                    self.send_header("Location", "/followed")
                    self.end_headers()
                    return
                if self.path == "/followed":
                    self.send_response(500)
                    self.end_headers()
                    return
                payload = b'{"synthetic":true}'
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)

            def log_message(self, _format: str, *args: object) -> None:
                return

        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            origin = f"http://127.0.0.1:{server.server_port}"
            source = FixedOriginDistributionSource(origin, "synthetic/stable")
            self.assertEqual(source.fetch_catalog(), b'{"synthetic":true}')
            self.assertEqual(source.fetch_revocations(), b'{"synthetic":true}')
            self.assertEqual(source.fetch_envelope("release_1"), b'{"synthetic":true}')
            with self.assertRaisesRegex(ValueError, "without following redirects"):
                source.fetch_envelope("redirect")
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=2)

        paths = [path for path, _headers in requests]
        self.assertEqual(paths[:3], [
            "/v1/distributions?profile=starhelp.local.v0.2&channel=synthetic%2Fstable",
            "/v1/distribution-revocations?profile=starhelp.local.v0.2&channel=synthetic%2Fstable",
            "/v1/distributions/release_1",
        ])
        self.assertEqual(paths[3], "/v1/distributions/redirect")
        self.assertNotIn("/followed", paths)
        for _path, headers in requests:
            self.assertNotIn("authorization", headers)
            self.assertNotIn("cookie", headers)
        for path in paths:
            self.assertNotIn("uid", path.lower())
            self.assertNotIn("profile_id", path.lower())

    def test_plain_http_distribution_source_is_limited_to_loopback(self) -> None:
        for origin in ("http://example.invalid", "http://192.0.2.1"):
            with self.subTest(origin=origin), self.assertRaisesRegex(
                ValueError, "loopback development service",
            ):
                FixedOriginDistributionSource(origin, "synthetic/stable")


def _basis() -> tuple[dict[str, object], dict[str, dict[str, str]]]:
    catalog = '{"signed":"catalog"}'
    revocations = '{"signed":"revocations"}'
    catalog_hash = hashlib.sha256(catalog.encode()).hexdigest()
    revocations_hash = hashlib.sha256(revocations.encode()).hexdigest()
    pair = {"catalog_sha256": catalog_hash, "revocations_sha256": revocations_hash}
    docs = {
        catalog_hash: {"profile": "starhelp.public-distribution-catalog.v1", "raw_json": catalog},
        revocations_hash: {"profile": "starhelp.public-revocations.v1", "raw_json": revocations},
    }
    basis: dict[str, object] = {
        "profile": "starhelp.public-basis.v1",
        "origin_id": "synthetic-origin",
        "channel": "test",
        "consumer_profile": "starhelp.local.v0.2",
        "policy_id": "synthetic-policy",
        "policy_revision": 1,
        "policy_sha256": "a" * 64,
        "epoch": 1,
        "selected_artifact": {
            "release_id": "release-1", "envelope_sha256": "b" * 64,
            "a_producer": {"package": "starhelp-knowledge", "version": "0.4.0",
                            "commit": "4" * 40},
            "planner": {"profile": "starhelp.planner.v0.5", "producer_profile": "starhelp.producers.v0.2",
                        "component_version": "0.5.1", "wheel_sha256": "5" * 64},
            "b_snapshot": {"profile": "starhelp.local.v0.2", "producer_commit": "6" * 40},
        },
        "qualification_pair": pair,
        "latest_pair": pair,
        "qualified_at": "2026-10-30T00:00:00Z",
        "offline_until": "2026-10-31T00:00:00Z",
        "evaluation_time": "2026-10-30T01:00:00Z",
        "state": "fresh",
    }
    return basis, docs


class ProducerV2Tests(unittest.TestCase):
    def test_v2_synthetic_demo_runs_pinned_worker_and_saves_basis_bound_report(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            private_store = EncryptedPrivateStore(
                root / "private", _SyntheticPrivateProtector(),
            )
            lifecycle = ProfileLifecycle(private_store, root / "temp")
            profiles = ProfileRepository(private_store, lifecycle)
            prepared = prepare_synthetic_demo_v2(
                profiles, lifecycle, private_store, protector=_IdentityProtector(),
                temporary_root=root,
            )
            session = prepared.session
            try:
                execution = session.runner.run(
                    request=prepared.request,
                    profile_id=session.fixture.profile.profile_id,
                    authorization_generation=session.fixture.profile.generation,
                    lifecycle=lifecycle,
                )
                report = execution.temporary_report
                self.assertIsNotNone(report, execution.planner_result.result)
                assert report is not None
                self.assertEqual(session.release.origin_id, "starhelp.synthetic.fixture")
                self.assertFalse(session.policy_config["allow_production"])
                self.assertEqual(report.planner_version, "0.5.1")
                self.assertIn("current_equipment_plans", report.result)
                self.assertEqual(report.result["producer_response"]["status"], "plans_available")
                citation = report.result["citations"][0]
                self.assertEqual(citation["kind"], "evidence")
                self.assertEqual(citation["id"], "ev_fixture_s3_0001")
                self.assertEqual(
                    citation["content_hash"],
                    "31fd2606d894719b33a1e552d3655fc8a712bfbd7375fa6d7021c33413b129a1",
                )
                self.assertEqual(
                    report.result["producer_response"]["analysis_citations"][0]["id"],
                    citation["id"],
                )
                self.assertEqual(report.public_basis_sha256,
                                 prepared.request["producer_request"]["public_basis_sha256"])
                self.assertEqual(private_store.list_profile_keys(report.profile_id, "report"), ())

                session.save_report(report, current_snapshot_revision=session.fixture.snapshot.revision)
                saved = private_store.list_profile_keys(report.profile_id, "report")
                self.assertEqual(len(saved), 1)
                self.assertEqual(private_store.load(saved[0])["validity"], "current")
            finally:
                session.temporary_directory.cleanup()

    def test_v2_runner_stages_unsaved_basis_bound_report_then_saves_explicitly(self) -> None:
        now = datetime.now(UTC).replace(microsecond=0)
        pair = VerifiedMetadataPair(
            b'{"signed":"synthetic catalog"}', b'{"signed":"synthetic revocations"}',
            1, 1, now + timedelta(hours=4), now + timedelta(hours=4),
        )
        identity = ReleaseIdentity("synthetic-origin", "test", "starhelp.local.v0.2",
                                   "release-runner", "a" * 64)
        selected_artifact = {
            "a_producer": {"package": "starhelp-knowledge", "version": "0.4.0",
                            "commit": "1" * 40},
            "planner": {"profile": "starhelp.planner.v0.5",
                        "producer_profile": "starhelp.producers.v0.2",
                        "component_version": "0.5.1", "wheel_sha256": "b" * 64},
            "b_snapshot": {"profile": "starhelp.local.v0.2", "producer_commit": "2" * 40},
        }
        citation = PublicObjectIdentity(
            "template", "synthetic-template", 1, "starhelp.a-native-content-field.v1", "c" * 64,
        ).as_dict()

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)
            security = DistributionSecurityStore(
                root / "distribution-state.bin", protector=_IdentityProtector(),
            )
            security.begin_update()
            security.accept_verified_catalog(
                sequence=pair.catalog_sequence, digest=pair.catalog_sha256, observed_at=now,
            )
            security.commit_verified_pair(pair, observed_at=now)
            security.qualify_artifact(identity, pair=pair, allowed=True, observed_at=now)
            basis, basis_digest, _documents = security.create_public_basis(
                identity, selected_artifact=selected_artifact,
                policy_config={"policy_id": "synthetic-test", "revision": 1},
                evaluation_time=now,
            )

            private_store = EncryptedPrivateStore(root / "private", _SyntheticPrivateProtector())
            lifecycle = ProfileLifecycle(private_store, root / "temp")
            profiles = ProfileRepository(private_store, lifecycle)
            profile = profiles.begin_profile(
                label="synthetic report runner", provider_id="synthetic-test",
                server_label="fixture-only",
            )
            reports = ReportLifecycle(private_store, lifecycle)
            runner = ProducerAnalysisRunnerV2(
                _AuthorizedPlanner({
                    "status": "plans_available", "index_release_id": identity.release_id,
                    "citations": [citation], "plans": [{"template_id": "synthetic-template"}],
                }),
                reports,
                security,
            )
            raw_snapshot = json.dumps({
                "profile_id": str(profile.profile_id), "revision": 7,
            }, separators=(",", ":"))
            request = {"producer_request": {
                "account_snapshot": {"raw_json": raw_snapshot},
                "public_bundle": {"expected_release_id": identity.release_id},
                "task": {"scope": {"mode_id": "fixture:mode"}},
                "public_basis": basis,
                "public_basis_sha256": basis_digest,
            }}

            execution = runner.run(
                request=request, profile_id=profile.profile_id,
                authorization_generation=profile.generation, lifecycle=lifecycle,
            )

            report = execution.temporary_report
            self.assertIsNotNone(report)
            assert report is not None
            self.assertEqual(report.public_basis_sha256, basis_digest)
            self.assertEqual(report.public_epoch, basis["epoch"])
            self.assertEqual(report.validity, ReportValidity.NEEDS_REVIEW)
            self.assertEqual(private_store.list_profile_keys(profile.profile_id, "report"), ())

            runner.save_current(
                report, current_snapshot_revision=7,
                current_release_id=identity.release_id, known_withdrawn_refs=frozenset(),
            )
            saved = private_store.list_profile_keys(profile.profile_id, "report")
            self.assertEqual(len(saved), 1)
            self.assertEqual(private_store.load(saved[0])["validity"], ReportValidity.CURRENT.value)

    def test_v2_worker_input_parser_rejects_duplicate_keys_and_nonfinite_values(self) -> None:
        with self.assertRaisesRegex(ValueError, "duplicate JSON object key"):
            _decode_object(b'{"request_id":"first","request_id":"second"}', "request")
        with self.assertRaisesRegex(ValueError, "non-finite JSON number"):
            _decode_object(b'{"value":NaN}', "request")
        with self.assertRaisesRegex(ValueError, "JSON object"):
            _decode_object(b'[]', "request")

    @staticmethod
    def _signed(profile: str, payload: dict[str, object], key_id: str,
                private_key: Ed25519PrivateKey) -> bytes:
        signature_payload = {
            "profile": profile, "algorithm": "Ed25519", "key_id": key_id, "payload": payload,
        }
        signature = private_key.sign(profile.encode("ascii") + b"\n" +
                                     canonical_json_bytes(signature_payload))
        envelope = {
            "profile": profile, "payload": payload,
            "signature": {"algorithm": "Ed25519", "key_id": key_id, "value": signature.hex()},
        }
        return canonical_json_bytes(envelope)

    def test_signed_metadata_verifier_checks_raw_pair_and_typed_revocations(self) -> None:
        now = datetime.now(UTC).replace(microsecond=0)
        key_id = "synthetic-key"
        channel = "local/组"
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw,
        ).hex()
        issued = now.isoformat().replace("+00:00", "Z")
        expiry = (now + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        revocations_payload: dict[str, object] = {
            "schema_version": REVOCATIONS_PROFILE, "origin_id": "synthetic-origin",
            "channel": channel, "consumer_profile": "starhelp.local.v0.2", "sequence": 1,
            "issued_at": issued, "valid_until": expiry,
            "revoked_releases": [{
                "release_id": "revoked-release", "envelope_sha256": "a" * 64,
                "reason_code": "integrity_issue", "effective_at": issued,
            }],
            "revoked_public_refs": [{
                "kind": "entity", "id": "entity-1", "revision": 2,
                "content_hash": "b" * 64, "reason_code": "source_correction", "effective_at": issued,
            }],
        }
        revocations_raw = self._signed(REVOCATIONS_PROFILE, revocations_payload, key_id, private)
        catalog_payload: dict[str, object] = {
            "schema_version": CATALOG_PROFILE, "origin_id": "synthetic-origin",
            "channel": channel, "consumer_profile": "starhelp.local.v0.2", "sequence": 4,
            "issued_at": issued, "valid_until": expiry, "active_release_id": "release-1",
            "distributions": [{
                "release_id": "release-1", "download_path": "/v1/distributions/release-1",
                "envelope_sha256": "c" * 64, "size_bytes": 100,
                "envelope_profile": "starhelp.b-publicbundle-envelope.v1",
                "a_producer": {"package": "starhelp-knowledge", "version": "0.4.0",
                                "commit": "1" * 40},
                "required_capabilities": ["starhelp.public-basis.v1"],
                "planner": {"profile": "starhelp.planner.v0.5",
                            "producer_profile": "starhelp.producers.v0.2",
                            "component_version": "0.5.1", "wheel_sha256": "d" * 64},
                "b_snapshot": {"profile": "starhelp.local.v0.2", "producer_commit": "2" * 40},
                "rollback_allowed": False,
            }],
            "revocation_snapshot": {
                "path": "/v1/distribution-revocations?profile=starhelp.local.v0.2&channel=local%2F%E7%BB%84",
                "sha256": hashlib.sha256(revocations_raw).hexdigest(),
                "size_bytes": len(revocations_raw), "sequence": 1,
            },
        }
        catalog_raw = self._signed(CATALOG_PROFILE, catalog_payload, key_id, private)
        key = {
            "key_id": key_id, "public_key_hex": public,
            "purposes": ["synthetic-catalog", "synthetic-revocations"],
            "not_before": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            "not_after": expiry, "revoked": False,
        }
        verifier = DistributionMetadataVerifier(DistributionMetadataTrust(
            "synthetic-origin", channel, "starhelp.local.v0.2", (key,),
            supported_capabilities=frozenset({"starhelp.public-basis.v1"}),
        ))
        pair = verifier.verify_pair(catalog_raw, revocations_raw, now=now)
        self.assertEqual((pair.catalog_sequence, pair.revocations_sequence), (4, 1))
        self.assertEqual(pair.releases[0]["release_id"], "revoked-release")
        self.assertEqual(pair.objects[0]["hash_profile"], "starhelp.a-native-content-field.v1")

        class Source:
            def fetch_catalog(self) -> bytes:
                return catalog_raw

            def fetch_revocations(self) -> bytes:
                return revocations_raw

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            store = DistributionSecurityStore(
                Path(directory) / "state.bin", protector=_IdentityProtector(),
            )
            accepted = DistributionMetadataSynchronizer(Source(), verifier, store).sync(now=now)
            self.assertEqual(accepted.catalog_sequence, 4)
            self.assertEqual(store.snapshot()["high_water"]["catalog_sequence"], 4)
            active = ReleaseIdentity("synthetic-origin", channel, "starhelp.local.v0.2",
                                     "release-1", "c" * 64)
            store.qualify_artifact(active, pair=accepted, allowed=True, observed_at=now)
            documents = store.public_documents_for(active)
            self.assertEqual(len(documents), 2)
            self.assertIn(hashlib.sha256(catalog_raw).hexdigest(), documents)
            basis, basis_digest, basis_documents = store.create_public_basis(
                active,
                selected_artifact={
                    "a_producer": catalog_payload["distributions"][0]["a_producer"],
                    "planner": catalog_payload["distributions"][0]["planner"],
                    "b_snapshot": catalog_payload["distributions"][0]["b_snapshot"],
                },
                policy_config={"policy_id": "synthetic-policy", "revision": 1},
                evaluation_time=now,
            )
            self.assertEqual(basis["state"], "fresh")
            self.assertEqual(basis["epoch"], store.snapshot()["public_epoch"])
            self.assertEqual(validate_public_basis(basis, basis_digest, basis_documents), basis)

            class UnavailableRevocations:
                def fetch_catalog(self) -> bytes:
                    return catalog_raw

                def fetch_revocations(self) -> bytes:
                    raise OSError("synthetic offline")

            interrupted = DistributionSecurityStore(
                Path(directory) / "interrupted.bin", protector=_IdentityProtector(),
            )
            with self.assertRaises(OSError):
                DistributionMetadataSynchronizer(
                    UnavailableRevocations(), verifier, interrupted
                ).sync(now=now)
            interrupted_state = interrupted.snapshot()
            self.assertEqual(interrupted_state["high_water"]["catalog_sequence"], 4)
            self.assertEqual(interrupted_state["safety_state"], "pending")
            recovered = DistributionSecurityStore(
                Path(directory) / "interrupted.bin", protector=_IdentityProtector(),
            )
            self.assertEqual(recovered.snapshot()["safety_state"], "recovery_required")

        with self.assertRaises(DistributionMetadataRejected):
            DistributionMetadataVerifier(DistributionMetadataTrust(
                "synthetic-origin", channel, "starhelp.local.v0.2",
                ({**key, "purposes": ["synthetic-release"]},),
                supported_capabilities=frozenset({"starhelp.public-basis.v1"}),
            )).verify_pair(catalog_raw, revocations_raw, now=now)

        wrong_route_payload = json.loads(json.dumps(catalog_payload))
        wrong_route_payload["revocation_snapshot"]["path"] += "&channel=other"
        wrong_route = self._signed(CATALOG_PROFILE, wrong_route_payload, key_id, private)
        with self.assertRaisesRegex(
            DistributionMetadataRejected, "distribution_catalog_revocation_invalid",
        ):
            verifier.verify_pair(wrong_route, revocations_raw, now=now)

    def test_rollback_requires_current_signed_admission_and_keeps_current_on_failure(self) -> None:
        now = datetime.now(UTC).replace(microsecond=0)
        key_id = "synthetic-key"
        private = Ed25519PrivateKey.generate()
        public = private.public_key().public_bytes(
            encoding=serialization.Encoding.Raw, format=serialization.PublicFormat.Raw,
        ).hex()
        bundle_key_id = "bundle-key"
        bundle_private = Ed25519PrivateKey.generate()
        bundle_public_key = bundle_private.public_key()
        issued = now.isoformat().replace("+00:00", "Z")
        expiry = (now + timedelta(hours=2)).isoformat().replace("+00:00", "Z")
        a_tuple = {"package": "starhelp-knowledge", "version": "0.4.0", "commit": "1" * 40}
        c_tuple = {
            "profile": "starhelp.planner.v0.5", "producer_profile": "starhelp.producers.v0.2",
            "component_version": "0.5.1", "wheel_sha256": "d" * 64,
        }
        b_tuple = {"profile": "starhelp.local.v0.2", "producer_commit": "2" * 40}

        def make_bundle(release_id: str) -> bytes:
            objects = {"fixture:object": {"kind": "fixture", "refs": []}}
            manifest = {
                "index_release_id": release_id,
                "distribution_profile": "starhelp.b-publicbundle-envelope.v1",
                "required_capabilities": [],
                "native_profile": "fixture.native.v1",
                "planner_profile": "starhelp.local.v0.2",
                "signing_key_id": bundle_key_id,
                "members": {"fixture:object": hashlib.sha256(
                    canonical_json_bytes(objects["fixture:object"])
                ).hexdigest()},
                "coverage": {"synthetic": True},
            }
            signed = canonical_json_bytes(manifest)
            signature = bundle_private.sign(signed).hex()
            return canonical_json_bytes({
                "contract_version": "0.1-draft", "schema_id": "PublicBundle",
                "schema_version": "0.1-draft", "manifest": manifest,
                "signature": signature, "objects": objects,
            })

        class BundleVerifier:
            def verify(self, candidate_key_id: str, signed_bytes: bytes,
                       signature: bytes) -> bool:
                if candidate_key_id != bundle_key_id:
                    return False
                try:
                    bundle_public_key.verify(signature, signed_bytes)
                    return True
                except Exception:
                    return False

        bundles = {release_id: make_bundle(release_id) for release_id in ("release-1", "release-2")}
        def make_revocations(*, revoke_target: bool, sequence: int = 1) -> bytes:
            revoked_releases = ([{
                "release_id": "release-1",
                "envelope_sha256": hashlib.sha256(bundles["release-1"]).hexdigest(),
                "reason_code": "integrity_issue", "effective_at": issued,
            }] if revoke_target else [])
            return self._signed(REVOCATIONS_PROFILE, {
                "schema_version": REVOCATIONS_PROFILE, "origin_id": "synthetic-origin",
                "channel": "test", "consumer_profile": "starhelp.local.v0.2",
                "sequence": sequence,
                "issued_at": issued, "valid_until": expiry,
                "revoked_releases": revoked_releases, "revoked_public_refs": [],
            }, key_id, private)

        def make_catalog(*, rollback_allowed: bool, revocations_raw: bytes,
                         sequence: int = 2, revocation_sequence: int = 1) -> bytes:
            distributions = []
            for release_id in ("release-1", "release-2"):
                distributions.append({
                    "release_id": release_id,
                    "download_path": f"/v1/distributions/{release_id}",
                    "envelope_sha256": hashlib.sha256(bundles[release_id]).hexdigest(),
                    "size_bytes": len(bundles[release_id]),
                    "envelope_profile": "starhelp.b-publicbundle-envelope.v1",
                    "a_producer": a_tuple, "required_capabilities": [],
                    "planner": c_tuple, "b_snapshot": b_tuple,
                    "rollback_allowed": release_id == "release-1" and rollback_allowed,
                })
            return self._signed(CATALOG_PROFILE, {
                "schema_version": CATALOG_PROFILE, "origin_id": "synthetic-origin",
                "channel": "test", "consumer_profile": "starhelp.local.v0.2",
                "sequence": sequence,
                "issued_at": issued, "valid_until": expiry, "active_release_id": "release-2",
                "distributions": distributions,
                "revocation_snapshot": {
                    "path": "/v1/distribution-revocations?profile=starhelp.local.v0.2&channel=test",
                    "sha256": hashlib.sha256(revocations_raw).hexdigest(),
                    "size_bytes": len(revocations_raw), "sequence": revocation_sequence,
                },
            }, key_id, private)

        metadata_key = {
            "key_id": key_id, "public_key_hex": public,
            "purposes": ["synthetic-catalog", "synthetic-revocations"],
            "not_before": (now - timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
            "not_after": expiry, "revoked": False,
        }
        verifier = DistributionMetadataVerifier(DistributionMetadataTrust(
            "synthetic-origin", "test", "starhelp.local.v0.2", (metadata_key,),
        ))
        bundle_verifier = BundleVerifier()
        native_tuple = {**a_tuple, "native_profile": "fixture.native.v1",
                        "planner_profile": "starhelp.local.v0.2"}

        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            root = Path(directory)

            def make_case(name: str, rollback_allowed: bool, *, revoke_target: bool = False) -> tuple[
                    DistributionMetadataSynchronizer, PublicBundleCache]:
                revoked_raw = make_revocations(revoke_target=revoke_target)
                catalog_raw = make_catalog(
                    rollback_allowed=rollback_allowed, revocations_raw=revoked_raw,
                )

                class Source:
                    def fetch_catalog(self) -> bytes:
                        return catalog_raw

                    def fetch_revocations(self) -> bytes:
                        return revoked_raw

                    def fetch_envelope(self, _release_id: str) -> bytes:
                        raise AssertionError("rollback must use the exact cached release bytes")

                case_root = root / name
                case_root.mkdir()
                cache = PublicBundleCache(case_root / "cache")
                bundle_validator = BundleValidator()
                for release_id in ("release-1", "release-2"):
                    cache.activate(bundle_validator.validate(
                        bundles[release_id], supported_capabilities=frozenset(),
                        expected_release_id=release_id, signature_verifier=bundle_verifier,
                    ))
                store = DistributionSecurityStore(
                    case_root / "state.bin", protector=_IdentityProtector(),
                )
                return DistributionMetadataSynchronizer(Source(), verifier, store), cache

            denied, denied_cache = make_case("denied", False)
            with self.assertRaisesRegex(BundleRejected, "not_allowed_by_verified_catalog"):
                denied.rollback(
                    denied_cache, "release-1", signature_verifier=bundle_verifier,
                    supported_capabilities=frozenset(), allowed_a_producers=(native_tuple,),
                    allowed_c_components=(c_tuple,), allowed_b_snapshots=(b_tuple,), now=now,
                )
            self.assertEqual(denied_cache.current_release_id(), "release-2")

            allowed, allowed_cache = make_case("allowed", True)
            original_write = allowed_cache._atomic_write

            def fail_current_write(destination: Path, data: bytes) -> None:
                if destination == allowed_cache.current_file:
                    raise OSError("synthetic current-pointer failure")
                original_write(destination, data)

            allowed_cache._atomic_write = fail_current_write
            with self.assertRaisesRegex(OSError, "current-pointer failure"):
                allowed.rollback(
                    allowed_cache, "release-1", signature_verifier=bundle_verifier,
                    supported_capabilities=frozenset(), allowed_a_producers=(native_tuple,),
                    allowed_c_components=(c_tuple,), allowed_b_snapshots=(b_tuple,), now=now,
                )
            self.assertEqual(allowed_cache.current_release_id(), "release-2")
            del allowed_cache._atomic_write
            result = allowed.rollback(
                allowed_cache, "release-1", signature_verifier=bundle_verifier,
                supported_capabilities=frozenset(), allowed_a_producers=(native_tuple,),
                allowed_c_components=(c_tuple,), allowed_b_snapshots=(b_tuple,), now=now,
            )
            self.assertEqual(result.previous_release_id, "release-2")
            self.assertEqual(result.current_release_id, "release-1")
            self.assertTrue(result.updated)
            self.assertEqual(allowed_cache.current_release_id(), "release-1")

            revoked, revoked_cache = make_case("revoked", True, revoke_target=True)
            with self.assertRaisesRegex(BundleRejected, "target is unusable: revoked"):
                revoked.rollback(
                    revoked_cache, "release-1", signature_verifier=bundle_verifier,
                    supported_capabilities=frozenset(), allowed_a_producers=(native_tuple,),
                    allowed_c_components=(c_tuple,), allowed_b_snapshots=(b_tuple,), now=now,
                )
            self.assertEqual(revoked_cache.current_release_id(), "release-2")

            raced, raced_cache = make_case("raced", True)
            newer_revocations = make_revocations(revoke_target=True, sequence=2)
            newer_catalog = make_catalog(
                rollback_allowed=True, revocations_raw=newer_revocations,
                sequence=3, revocation_sequence=2,
            )
            newer_pair = raced._verifier.verify_pair(
                newer_catalog, newer_revocations, now=now,
            )
            original_epoch_guard = raced._security.run_if_epoch_current

            def advance_revocations_then_guard(epoch: int, operation: object) -> object:
                raced._security.commit_verified_pair(newer_pair, observed_at=now)
                return original_epoch_guard(epoch, operation)

            raced._security.run_if_epoch_current = advance_revocations_then_guard
            with self.assertRaisesRegex(BundleRejected, "safety state changed"):
                raced.rollback(
                    raced_cache, "release-1", signature_verifier=bundle_verifier,
                    supported_capabilities=frozenset(), allowed_a_producers=(native_tuple,),
                    allowed_c_components=(c_tuple,), allowed_b_snapshots=(b_tuple,), now=now,
                )
            self.assertEqual(raced_cache.current_release_id(), "release-2")

    def test_typed_tombstones_merge_monotonically_and_match_full_identity(self) -> None:
        release = ReleaseIdentity("origin", "stable", "native", "r1", "a" * 64)
        ref = PublicObjectIdentity("entity", "same-id", 1,
                                   "starhelp.a-native-content-field.v1", "b" * 64)
        ledger = CumulativeRevocations()
        ledger.merge(releases=[release.as_dict()], objects=[ref.as_dict()])
        ledger.merge(releases=[], objects=[])
        self.assertTrue(ledger.release_is_revoked(release))
        self.assertTrue(ledger.object_is_revoked(ref))
        self.assertFalse(ledger.object_is_revoked(PublicObjectIdentity(
            "knowledge", "same-id", 1, "starhelp.a-native-content-field.v1", "b" * 64
        )))
        self.assertFalse(ledger.object_is_revoked(PublicObjectIdentity(
            "entity", "same-id", 1, "starhelp.a-native-content-field.v1", "c" * 64
        )))

    def test_object_revision_rejects_boolean(self) -> None:
        with self.assertRaises(ValueError):
            PublicObjectIdentity("entity", "x", True,
                                 "starhelp.a-native-content-field.v1", "a" * 64)

    def test_source_lock_loader_binds_artifact_and_dependency_digests(self) -> None:
        deps = [
            {"path": "packages/starhelp-desktop/pyproject.toml", "git_blob": "3" * 40,
             "raw_sha256": "4" * 64},
            {"path": "packages/starhelp-desktop/src/starhelp_desktop/producer_v2.py",
             "git_blob": "1" * 40, "raw_sha256": "2" * 64},
        ]
        lock = {
            "schema_id": "BSourceLock", "schema_version": "0.2",
            "name": "starhelp-desktop", "package_version": "0.2.0",
            "source_commit": "3" * 40, "builder_module": "starhelp_desktop.producer_v2",
            "builder_blob": "1" * 40,
            "dependency_lock_sha256": hashlib.sha256(canonical_json_bytes(deps)).hexdigest(),
            "dependencies": deps,
        }
        raw = canonical_json_bytes(lock) + b"\n"
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            path = Path(directory) / "source-lock.json"
            path.write_bytes(raw)
            producer = load_request_producer_from_source_lock(path)
            self.assertEqual(producer["artifact_sha256"], hashlib.sha256(raw).hexdigest())
            lock["dependencies"] = [deps[0], {**deps[1], "raw_sha256": "5" * 64}]
            path.write_bytes(canonical_json_bytes(lock) + b"\n")
            with self.assertRaisesRegex(ValueError, "digest mismatch"):
                load_request_producer_from_source_lock(path)

    def test_local_backend_readiness_requires_owned_instance_and_distribution(self) -> None:
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            executable = Path(directory) / "synthetic.exe"
            executable.write_bytes(b"synthetic")
            controller = KnowledgeBackendController(LocalBackendConfig(
                executable=executable, executable_sha256=hashlib.sha256(b"synthetic").hexdigest(),
                application_version="0.4.0", database_path=Path(directory) / "db.sqlite",
                distribution_store=Path(directory) / "dist", port=18765,
            ))
            ready = {
                "status": "ready", "service": "starhelp-knowledge",
                "application_version": "0.4.0", "schema_version": "9",
                "database": "ready", "migration": "current", "active_release_id": "r1",
                "distribution_catalog": "available", "checked_at": "2026-10-30T00:00:00Z",
                "instance_id": "owned-instance",
            }
            controller._validate_readiness(ready, "owned-instance")
            with self.assertRaisesRegex(ValueError, "identity"):
                controller._validate_readiness({**ready, "instance_id": "external-instance"},
                                               "owned-instance")
            with self.assertRaisesRegex(ValueError, "identity"):
                controller._validate_readiness({**ready, "distribution_catalog": "unavailable"},
                                               "owned-instance")

    def test_basis_binds_documents_and_digest(self) -> None:
        basis, documents = _basis()
        digest = build_public_basis_sha256(basis)
        self.assertEqual(validate_public_basis(basis, digest, documents), basis)
        with self.assertRaisesRegex(ValueError, "digest"):
            validate_public_basis(basis, "0" * 64, documents)
        altered = dict(documents)
        doc_hash = next(iter(altered))
        altered[doc_hash] = {**altered[doc_hash], "raw_json": "{}"}
        with self.assertRaisesRegex(ValueError, "digest"):
            validate_public_basis(basis, digest, altered)

    def test_v2_request_has_one_authoritative_inner_payload(self) -> None:
        basis, documents = _basis()
        snapshot_raw = '{"profile_id":"p1","revision":7}'
        release_bundle = {
            "manifest": {"index_release_id": "release-1"},
            "objects": {"planner-view:release-1": {"bundle": {
                "stages": [{"stage_id": "stage-1", "index_release_id": "release-1",
                            "scope": {"game_version": "v1", "environment": "synthetic",
                                      "mode_id": "mode-1", "cycle_id": "cycle-1",
                                      "stage_id": "stage-1", "stage_revision": 1}}],
                "templates": [{"index_release_id": "release-1", "stage_ids": ["stage-1"],
                               "scope": {"game_version": "v1", "environment": "synthetic",
                                         "mode_id": "mode-1", "cycle_id": "cycle-1",
                                         "stage_id": "stage-1", "stage_revision": 1},
                               "public_goals": [{"kind": "synthetic-goal"}]}],
            }}},
        }
        bundle_raw = canonical_json_bytes(release_bundle).decode("utf-8")
        basis["selected_artifact"]["envelope_sha256"] = hashlib.sha256(bundle_raw.encode()).hexdigest()
        source_lock = b'{"schema_id":"BSourceLock","schema_version":"0.2"}\n'
        producer = {
            "name": "starhelp-desktop", "package_version": "0.2.0",
            "source_commit": "1" * 40, "builder_module": "starhelp_desktop.producer_v2",
            "builder_blob": "2" * 40, "dependency_lock_sha256": "3" * 64,
            "artifact_kind": "source-lock", "artifact_sha256": hashlib.sha256(source_lock).hexdigest(),
        }
        inner = build_producer_request_v2(
            request_id="req-1", request_producer=producer,
            public_bundle={
                "producer": "starhelp_knowledge", "producer_commit": "4" * 40,
                "format_profile": "native-v0.2", "expected_release_id": "release-1",
                "raw_json": bundle_raw, "sha256": hashlib.sha256(bundle_raw.encode()).hexdigest(),
            },
            account_snapshot={
                "producer": "starhelp_desktop", "producer_commit": "5" * 40,
                "format_profile": "starhelp.local.v0.2", "raw_json": snapshot_raw,
                "sha256": hashlib.sha256(snapshot_raw.encode()).hexdigest(),
            },
            authorization_context={"profile_id": "p1", "active": True, "generation": 2},
            task={
                "scope": {"game_version": "v1", "environment": "synthetic",
                          "mode_id": "mode-1", "cycle_id": "cycle-1",
                          "stage_id": "stage-1", "stage_revision": 1},
                "public_goal": {"kind": "synthetic-goal"},
                "fixed_character_ids": [], "excluded_character_ids": [],
                "locked_local_instance_ids": [], "allow_rearrangement": False,
            }, evaluation_time="2026-10-30T01:00:00Z",
            public_basis=basis, public_documents=documents,
        )
        outer = build_outer_request_v2(
            request_id="req-1", authorization_generation=2, profile_id="p1",
            snapshot_revision=7, producer_request=inner,
        )
        self.assertEqual(set(outer), {
            "schema_id", "schema_version", "request_id", "authorization_generation",
            "account_snapshot", "producer_request",
        })
        self.assertNotIn("task", outer)
        self.assertEqual(outer["producer_request"]["request_id"], "req-1")
        result = {
            "request_id": "req-1", "request_producer": producer,
            "request_sha256": hashlib.sha256(canonical_json_bytes(inner)).hexdigest(),
            "feedback_sha256": hashlib.sha256(canonical_json_bytes(None)).hexdigest(),
            "public_basis_sha256": inner["public_basis_sha256"], "public_epoch": 1,
            "snapshot_revision": 7, "authorization_generation": 2,
            "adapter_profile": "starhelp.producers.v0.2", "status": "error",
        }
        response = {
            "protocol": "starhelp-local-planner", "protocol_version": "0.2",
            "planner_version": "0.5.1",
            "capabilities": ["starhelp.producers.v0.2", "starhelp.public-basis.v1",
                             "starhelp.request-producer.v1"],
            "result": result,
        }
        parsed = _parse_response_v2(canonical_json_bytes(response), outer)
        self.assertEqual(parsed.result["public_epoch"], 1)
        response["result"] = {**result, "request_sha256": "0" * 64}
        with self.assertRaisesRegex(RuntimeError, "correlation"):
            _parse_response_v2(canonical_json_bytes(response), outer)

    def test_security_store_keeps_original_qualification_and_gates_recovery(self) -> None:
        now = datetime.now(UTC).replace(microsecond=0)
        identity = ReleaseIdentity("origin", "stable", "native", "r1", "a" * 64)
        historical_revocation = ReleaseIdentity("origin", "stable", "native", "r0", "c" * 64)
        first = VerifiedMetadataPair(
            b"catalog-1", b"revocations-1", 1, 1,
            now + timedelta(hours=24), now + timedelta(hours=24),
            releases=(historical_revocation.as_dict(),),
        )
        second = VerifiedMetadataPair(
            b"catalog-2", b"revocations-2", 2, 2,
            now + timedelta(hours=30), now + timedelta(hours=30),
        )
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            path = Path(directory) / "distribution-state.bin"
            store = DistributionSecurityStore(path, protector=_IdentityProtector())
            store.begin_update()
            store.accept_verified_catalog(
                sequence=first.catalog_sequence, digest=first.catalog_sha256, observed_at=now,
            )
            store.commit_verified_pair(first, observed_at=now)
            qualification = store.qualify_artifact(
                identity, pair=first, allowed=True, observed_at=now,
            )
            basis_epoch = store.snapshot()["public_epoch"]
            store.begin_update()
            refreshed_at = now + timedelta(seconds=1)
            store.accept_verified_catalog(
                sequence=second.catalog_sequence, digest=second.catalog_sha256,
                observed_at=refreshed_at,
            )
            changed_epoch = store.commit_verified_pair(second, observed_at=refreshed_at)
            with self.assertRaisesRegex(ValueError, "public_basis_changed"):
                store.run_if_epoch_current(basis_epoch, lambda: None)
            unchanged = store.qualify_artifact(
                identity, pair=second, allowed=True, observed_at=refreshed_at,
            )
            self.assertEqual(unchanged["qualified_at"], qualification["qualified_at"])
            with self.assertRaisesRegex(ValueError, "revoked"):
                store.assert_release_usable(historical_revocation, now=refreshed_at)
            self.assertEqual(store.run_if_epoch_current(changed_epoch, lambda: "saved"), "saved")
            self.assertEqual(store.effective_state(identity, now=now), "fresh")
            reopened = DistributionSecurityStore(path, protector=_IdentityProtector())
            self.assertEqual(reopened.snapshot()["safety_state"], "ready")
            reopened.begin_update()
            recovered = DistributionSecurityStore(path, protector=_IdentityProtector())
            self.assertEqual(recovered.snapshot()["safety_state"], "recovery_required")


if __name__ == "__main__":
    unittest.main()
