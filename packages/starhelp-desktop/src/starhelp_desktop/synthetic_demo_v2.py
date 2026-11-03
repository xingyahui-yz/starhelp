from __future__ import annotations

import hashlib
import json
import sys
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from .analysis_v2 import ProducerAnalysisRunnerV2
from .distribution_metadata import (
    CATALOG_PROFILE,
    REVOCATIONS_PROFILE,
    DistributionMetadataSynchronizer,
    DistributionMetadataTrust,
    DistributionMetadataVerifier,
)
from .distribution_state import DistributionSecurityStore, VerifiedMetadataPair
from .lifecycle import ProfileLifecycle
from .planner_v2 import LocalProducerV2Process, bundled_producer_v2_command
from .producer_v2 import (
    ReleaseIdentity,
    canonical_json_bytes,
    build_outer_request_v2,
    build_producer_request_v2,
    load_request_producer_from_source_lock,
)
from .profiles import ProfileRepository
from .reports import ReportLifecycle
from .storage import DataProtector
from .synthetic_demo import SyntheticDemoContext, prepare_synthetic_demo


_ORIGIN_ID = "starhelp.synthetic.fixture"
_CHANNEL = "synthetic-v0.2-demo"
_CONSUMER_PROFILE = "starhelp.local.v0.2"
_POLICY_ID = "starhelp.validity-policy.dev.v1"
_NATIVE_PROFILE = "starhelp.knowledge.native.v0.1-draft"
_C_PROFILE = _CONSUMER_PROFILE
_C_PRODUCER_PROFILE = "starhelp.producers.v0.2"
_C_VERSION = "0.5.1"
_C_WHEEL_SHA256 = "c79ceb58e78d11cf947c0c9f7c5c862ccad8155886fab715a76f7d8977f98322"
_POLICY_CONFIG: dict[str, Any] = {
    "profile": "starhelp.execution-policy.v1",
    "policy_id": _POLICY_ID,
    "revision": 1,
    "allow_production": False,
    "limits": {
        "request_bytes": 8 * 1024 * 1024,
        "response_bytes": 16 * 1024 * 1024,
        "envelope_raw_bytes": 2 * 1024 * 1024,
        "snapshot_raw_bytes": 512 * 1024,
        "catalog_raw_bytes": 128 * 1024,
        "revocations_raw_bytes": 256 * 1024,
        "feedback_bytes": 64 * 1024,
        "feedback_fields": 64,
        "documents_count": 4,
        "json_nodes": 100_000,
        "json_depth": 48,
        "raw_chars": 8_000_000,
    },
    "freshness": {
        "catalog_ttl_seconds": 24 * 60 * 60,
        "refresh_interval_seconds": 6 * 60 * 60,
        "offline_max_seconds": 72 * 60 * 60,
        "clock_skew_seconds": 300,
    },
}


@dataclass(slots=True)
class SyntheticDemoV2Session:
    fixture: SyntheticDemoContext
    security: DistributionSecurityStore
    runner: ProducerAnalysisRunnerV2
    release: ReleaseIdentity
    metadata_pair: VerifiedMetadataPair
    temporary_directory: tempfile.TemporaryDirectory[str]
    policy_config: dict[str, Any]

    @property
    def policy_id(self) -> str:
        return _POLICY_ID

    def current_report_basis(self, report: Any) -> tuple[str, int, frozenset[str]] | None:
        state = self.security.snapshot()
        if (state["safety_state"] != "ready" or state["pending"]
                or state["public_epoch"] != report.public_epoch
                or report.public_basis_sha256 is None):
            return None
        try:
            self.security.assert_release_usable(self.release, now=datetime.now(UTC))
            self.security.assert_public_refs_usable([
                json.loads(value) for value in report.public_refs
            ])
        except (TypeError, ValueError):
            return None
        withdrawn = frozenset(
            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for item in state["known_revoked_public_refs"]
        )
        return report.public_basis_sha256, report.public_epoch, withdrawn

    def save_report(self, report: Any, *, current_snapshot_revision: int) -> Path:
        state = self.security.snapshot()
        withdrawn = frozenset(
            json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            for item in state["known_revoked_public_refs"]
        )
        return self.runner.save_current(
            report,
            current_snapshot_revision=current_snapshot_revision,
            current_release_id=self.release.release_id,
            known_withdrawn_refs=withdrawn,
        )


@dataclass(frozen=True, slots=True)
class SyntheticDemoV2Prepared:
    session: SyntheticDemoV2Session
    request: dict[str, Any]
    execution_policy_path: Path
    execution_policy_sha256: str


class _MemoryMetadataSource:
    def __init__(self, catalog: bytes, revocations: bytes) -> None:
        self._catalog = catalog
        self._revocations = revocations

    def fetch_catalog(self) -> bytes:
        return self._catalog

    def fetch_revocations(self) -> bytes:
        return self._revocations


