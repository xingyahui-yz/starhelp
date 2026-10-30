"""Build reviewable, test-only S4.1 public distribution metadata fixtures."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import quote

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
REPOSITORY_ROOT = PACKAGE_ROOT.parents[1]
sys.path.insert(0, str(PACKAGE_ROOT / "src"))

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey  # noqa: E402

from starhelp_knowledge import __version__  # noqa: E402
from starhelp_knowledge.distribution import DISTRIBUTION_CAPABILITY, PLANNER_CAPABILITY, verify_distribution_envelope  # noqa: E402
from starhelp_knowledge.fixture import FIXTURE_KEY_ID, _FIXTURE_SEED  # noqa: E402
from starhelp_knowledge.public_distribution import (  # noqa: E402
    CATALOG_PROFILE,
    CONSUMER_PROFILE,
    NATIVE_HASH_PROFILE,
    REVOCATIONS_PROFILE,
    build_p1_native_test_vectors,
    canonical_json_bytes,
    sign_metadata,
    verify_metadata,
)

S3_ARTIFACT_RELATIVE = Path("packages/starhelp-knowledge/artifacts/interop-min-v0.1-s3/starhelp-interop-min-v0.1-s3.bpublic.json")
S3_ARTIFACT_SHA256 = "f777d05bdb269b2e92a612e4fc96a9ad076f9d5b2bc36760c34c1209ff323772"
METADATA_KEY_ID = "starhelp-synthetic-metadata-v1"
OLD_A_COMMIT = "dcb1e3ee220b85229bedc6c79d72ebe495825f37"
OLD_B_SNAPSHOT_COMMIT = "103741e02c90ac672017f783058bdd8dacae982e"
OLD_C_WHEEL_SHA256 = "3b5b8de8f2ef71cd07f1cfb7724cb0a1564f316860232b58728386d52c47aea2"
OLD_RELEASE_ID = "rel_fixture_s3_0001"
REPLACEMENT_ID = "rel_synthetic_replacement_unavailable_0002"
_UNAVAILABLE_BYTES = b"synthetic replacement artifact intentionally absent\n"


def git_text(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPOSITORY_ROOT, check=True, capture_output=True, text=True).stdout.strip()


def utc_text(value: datetime) -> str:
    return value.astimezone(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def write_raw(directory: Path, name: str, raw: bytes) -> None:
    (directory / name).write_bytes(raw)


def write_json(directory: Path, name: str, value: object) -> None:
    write_raw(directory, name, canonical_json_bytes(value) + b"\n")


def distribution_entry(release_id: str, digest: str, size: int) -> dict[str, object]:
    """Reuse only the explicitly labeled legacy S3 tuple in these transport fixtures."""
    return {
        "release_id": release_id,
        "download_path": f"/v1/distributions/{release_id}",
        "envelope_sha256": digest,
        "size_bytes": size,
        "envelope_profile": "starhelp.b-publicbundle-envelope.v1",
        "a_producer": {"package": "starhelp-knowledge", "version": "0.3.0", "commit": OLD_A_COMMIT},
        "required_capabilities": [DISTRIBUTION_CAPABILITY],
        "planner": {
            "profile": "starhelp.local.v0.2",
            "producer_profile": "starhelp.producers.v0.1",
            "component_version": "0.4.0",
            "wheel_sha256": OLD_C_WHEEL_SHA256,
        },
        "b_snapshot": {"profile": "starhelp.desktop.snapshot.interop-min.v0.1", "producer_commit": OLD_B_SNAPSHOT_COMMIT},
        "rollback_allowed": False,
    }


def revocation_payload(sequence: int, issued_at: str, valid_until: str, *, vectors: dict[str, object] | None = None) -> dict[str, object]:
    revoked_releases: list[dict[str, object]] = []
    revoked_public_refs: list[dict[str, object]] = []
    if vectors is not None:
        record = vectors["record"]
        evidence = vectors["evidence"]
        revoked_releases.append({
            "release_id": OLD_RELEASE_ID,
            "envelope_sha256": hashlib.sha256((REPOSITORY_ROOT / S3_ARTIFACT_RELATIVE).read_bytes()).hexdigest(),
            "reason_code": "source_correction",
            "effective_at": issued_at,
        })
        revoked_public_refs.extend([
            {
                "kind": record["kind"], "id": record["id"], "revision": record["revision"],
                "hash_profile": NATIVE_HASH_PROFILE, "content_hash": record["content_hash"],
                "reason_code": "integrity_issue", "effective_at": issued_at,
            },
            {
                "kind": "evidence", "id": evidence["id"], "revision": 1,
                "hash_profile": NATIVE_HASH_PROFILE, "content_hash": evidence["content_hash"],
                "reason_code": "source_correction", "effective_at": issued_at,
            },
        ])
    revoked_releases.sort(key=lambda row: (row["release_id"], row["envelope_sha256"]))
    revoked_public_refs.sort(key=lambda row: (row["kind"], row["id"], row["revision"], row["hash_profile"], row["content_hash"]))
    return {
        "schema_version": REVOCATIONS_PROFILE,
        "origin_id": "starhelp.synthetic.fixture",
        "channel": "synthetic",
        "consumer_profile": CONSUMER_PROFILE,
        "sequence": sequence,
        "issued_at": issued_at,
        "valid_until": valid_until,
        "revoked_releases": revoked_releases,
        "revoked_public_refs": revoked_public_refs,
    }


def catalog_payload(
    *, sequence: int, active_release_id: str, entry: dict[str, object],
    revocations_raw: bytes, issued_at: str, valid_until: str,
) -> dict[str, object]:
    rev_payload = json.loads(revocations_raw.decode("utf-8"))["payload"]
    channel = "synthetic"
    return {
        "schema_version": CATALOG_PROFILE,
        "origin_id": "starhelp.synthetic.fixture",
        "channel": channel,
        "consumer_profile": CONSUMER_PROFILE,
        "sequence": sequence,
        "issued_at": issued_at,
        "valid_until": valid_until,
        "active_release_id": active_release_id,
        "distributions": [entry],
        "revocation_snapshot": {
            "path": f"/v1/distribution-revocations?profile={CONSUMER_PROFILE}&channel={quote(channel, safe='')}",
            "sha256": hashlib.sha256(revocations_raw).hexdigest(),
            "size_bytes": len(revocations_raw),
            "sequence": rev_payload["sequence"],
        },
    }


def build(output: Path) -> dict[str, object]:
    if output.exists():
        raise FileExistsError(f"immutable output directory already exists: {output}")
    source_commit = git_text("rev-parse", "HEAD")
    builder_path = Path(__file__).resolve().relative_to(REPOSITORY_ROOT).as_posix()
    builder_blob = git_text("rev-parse", f"HEAD:{builder_path}")
    s3_path = REPOSITORY_ROOT / S3_ARTIFACT_RELATIVE
    s3_raw = s3_path.read_bytes()
    s3_digest = hashlib.sha256(s3_raw).hexdigest()
    if s3_digest != S3_ARTIFACT_SHA256:
        raise ValueError("frozen S3 artifact digest does not match the recorded baseline")
    envelope = json.loads(s3_raw.decode("utf-8"))
    public_pem_path = s3_path.parent / "fixture-ed25519-public.pem"
    public_key = serialization.load_pem_public_key(public_pem_path.read_bytes())
    public_key_bytes = public_key.public_bytes_raw()
    verify_distribution_envelope(
        envelope,
        trusted_public_keys={FIXTURE_KEY_ID: public_key_bytes},
        trusted_key_id=FIXTURE_KEY_ID,
        supported_distribution_capabilities={DISTRIBUTION_CAPABILITY},
        supported_planner_capabilities={PLANNER_CAPABILITY},
    )
    vectors = build_p1_native_test_vectors(
        envelope, trusted_public_keys={FIXTURE_KEY_ID: public_key_bytes}, trusted_key_id=FIXTURE_KEY_ID,
    )
    private_key = Ed25519PrivateKey.from_private_bytes(_FIXTURE_SEED)
    now = datetime.now(UTC).replace(microsecond=0)
    issued_at, valid_until = utc_text(now), utc_text(now + timedelta(hours=12))

    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent) as temporary_name:
        temporary = Path(temporary_name)
        (temporary / "replacement-unavailable").mkdir()
        (temporary / "same-sequence-conflict").mkdir()
        rev1_payload = revocation_payload(1, issued_at, valid_until)
        rev1_raw = sign_metadata(REVOCATIONS_PROFILE, rev1_payload, signing_private_key=private_key, key_id=METADATA_KEY_ID)
        normal_catalog = catalog_payload(
            sequence=1, active_release_id=OLD_RELEASE_ID,
            entry=distribution_entry(OLD_RELEASE_ID, s3_digest, len(s3_raw)),
            revocations_raw=rev1_raw, issued_at=issued_at, valid_until=valid_until,
        )
        normal_catalog_raw = sign_metadata(CATALOG_PROFILE, normal_catalog, signing_private_key=private_key, key_id=METADATA_KEY_ID)
        conflict_catalog = dict(normal_catalog, valid_until=utc_text(now + timedelta(hours=6)))
        conflict_catalog_raw = sign_metadata(CATALOG_PROFILE, conflict_catalog, signing_private_key=private_key, key_id=METADATA_KEY_ID)

        rev2_payload = revocation_payload(2, issued_at, valid_until, vectors=vectors)
        rev2_raw = sign_metadata(REVOCATIONS_PROFILE, rev2_payload, signing_private_key=private_key, key_id=METADATA_KEY_ID)
        replacement_entry = distribution_entry(REPLACEMENT_ID, hashlib.sha256(_UNAVAILABLE_BYTES).hexdigest(), len(_UNAVAILABLE_BYTES))
        replacement_catalog = catalog_payload(
            sequence=2, active_release_id=REPLACEMENT_ID, entry=replacement_entry,
            revocations_raw=rev2_raw, issued_at=issued_at, valid_until=valid_until,
        )
        replacement_catalog_raw = sign_metadata(CATALOG_PROFILE, replacement_catalog, signing_private_key=private_key, key_id=METADATA_KEY_ID)

        trust = {METADATA_KEY_ID: {
            "public_key": private_key.public_key().public_bytes_raw(),
            "purposes": ["synthetic-catalog", "synthetic-revocations"],
            "not_before": "1970-01-01T00:00:00Z", "not_after": "9999-12-31T23:59:59Z", "revoked": False,
        }}
        verify_metadata(normal_catalog_raw, expected_profile=CATALOG_PROFILE, purpose="synthetic-catalog", trusted_keys=trust)
        verify_metadata(rev1_raw, expected_profile=REVOCATIONS_PROFILE, purpose="synthetic-revocations", trusted_keys=trust)
        verify_metadata(conflict_catalog_raw, expected_profile=CATALOG_PROFILE, purpose="synthetic-catalog", trusted_keys=trust)
        verify_metadata(replacement_catalog_raw, expected_profile=CATALOG_PROFILE, purpose="synthetic-catalog", trusted_keys=trust)
        verify_metadata(rev2_raw, expected_profile=REVOCATIONS_PROFILE, purpose="synthetic-revocations", trusted_keys=trust)

        write_raw(temporary, "catalog-normal-seq-0001.json", normal_catalog_raw)
        write_raw(temporary, "revocations-normal-seq-0001.json", rev1_raw)
        write_raw(temporary / "same-sequence-conflict", "catalog-seq-0001-different-bytes.json", conflict_catalog_raw)
        write_raw(temporary / "replacement-unavailable", "catalog-seq-0002.json", replacement_catalog_raw)
        write_raw(temporary / "replacement-unavailable", "revocations-seq-0002.json", rev2_raw)
        write_json(temporary, "p1-native-test-vectors.json", vectors)
        write_json(temporary, "transport-only-s3-reference.json", {
            "artifact_path": S3_ARTIFACT_RELATIVE.as_posix(),
            "artifact_sha256": s3_digest,
            "release_id": OLD_RELEASE_ID,
            "source_commit": OLD_A_COMMIT,
            "producer_version": "0.3.0",
            "compatibility_label": "legacy-transport-only-not-a-final-producer-tuple",
        })
        write_raw(temporary, "fixture-ed25519-public.pem", public_pem_path.read_bytes())
        write_json(temporary, "receipt.json", {
            "fixture_only": True,
            "allow_production": False,
            "builder_source_commit": source_commit,
            "builder_module": builder_path,
            "builder_blob": builder_blob,
            "builder_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
            "package_version": __version__,
            "metadata_key_id": METADATA_KEY_ID,
            "metadata_purposes": ["synthetic-catalog", "synthetic-revocations"],
            "s3_source_artifact_sha256": s3_digest,
            "normal_release_id": OLD_RELEASE_ID,
            "unavailable_replacement_release_id": REPLACEMENT_ID,
            "replacement_expected_missing_bytes_sha256": hashlib.sha256(_UNAVAILABLE_BYTES).hexdigest(),
        })
        (temporary / "README.md").write_bytes((
            "# S4.1 synthetic public distribution fixtures\n\n"
            "All signed metadata and examples are synthetic. The normal catalog references the frozen S3 envelope as a legacy transport-only fixture. Its A 0.3.0, B1, and C 0.4.0 values are not a final compatibility tuple. The second catalog/revocations pair cumulatively revokes that old release and one exact native public ref, then names a deliberately absent synthetic replacement artifact; a client fetching it should observe an unavailable-artifact response while preserving the tombstone. The same-sequence directory contains a validly signed catalog with different raw bytes at sequence 1 and must be rejected as a sequence conflict.\n\n"
            "`p1-native-test-vectors.json` records one record and evidence hash from A's own verified native content-hash fields. Evidence revision 1 is taken only from the matching verified planner projection. The deterministic test key is not production trust. This package build hard-disables production metadata publishing. No real account, source collector, remote model, or production key was used. `receipt.json` identifies the exact builder commit/blob and frozen source digest.\n"
        ).encode("utf-8"))
        checksums = []
        for path in sorted(temporary.rglob("*")):
            if path.is_file():
                checksums.append(f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.relative_to(temporary).as_posix()}")
        (temporary / "SHA256SUMS.txt").write_bytes(("\n".join(checksums) + "\n").encode("ascii"))
        temporary.rename(output)
    return {
        "output": str(output), "builder_source_commit": source_commit,
        "normal_catalog_sha256": hashlib.sha256(normal_catalog_raw).hexdigest(),
        "normal_revocations_sha256": hashlib.sha256(rev1_raw).hexdigest(),
        "replacement_catalog_sha256": hashlib.sha256(replacement_catalog_raw).hexdigest(),
        "replacement_revocations_sha256": hashlib.sha256(rev2_raw).hexdigest(),
        "fixture_only": True,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = build(args.output.resolve())
    except FileExistsError:
        print("immutable fixture output directory already exists", file=sys.stderr)
        return 2
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
