from __future__ import annotations

import hashlib
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

from starhelp_desktop.producer_v2 import (
    CumulativeRevocations,
    PublicObjectIdentity,
    ReleaseIdentity,
    build_outer_request_v2,
    build_producer_request_v2,
    build_public_basis_sha256,
    load_request_producer_from_source_lock,
    validate_public_basis,
)
from starhelp_desktop.distribution_state import DistributionSecurityStore, VerifiedMetadataPair
from starhelp_desktop.planner_v2 import _parse_response_v2
from starhelp_desktop.local_backend import KnowledgeBackendController, LocalBackendConfig
from starhelp_desktop.producer_v2 import canonical_json_bytes


class _IdentityProtector:
    def protect(self, data: bytes) -> bytes:
        return data

    def unprotect(self, data: bytes) -> bytes:
        return data


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
                        "component_version": "0.5.0", "wheel_sha256": "5" * 64},
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

    def test_object_revision_rejects_boolean(self) -> None:
        with self.assertRaises(ValueError):
            PublicObjectIdentity("entity", "x", True,
                                 "starhelp.a-native-content-field.v1", "a" * 64)

    def test_source_lock_loader_binds_artifact_and_dependency_digests(self) -> None:
        deps = [{
            "path": "packages/starhelp-desktop/src/starhelp_desktop/producer_v2.py",
            "git_blob": "1" * 40, "raw_sha256": "2" * 64,
        }]
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
            lock["dependencies"] = [{**deps[0], "raw_sha256": "4" * 64}]
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
        bundle_raw = '{"release_id":"release-1"}'
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
            task={"goal": "synthetic"}, evaluation_time="2026-10-30T01:00:00Z",
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
            "planner_version": "0.5.0",
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
        first = VerifiedMetadataPair(
            b"catalog-1", b"revocations-1", 1, 1,
            now + timedelta(hours=24), now + timedelta(hours=24),
        )
        second = VerifiedMetadataPair(
            b"catalog-2", b"revocations-2", 2, 2,
            now + timedelta(hours=30), now + timedelta(hours=30),
        )
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            path = Path(directory) / "distribution-state.bin"
            store = DistributionSecurityStore(path, protector=_IdentityProtector())
            store.begin_update()
            store.commit_verified_pair(first, observed_at=now)
            qualification = store.qualify_artifact(
                identity, pair=first, allowed=True, observed_at=now,
            )
            basis_epoch = store.snapshot()["public_epoch"]
            store.begin_update()
            refreshed_at = now + timedelta(seconds=1)
            changed_epoch = store.commit_verified_pair(second, observed_at=refreshed_at)
            with self.assertRaisesRegex(ValueError, "public_basis_changed"):
                store.run_if_epoch_current(basis_epoch, lambda: None)
            unchanged = store.qualify_artifact(
                identity, pair=second, allowed=True, observed_at=refreshed_at,
            )
            self.assertEqual(unchanged["qualified_at"], qualification["qualified_at"])
            self.assertEqual(store.run_if_epoch_current(changed_epoch, lambda: "saved"), "saved")
            self.assertEqual(store.effective_state(identity, now=now), "fresh")
            reopened = DistributionSecurityStore(path, protector=_IdentityProtector())
            self.assertEqual(reopened.snapshot()["safety_state"], "ready")
            reopened.begin_update()
            recovered = DistributionSecurityStore(path, protector=_IdentityProtector())
            self.assertEqual(recovered.snapshot()["safety_state"], "recovery_required")


if __name__ == "__main__":
    unittest.main()