def prepare_synthetic_demo_v2(
    profiles: ProfileRepository,
    lifecycle: ProfileLifecycle,
    private_store: Any,
    *,
    protector: DataProtector | None = None,
    temporary_root: Path | None = None,
    feedback: dict[str, Any] | None = None,
) -> SyntheticDemoV2Prepared:
    """Prepare a no-network, production-disabled v0.2 replay over pinned fixtures."""
    fixture = prepare_synthetic_demo(profiles, feedback=feedback)
    legacy = fixture.request["producer_request"]
    now = datetime.now(UTC).replace(microsecond=0)
    issued = _format_utc(now)
    valid_until = _format_utc(now + timedelta(hours=4))
    metadata_private_key = Ed25519PrivateKey.generate()
    metadata_public_key = metadata_private_key.public_key().public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw,
    )
    metadata_key_id = "starhelp-synthetic-v0.2-demo-ephemeral"
    release_id = legacy["public_bundle"]["expected_release_id"]
    planner = {
        "profile": _C_PROFILE,
        "producer_profile": _C_PRODUCER_PROFILE,
        "component_version": _C_VERSION,
        "wheel_sha256": _C_WHEEL_SHA256,
    }
    a_producer = {
        "package": "starhelp-knowledge",
        "version": "0.3.0",
        "commit": legacy["public_bundle"]["producer_commit"],
    }
    b_snapshot = {
        "profile": legacy["account_snapshot"]["format_profile"],
        "producer_commit": legacy["account_snapshot"]["producer_commit"],
    }
    public_bundle_raw = legacy["public_bundle"]["raw_json"].encode("utf-8")
    descriptor = {
        "release_id": release_id,
        "download_path": f"/v1/distributions/{quote(release_id, safe='')}",
        "envelope_sha256": hashlib.sha256(public_bundle_raw).hexdigest(),
        "size_bytes": len(public_bundle_raw),
        "envelope_profile": legacy["public_bundle"]["format_profile"],
        "a_producer": a_producer,
        "required_capabilities": ["starhelp.knowledge-distribution.v1"],
        "planner": planner,
        "b_snapshot": b_snapshot,
        "rollback_allowed": False,
    }
    revocations_payload = {
        "schema_version": REVOCATIONS_PROFILE,
        "origin_id": _ORIGIN_ID,
        "channel": _CHANNEL,
        "consumer_profile": _CONSUMER_PROFILE,
        "sequence": 1,
        "issued_at": issued,
        "valid_until": valid_until,
        "revoked_releases": [],
        "revoked_public_refs": [],
    }
    revocations_raw = _sign_metadata(
        REVOCATIONS_PROFILE, revocations_payload, metadata_key_id, metadata_private_key,
    )
    catalog_payload = {
        "schema_version": CATALOG_PROFILE,
        "origin_id": _ORIGIN_ID,
        "channel": _CHANNEL,
        "consumer_profile": _CONSUMER_PROFILE,
        "sequence": 1,
        "issued_at": issued,
        "valid_until": valid_until,
        "active_release_id": release_id,
        "distributions": [descriptor],
        "revocation_snapshot": {
            "path": (f"/v1/distribution-revocations?profile={_CONSUMER_PROFILE}"
                     f"&channel={quote(_CHANNEL, safe='')}") ,
            "sha256": hashlib.sha256(revocations_raw).hexdigest(),
            "size_bytes": len(revocations_raw),
            "sequence": 1,
        },
    }
    catalog_raw = _sign_metadata(
        CATALOG_PROFILE, catalog_payload, metadata_key_id, metadata_private_key,
    )
    metadata_key = {
        "key_id": metadata_key_id,
        "public_key_hex": metadata_public_key.hex(),
        "purposes": ["synthetic-catalog", "synthetic-revocations"],
        "not_before": _format_utc(now - timedelta(minutes=5)),
        "not_after": valid_until,
        "revoked": False,
    }
    verifier = DistributionMetadataVerifier(DistributionMetadataTrust(
        _ORIGIN_ID,
        _CHANNEL,
        _CONSUMER_PROFILE,
        (metadata_key,),
        supported_capabilities=frozenset(descriptor["required_capabilities"]),
    ))
    if temporary_root is not None:
        temporary_root.mkdir(parents=True, exist_ok=True)
    temporary_directory = tempfile.TemporaryDirectory(
        prefix="starhelp-v02-synthetic-", dir=temporary_root,
    )
    temporary_root = Path(temporary_directory.name)
    security = DistributionSecurityStore(
        temporary_root / "distribution-state.bin", protector=protector,
    )
    pair = DistributionMetadataSynchronizer(
        _MemoryMetadataSource(catalog_raw, revocations_raw), verifier, security,
    ).sync(now=now)
    release = ReleaseIdentity(
        _ORIGIN_ID, _CHANNEL, _CONSUMER_PROFILE, release_id, descriptor["envelope_sha256"],
    )
    security.qualify_artifact(
        release, pair=pair, allowed=True, observed_at=now,
        artifact_expires_at=min(pair.catalog_expires_at, pair.revocations_expires_at),
    )
    source_lock = _source_lock_path()
    request_producer = load_request_producer_from_source_lock(source_lock)
    public_snapshot = legacy["account_snapshot"]
    public_key = serialization.load_pem_public_key(
        _fixture_public_key_path().read_bytes()
    ).public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    policy_config = json.loads(json.dumps(_POLICY_CONFIG))
    policy_config["keys"] = [
        {
            "key_id": fixture.bundle.payload()["manifest"]["signing_key_id"],
            "public_key_hex": public_key.hex(),
            "purposes": ["synthetic-release"],
            "not_before": _format_utc(now - timedelta(minutes=5)),
            "not_after": valid_until,
            "revoked": False,
        },
        metadata_key,
    ]
    policy_config["allowed_a_producers"] = [{
        **a_producer,
        "envelope_profile": legacy["public_bundle"]["format_profile"],
        "native_profile": _NATIVE_PROFILE,
        "planner_profile": _CONSUMER_PROFILE,
    }]
    policy_config["allowed_b_snapshots"] = [b_snapshot]
    policy_config["allowed_request_producers"] = [request_producer]
    policy_config["allowed_c_components"] = [planner]
    selected_artifact = {
        "a_producer": a_producer,
        "planner": planner,
        "b_snapshot": b_snapshot,
    }
    basis, _basis_digest, public_documents = security.create_public_basis(
        release,
        selected_artifact=selected_artifact,
        policy_config=policy_config,
        evaluation_time=now,
    )
    request_id = legacy["request_id"]
    inner = build_producer_request_v2(
        request_id=request_id,
        request_producer=request_producer,
        public_bundle={
            "producer": legacy["public_bundle"]["producer"],
            "producer_commit": legacy["public_bundle"]["producer_commit"],
            "format_profile": legacy["public_bundle"]["format_profile"],
            "expected_release_id": release_id,
            "raw_json": legacy["public_bundle"]["raw_json"],
            "sha256": descriptor["envelope_sha256"],
        },
        account_snapshot=public_snapshot,
        authorization_context=legacy["authorization_context"],
        task=legacy["task"],
        evaluation_time=issued,
        public_basis=basis,
        public_documents=public_documents,
        feedback=legacy.get("feedback", feedback),
    )
    outer = build_outer_request_v2(
        request_id=request_id,
        authorization_generation=fixture.profile.generation,
        profile_id=str(fixture.profile.profile_id),
        snapshot_revision=fixture.snapshot.revision,
        producer_request=inner,
    )
    policy_context = {
        "origin_id": _ORIGIN_ID,
        "channel": _CHANNEL,
        "consumer_profile": _CONSUMER_PROFILE,
        "public_epoch": basis["epoch"],
        "basis_sha256": inner["public_basis_sha256"],
        "evaluation_time": issued,
        "known_revoked_releases": security.snapshot()["known_revoked_releases"],
        "known_revoked_public_refs": security.snapshot()["known_revoked_public_refs"],
        "safety_state": "ready",
    }
    execution_policy = {"config": policy_config, "context": policy_context}
    policy_raw = canonical_json_bytes(execution_policy) + b"\n"
    policy_path = temporary_root / "execution-policy.json"
    policy_path.write_bytes(policy_raw)
    session = SyntheticDemoV2Session(
        fixture, security,
        ProducerAnalysisRunnerV2(
            LocalProducerV2Process(
                bundled_producer_v2_command(),
                policy_path,
                hashlib.sha256(policy_raw).hexdigest(),
            ),
            ReportLifecycle(private_store, lifecycle),
            security,
        ),
        release, pair, temporary_directory, policy_config,
    )
    return SyntheticDemoV2Prepared(
        session, outer, policy_path, hashlib.sha256(policy_raw).hexdigest(),
    )


def _sign_metadata(profile: str, payload: dict[str, Any], key_id: str,
                   private_key: Ed25519PrivateKey) -> bytes:
    signed = {"profile": profile, "algorithm": "Ed25519", "key_id": key_id, "payload": payload}
    signature = private_key.sign(profile.encode("ascii") + b"\n" + canonical_json_bytes(signed))
    envelope = {
        "profile": profile,
        "payload": payload,
        "signature": {"algorithm": "Ed25519", "key_id": key_id, "value": signature.hex()},
    }
    return canonical_json_bytes(envelope) + b"\n"


def _format_utc(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def _package_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _source_lock_path() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and isinstance(frozen_root, str):
        return Path(frozen_root) / "source-lock-v0.2.json"
    return _package_root() / "packaging" / "source-lock-v0.2.json"


def _fixture_public_key_path() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and isinstance(frozen_root, str):
        return Path(frozen_root) / "demo-fixtures" / "fixture-ed25519-public.pem"
    return _package_root() / "tests" / "fixtures" / "producer-interop-s3" / "fixture-ed25519-public.pem"


