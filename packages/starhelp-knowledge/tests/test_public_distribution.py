from __future__ import annotations

import hashlib
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from io import StringIO
from typing import Any

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from starhelp_knowledge import KnowledgeDatabase, KnowledgeService
from starhelp_knowledge.cli import main as cli_main
from starhelp_knowledge.errors import Conflict, IntegrityFailure, InvalidPayload
from starhelp_knowledge.http import KnowledgeApplication
from starhelp_knowledge.policy import TokenAuthenticator
from starhelp_knowledge.public_distribution import (
    CATALOG_PROFILE,
    CONSUMER_PROFILE,
    NATIVE_HASH_PROFILE,
    REVOCATIONS_PROFILE,
    PublicDistributionStore,
    build_p1_native_test_vectors,
    sign_metadata,
    verify_metadata,
)

PACKAGE = Path(__file__).parents[1]
S3_ARTIFACT = PACKAGE / "artifacts" / "interop-min-v0.1-s3" / "starhelp-interop-min-v0.1-s3.bpublic.json"
S3_PUBLIC_KEY = PACKAGE / "artifacts" / "interop-min-v0.1-s3" / "fixture-ed25519-public.pem"
S3_KEY_ID = "starhelp-fixture-ed25519-v1"
METADATA_KEY_ID = "starhelp-synthetic-metadata-v1"
_FIXTURE_SEED = bytes.fromhex("5f8a08cc63c14b9723a9c44a70c142e9133b1825adf0a9478d26582144e9c701")
_ISSUED = "2026-10-30T00:00:00Z"
_VALID_UNTIL = "2026-10-30T12:00:00Z"


class PublicDistributionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(dir=PACKAGE / "tests")
        self.root = Path(self.tempdir.name)
        self.metadata_key = Ed25519PrivateKey.from_private_bytes(_FIXTURE_SEED)
        self.trusted_keys = {
            METADATA_KEY_ID: {
                "public_key": self.metadata_key.public_key().public_bytes_raw(),
                "purposes": ["synthetic-catalog", "synthetic-revocations"],
                "not_before": "2026-10-29T00:00:00Z",
                "not_after": "2026-10-31T00:00:00Z",
                "revoked": False,
            }
        }
        self.raw_artifact = S3_ARTIFACT.read_bytes()
        self.envelope = json.loads(self.raw_artifact.decode("utf-8"))
        self.release_id = self.envelope["manifest"]["index_release_id"]
        self.store = PublicDistributionStore(self.root / "distribution")
        self.store.store_artifact(self.release_id, self.raw_artifact)
        self.revocations_payload = self._revocations(sequence=1)
        self.revocations_raw = sign_metadata(
            REVOCATIONS_PROFILE, self.revocations_payload,
            signing_private_key=self.metadata_key, key_id=METADATA_KEY_ID,
        )
        self.catalog_payload = self._catalog(sequence=1, revocations_raw=self.revocations_raw)
        self.catalog_raw = sign_metadata(
            CATALOG_PROFILE, self.catalog_payload,
            signing_private_key=self.metadata_key, key_id=METADATA_KEY_ID,
        )

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _revocations(self, *, sequence: int, refs: list[dict[str, object]] | None = None) -> dict[str, object]:
        return {
            "schema_version": REVOCATIONS_PROFILE,
            "origin_id": "fixture-origin",
            "channel": "synthetic",
            "consumer_profile": CONSUMER_PROFILE,
            "sequence": sequence,
            "issued_at": _ISSUED,
            "valid_until": _VALID_UNTIL,
            "revoked_releases": [],
            "revoked_public_refs": sorted(refs or [], key=lambda row: (
                row["kind"], row["id"], row["revision"], row["hash_profile"], row["content_hash"],
            )),
        }

    def _catalog(self, *, sequence: int, revocations_raw: bytes) -> dict[str, object]:
        digest = hashlib.sha256(self.raw_artifact).hexdigest()
        return {
            "schema_version": CATALOG_PROFILE,
            "origin_id": "fixture-origin",
            "channel": "synthetic",
            "consumer_profile": CONSUMER_PROFILE,
            "sequence": sequence,
            "issued_at": _ISSUED,
            "valid_until": _VALID_UNTIL,
            "active_release_id": self.release_id,
            "distributions": [{
                "release_id": self.release_id,
                "download_path": f"/v1/distributions/{self.release_id}",
                "envelope_sha256": digest,
                "size_bytes": len(self.raw_artifact),
                "envelope_profile": "starhelp.b-publicbundle-envelope.v1",
                "a_producer": {"package": "starhelp-knowledge", "version": "0.3.0", "commit": "dcb1e3ee220b85229bedc6c79d72ebe495825f37"},
                "required_capabilities": ["starhelp.knowledge-distribution.v1"],
                "planner": {
                    "profile": "starhelp.local.v0.2", "producer_profile": "starhelp.producers.v0.1",
                    "component_version": "0.4.0",
                    "wheel_sha256": "3b5b8de8f2ef71cd07f1cfb7724cb0a1564f316860232b58728386d52c47aea2",
                },
                "b_snapshot": {
                    "profile": "starhelp.desktop.snapshot.interop-min.v0.1",
                    "producer_commit": "103741e02c90ac672017f783058bdd8dacae982e",
                },
                "rollback_allowed": False,
            }],
            "revocation_snapshot": {
                "path": "/v1/distribution-revocations?profile=starhelp.local.v0.2&channel=synthetic",
                "sha256": hashlib.sha256(revocations_raw).hexdigest(),
                "size_bytes": len(revocations_raw),
                "sequence": sequence,
            },
        }

    def _publish(self, catalog_payload: dict[str, object], revocations_raw: bytes) -> tuple[bytes, bytes]:
        revocations_payload = json.loads(revocations_raw.decode("utf-8"))["payload"]
        catalog_payload = dict(catalog_payload)
        catalog_payload["revocation_snapshot"] = {
            "path": f"/v1/distribution-revocations?profile={CONSUMER_PROFILE}&channel=synthetic",
            "sha256": hashlib.sha256(revocations_raw).hexdigest(),
            "size_bytes": len(revocations_raw),
            "sequence": revocations_payload["sequence"],
        }
        catalog_raw = sign_metadata(CATALOG_PROFILE, catalog_payload, signing_private_key=self.metadata_key, key_id=METADATA_KEY_ID)
        self.store.publish_metadata(catalog_raw, revocations_raw, trusted_keys=self.trusted_keys)
        return catalog_raw, revocations_raw

    def test_signed_metadata_uses_profile_domain_and_purpose_bound_trust(self) -> None:
        verified = verify_metadata(
            self.catalog_raw, expected_profile=CATALOG_PROFILE,
            purpose="synthetic-catalog", trusted_keys=self.trusted_keys,
        )
        self.assertEqual(verified["active_release_id"], self.release_id)
        with self.assertRaises(IntegrityFailure):
            verify_metadata(
                self.catalog_raw, expected_profile=CATALOG_PROFILE,
                purpose="synthetic-revocations", trusted_keys=self.trusted_keys,
            )
        with self.assertRaises(InvalidPayload):
            verify_metadata(
                b'{"profile":"x","profile":"y"}', expected_profile=CATALOG_PROFILE,
                purpose="synthetic-catalog", trusted_keys=self.trusted_keys,
            )

    def test_schema_rejects_boolean_sequence_and_future_revocation(self) -> None:
        invalid = dict(self.catalog_payload, sequence=True)
        with self.assertRaises(InvalidPayload):
            sign_metadata(CATALOG_PROFILE, invalid, signing_private_key=self.metadata_key, key_id=METADATA_KEY_ID)
        ref = {
            "kind": "evidence", "id": "ev_fixture_s3_0001", "revision": 1,
            "hash_profile": NATIVE_HASH_PROFILE,
            "content_hash": "31fd2606d894719b33a1e552d3655fc8a712bfbd7375fa6d7021c33413b129a1",
            "reason_code": "source_correction", "effective_at": "2026-10-31T00:00:00Z",
        }
        with self.assertRaises(InvalidPayload):
            sign_metadata(REVOCATIONS_PROFILE, self._revocations(sequence=2, refs=[ref]), signing_private_key=self.metadata_key, key_id=METADATA_KEY_ID)

    def test_store_keeps_exact_bytes_and_rejects_same_sequence_conflict(self) -> None:
        result = self.store.publish_metadata(self.catalog_raw, self.revocations_raw, trusted_keys=self.trusted_keys)
        self.assertEqual(result["allow_production"], False)
        self.assertEqual(self.store.get_catalog(profile=CONSUMER_PROFILE, channel="synthetic"), self.catalog_raw)
        self.assertEqual(self.store.get_revocations(profile=CONSUMER_PROFILE, channel="synthetic"), self.revocations_raw)
        self.assertEqual(self.store.get_artifact(self.release_id), self.raw_artifact)
        changed = dict(self.catalog_payload, valid_until="2026-10-30T06:00:00Z")
        conflict_raw = sign_metadata(CATALOG_PROFILE, changed, signing_private_key=self.metadata_key, key_id=METADATA_KEY_ID)
        with self.assertRaises(Conflict):
            self.store.publish_metadata(conflict_raw, self.revocations_raw, trusted_keys=self.trusted_keys)

    def test_revocation_snapshots_are_cumulative(self) -> None:
        self.store.publish_metadata(self.catalog_raw, self.revocations_raw, trusted_keys=self.trusted_keys)
        ref = {
            "kind": "evidence", "id": "ev_fixture_s3_0001", "revision": 1,
            "hash_profile": NATIVE_HASH_PROFILE,
            "content_hash": "31fd2606d894719b33a1e552d3655fc8a712bfbd7375fa6d7021c33413b129a1",
            "reason_code": "source_correction", "effective_at": _ISSUED,
        }
        rev2 = sign_metadata(REVOCATIONS_PROFILE, self._revocations(sequence=2, refs=[ref]), signing_private_key=self.metadata_key, key_id=METADATA_KEY_ID)
        self._publish(dict(self.catalog_payload, sequence=2), rev2)
        rev3 = sign_metadata(REVOCATIONS_PROFILE, self._revocations(sequence=3), signing_private_key=self.metadata_key, key_id=METADATA_KEY_ID)
        catalog3 = self._catalog(sequence=3, revocations_raw=rev3)
        catalog3["revocation_snapshot"]["sha256"] = hashlib.sha256(rev3).hexdigest()
        catalog3["revocation_snapshot"]["size_bytes"] = len(rev3)
        with self.assertRaises(IntegrityFailure):
            self._publish(catalog3, rev3)

    def test_http_serves_immutable_raw_bytes_and_readiness(self) -> None:
        self.store.publish_metadata(self.catalog_raw, self.revocations_raw, trusted_keys=self.trusted_keys)
        service = KnowledgeService(KnowledgeDatabase(self.root / "knowledge.sqlite3"))
        app = KnowledgeApplication(service, TokenAuthenticator(), distribution_store=self.store, instance_id="fixture-instance")

        def get(path: str, query: str = "") -> tuple[str, dict[str, str], bytes]:
            result: dict[str, Any] = {}

            def start(status: str, headers: list[tuple[str, str]]) -> None:
                result["status"] = status
                result["headers"] = dict(headers)

            environ = {"REQUEST_METHOD": "GET", "PATH_INFO": path, "QUERY_STRING": query, "wsgi.input": io.BytesIO(b""), "CONTENT_LENGTH": "0"}
            body = b"".join(app(environ, start))
            return result["status"], result["headers"], body

        status, headers, body = get("/v1/distributions", f"profile={CONSUMER_PROFILE}&channel=synthetic")
        self.assertEqual(status, "200 OK")
        self.assertEqual(body, self.catalog_raw)
        self.assertEqual(headers["ETag"], f'"{hashlib.sha256(self.catalog_raw).hexdigest()}"')
        self.assertEqual(get("/v1/distribution-revocations", f"profile={CONSUMER_PROFILE}&channel=synthetic")[2], self.revocations_raw)
        self.assertEqual(get(f"/v1/distributions/{self.release_id}")[2], self.raw_artifact)
        ready = json.loads(get("/health/ready")[2].decode("utf-8"))
        self.assertEqual(ready["status"], "ready")
        self.assertEqual(ready["instance_id"], "fixture-instance")
        self.assertEqual(ready["distribution_catalog"], "available")

    def test_native_p1_vectors_come_from_a_verifiers_original_hash_fields(self) -> None:
        public_key = serialization.load_pem_public_key(S3_PUBLIC_KEY.read_bytes()).public_bytes_raw()
        vectors = build_p1_native_test_vectors(
            self.envelope, trusted_public_keys={S3_KEY_ID: public_key}, trusted_key_id=S3_KEY_ID,
        )
        self.assertEqual(vectors["profile"], NATIVE_HASH_PROFILE)
        self.assertEqual(vectors["record"]["content_hash"], "70158aecb170994a012865a0866a10d0340d7689e4b88bf056fdab8248f14f70")
        self.assertEqual(vectors["evidence"]["content_hash"], "31fd2606d894719b33a1e552d3655fc8a712bfbd7375fa6d7021c33413b129a1")
        self.assertEqual(vectors["evidence"]["revision"], 1)

    def test_serve_rejects_non_loopback_bind(self) -> None:
        self.assertEqual(cli_main(["serve", "--database", str(self.root / "db.sqlite3"), "--host", "0.0.0.0"]), 2)

    def test_controlled_publisher_verifies_and_stores_synthetic_fixture(self) -> None:
        private_key_path = self.root / "metadata-private.pem"
        private_key_path.write_bytes(self.metadata_key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        ))
        config_path = self.root / "publish.json"
        config_path.write_text(json.dumps({
            "envelope_paths": {self.release_id: str(S3_ARTIFACT)},
            "envelope_trusted_public_key": str(S3_PUBLIC_KEY),
            "envelope_trusted_key_id": S3_KEY_ID,
            "metadata_key_id": METADATA_KEY_ID,
            "catalog_payload": self.catalog_payload,
            "revocations_payload": self.revocations_payload,
        }), encoding="utf-8")
        output_store = self.root / "published"
        with redirect_stdout(StringIO()):
            code = cli_main([
                "publish-public-distribution", "--config", str(config_path),
                "--metadata-private-key", str(private_key_path), "--output-store", str(output_store),
            ])
        self.assertEqual(code, 0)
        published = PublicDistributionStore(output_store)
        self.assertEqual(published.get_artifact(self.release_id), self.raw_artifact)
        self.assertEqual(published.readiness(), ("available", self.release_id))


if __name__ == "__main__":
    unittest.main()
