"""Durable public distribution safety state, separate from the active bundle cache."""

from __future__ import annotations

import json
import os
import tempfile
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence, TypeVar

from .producer_v2 import (
    BASIS_PROFILE,
    CumulativeRevocations,
    PublicObjectIdentity,
    ReleaseIdentity,
    build_public_basis_sha256,
    canonical_json_bytes,
    sha256_hex,
    validate_public_basis,
)
from .storage import DataProtector, WindowsDpapiProtector


@dataclass(frozen=True, slots=True)
class VerifiedMetadataPair:
    """Pair of raw metadata documents after caller-side signature/context validation."""

    catalog_raw: bytes
    revocations_raw: bytes
    catalog_sequence: int
    revocations_sequence: int
    catalog_expires_at: datetime
    revocations_expires_at: datetime
    releases: tuple[Mapping[str, Any], ...] = ()
    objects: tuple[Mapping[str, Any], ...] = ()

    def __post_init__(self) -> None:
        for name in ("catalog_sequence", "revocations_sequence"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be a positive integer")
        for name in ("catalog_expires_at", "revocations_expires_at"):
            value = getattr(self, name)
            if value.tzinfo is None:
                raise ValueError(f"{name} must be timezone aware")
        if not self.catalog_raw or not self.revocations_raw:
            raise ValueError("verified metadata documents must not be empty")

    @property
    def catalog_sha256(self) -> str:
        return sha256_hex(self.catalog_raw)

    @property
    def revocations_sha256(self) -> str:
        return sha256_hex(self.revocations_raw)

    def as_pair(self) -> dict[str, str]:
        return {"catalog_sha256": self.catalog_sha256,
                "revocations_sha256": self.revocations_sha256}


_EMPTY_STATE: dict[str, Any] = {
    "schema_id": "DistributionSecurityState", "schema_version": "0.2",
    "safety_state": "pending", "pending": False, "public_epoch": 1,
    "high_water": {"catalog_sequence": 0, "catalog_sha256": None,
                   "revocations_sequence": 0, "revocations_sha256": None},
    "latest_pair": None, "metadata_documents": {"catalog": None, "revocations": None},
    "known_revoked_releases": [], "known_revoked_public_refs": [],
    "qualifications": {}, "last_trusted_utc": None,
}
_T = TypeVar("_T")


class DistributionSecurityStore:
    """Atomic local state for metadata high water, tombstones and per-artifact qualification.

    Metadata signature verification stays at the sync boundary; only a verified pair value can
    advance this store. Startup with an interrupted update enters recovery_required.
    """

    CLOCK_SKEW_SECONDS = 300
    DEV_OFFLINE_SECONDS = 72 * 60 * 60

    def __init__(self, path: Path, *, protector: DataProtector | None = None) -> None:
        self.path = path.resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._protector = protector or WindowsDpapiProtector()
        self._lock = threading.RLock()
        self._state = self._read()
        self._mono_checkpoint: tuple[float, datetime] | None = None
        if self._state.get("pending"):
            self._state["safety_state"] = "recovery_required"
            self._write()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return json.loads(json.dumps(self._state, ensure_ascii=False))

    def run_if_epoch_current(self, epoch: int, operation: Callable[[], _T]) -> _T:
        """Hold the same safety lock through a caller's final stage/save operation."""
        if not isinstance(epoch, int) or isinstance(epoch, bool) or epoch < 1:
            raise ValueError("public epoch must be a positive integer")
        with self._lock:
            try:
                self._check_clock(datetime.now(UTC))
            except ValueError:
                raise ValueError("clock_untrusted") from None
            if self._state["safety_state"] != "ready" or self._state["pending"]:
                raise ValueError(self._state["safety_state"])
            if self._state["public_epoch"] != epoch:
                raise ValueError("public_basis_changed")
            return operation()

    def begin_update(self) -> None:
        with self._lock:
            self._state["pending"] = True
            self._state["safety_state"] = "pending"
            self._write()

    def accept_verified_catalog(self, *, sequence: int, digest: str,
                                observed_at: datetime) -> int:
        """Persist authenticated catalog high-water before requesting its revocation snapshot."""
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            raise ValueError("catalog sequence must be a positive integer")
        if (not isinstance(digest, str) or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)):
            raise ValueError("catalog raw digest must be lowercase SHA-256")
        if observed_at.tzinfo is None:
            raise ValueError("trusted observation time must be timezone aware")
        with self._lock:
            self._check_clock(observed_at)
            if not self._state["pending"]:
                raise ValueError("catalog high-water can advance only during a pending sync")
            high_water = self._state["high_water"]
            old_sequence, old_digest = high_water["catalog_sequence"], high_water["catalog_sha256"]
            if sequence < old_sequence:
                raise ValueError("catalog metadata sequence rollback")
            if sequence == old_sequence and old_sequence and digest != old_digest:
                raise ValueError("catalog metadata sequence digest conflict")
            changed = sequence != old_sequence or digest != old_digest
            high_water["catalog_sequence"] = sequence
            high_water["catalog_sha256"] = digest
            self._state["safety_state"] = "pending"
            if changed:
                self._state["public_epoch"] += 1
            self._write()
            return self._state["public_epoch"]

    def commit_verified_pair(self, pair: VerifiedMetadataPair, *, observed_at: datetime) -> int:
        if observed_at.tzinfo is None:
            raise ValueError("trusted observation time must be timezone aware")
        with self._lock:
            self._check_clock(observed_at)
            prior = json.loads(json.dumps(self._state))
            hwm = self._state["high_water"]
            new_hwm = {
                "catalog_sequence": pair.catalog_sequence,
                "catalog_sha256": pair.catalog_sha256,
                "revocations_sequence": pair.revocations_sequence,
                "revocations_sha256": pair.revocations_sha256,
            }
            for kind in ("catalog", "revocations"):
                seq_key, hash_key = f"{kind}_sequence", f"{kind}_sha256"
                old_seq, new_seq = hwm[seq_key], new_hwm[seq_key]
                if new_seq < old_seq:
                    raise ValueError(f"{kind} metadata sequence rollback")
                if new_seq == old_seq and old_seq and new_hwm[hash_key] != hwm[hash_key]:
                    raise ValueError(f"{kind} metadata sequence digest conflict")
            ledger = CumulativeRevocations(
                self._state["known_revoked_releases"], self._state["known_revoked_public_refs"]
            )
            before = (ledger.releases, ledger.objects)
            ledger.merge(releases=pair.releases, objects=pair.objects)
            changed = (before != (ledger.releases, ledger.objects)
                       or new_hwm != hwm or self._state["latest_pair"] != pair.as_pair())
            self._state["high_water"] = new_hwm
            self._state["latest_pair"] = pair.as_pair()
            self._state["metadata_documents"] = {
                "catalog": pair.catalog_raw.decode("utf-8"),
                "revocations": pair.revocations_raw.decode("utf-8"),
            }
            self._state["known_revoked_releases"] = list(ledger.releases)
            self._state["known_revoked_public_refs"] = list(ledger.objects)
            self._state["last_trusted_utc"] = observed_at.astimezone(UTC).isoformat().replace(
                "+00:00", "Z"
            )
            self._state["pending"] = False
            self._state["safety_state"] = "ready"
            if changed:
                self._state["public_epoch"] += 1
            try:
                self._write()
            except OSError:
                self._state = prior
                self._state["pending"] = True
                self._state["safety_state"] = "recovery_required"
                try:
                    self._write()
                except OSError:
                    pass
                raise
            self._mono_checkpoint = (time.monotonic(), observed_at.astimezone(UTC))
            return self._state["public_epoch"]

    def qualify_artifact(self, identity: ReleaseIdentity, *, pair: VerifiedMetadataPair,
                         allowed: bool, observed_at: datetime,
                         artifact_expires_at: datetime | None = None,
                         catalog_ttl_seconds: int = 24 * 60 * 60,
                         policy_offline_seconds: int = DEV_OFFLINE_SECONDS) -> dict[str, Any]:
        if not allowed:
            raise ValueError("artifact is not admitted by the verified catalog")
        if (observed_at.tzinfo is None or not isinstance(catalog_ttl_seconds, int)
                or isinstance(catalog_ttl_seconds, bool) or not 1 <= catalog_ttl_seconds <= 86400
                or not isinstance(policy_offline_seconds, int) or isinstance(policy_offline_seconds, bool)
                or policy_offline_seconds < 1):
            raise ValueError("qualification time and policy limit are required")
        with self._lock:
            if self._state["safety_state"] != "ready" or self._state["pending"]:
                raise ValueError("distribution safety state does not permit qualification")
            if self._state["latest_pair"] != pair.as_pair():
                raise ValueError("artifact qualification must reference the current verified pair")
            ledger = CumulativeRevocations(
                self._state["known_revoked_releases"], self._state["known_revoked_public_refs"]
            )
            if ledger.release_is_revoked(identity):
                raise ValueError("release is revoked")
            key = f"{identity.origin_id}|{identity.channel}|{identity.consumer_profile}|{identity.release_id}|{identity.envelope_sha256}"
            existing = self._state["qualifications"].get(key)
            if existing:
                return dict(existing)
            qualified = observed_at.astimezone(UTC)
            fresh_until = min(
                qualified + timedelta(seconds=catalog_ttl_seconds),
                pair.catalog_expires_at.astimezone(UTC),
                pair.revocations_expires_at.astimezone(UTC),
            )
            offline_until = qualified + timedelta(seconds=min(
                policy_offline_seconds, self.DEV_OFFLINE_SECONDS
            ))
            if artifact_expires_at is not None:
                if artifact_expires_at.tzinfo is None:
                    raise ValueError("artifact expiry must be timezone aware")
                offline_until = min(offline_until, artifact_expires_at.astimezone(UTC))
            record = {
                "release_identity": identity.as_dict(), "raw_sha256": identity.envelope_sha256,
                "pair": pair.as_pair(), "qualified_at": qualified.isoformat().replace("+00:00", "Z"),
                "metadata_documents": {
                    "catalog": pair.catalog_raw.decode("utf-8"),
                    "revocations": pair.revocations_raw.decode("utf-8"),
                },
                "fresh_until": fresh_until.isoformat().replace("+00:00", "Z"),
                "offline_until": offline_until.isoformat().replace("+00:00", "Z"),
            }
            self._state["qualifications"][key] = record
            self._state["public_epoch"] += 1
            self._write()
            return dict(record)

    def public_documents_for(self, identity: ReleaseIdentity) -> dict[str, dict[str, str]]:
        """Return the selected qualification pair and latest pair, deduplicated by raw digest."""
        with self._lock:
            key = self._qualification_key(identity)
            qualification = self._state["qualifications"].get(key)
            latest_pair = self._state["latest_pair"]
            latest_docs = self._state["metadata_documents"]
            if not qualification or not latest_pair or not latest_docs["catalog"] or not latest_docs[
                "revocations"
            ]:
                raise ValueError("public basis documents are unavailable")
            documents: dict[str, dict[str, str]] = {}
            for pair, raw_docs in (
                (qualification["pair"], qualification["metadata_documents"]),
                (latest_pair, latest_docs),
            ):
                for profile, digest_key, content_key in (
                    ("starhelp.public-distribution-catalog.v1", "catalog_sha256", "catalog"),
                    ("starhelp.public-revocations.v1", "revocations_sha256", "revocations"),
                ):
                    raw_text = raw_docs[content_key]
                    if sha256_hex(raw_text.encode("utf-8")) != pair[digest_key]:
                        raise ValueError("persisted public metadata document digest mismatch")
                    documents[pair[digest_key]] = {"profile": profile, "raw_json": raw_text}
            if len(documents) > 4:
                raise ValueError("public basis document limit exceeded")
            return documents

    def create_public_basis(self, identity: ReleaseIdentity, *,
                            selected_artifact: Mapping[str, Any],
                            policy_config: Mapping[str, Any],
                            evaluation_time: datetime) -> tuple[dict[str, Any], str,
                                                               dict[str, dict[str, str]]]:
        if evaluation_time.tzinfo is None:
            raise ValueError("public basis evaluation time must be timezone aware")
        policy_hash = sha256_hex(canonical_json_bytes(dict(policy_config)))
        with self._lock:
            state = self._state
            if state["safety_state"] != "ready" or state["pending"]:
                raise ValueError(state["safety_state"])
            qualification = state["qualifications"].get(self._qualification_key(identity))
            latest_pair = state["latest_pair"]
            if qualification is None or latest_pair is None:
                raise ValueError("selected public artifact has no complete qualification")
            config_pair = qualification["pair"]
            basis = {
                "profile": BASIS_PROFILE,
                "origin_id": identity.origin_id,
                "channel": identity.channel,
                "consumer_profile": identity.consumer_profile,
                "policy_id": policy_config["policy_id"],
                "policy_revision": policy_config["revision"],
                "policy_sha256": policy_hash,
                "epoch": state["public_epoch"],
                "selected_artifact": {
                    "release_id": identity.release_id,
                    "envelope_sha256": identity.envelope_sha256,
                    "a_producer": dict(selected_artifact["a_producer"]),
                    "planner": dict(selected_artifact["planner"]),
                    "b_snapshot": dict(selected_artifact["b_snapshot"]),
                },
                "qualification_pair": config_pair,
                "latest_pair": latest_pair,
                "qualified_at": qualification["qualified_at"],
                "offline_until": qualification["offline_until"],
                "evaluation_time": evaluation_time.astimezone(UTC).isoformat().replace("+00:00", "Z"),
                "state": self.effective_state(identity, now=evaluation_time),
            }
            documents = self.public_documents_for(identity)
            digest = build_public_basis_sha256(basis)
            validate_public_basis(basis, digest, documents)
            return basis, digest, documents

    @staticmethod
    def _qualification_key(identity: ReleaseIdentity) -> str:
        return f"{identity.origin_id}|{identity.channel}|{identity.consumer_profile}|{identity.release_id}|{identity.envelope_sha256}"

    def effective_state(self, identity: ReleaseIdentity, *, now: datetime) -> str:
        if now.tzinfo is None:
            raise ValueError("evaluation time must be timezone aware")
        with self._lock:
            try:
                self._check_clock(now)
            except ValueError:
                return "clock_untrusted"
            if self._state["safety_state"] != "ready":
                return self._state["safety_state"]
            ledger = CumulativeRevocations(
                self._state["known_revoked_releases"], self._state["known_revoked_public_refs"]
            )
            if ledger.release_is_revoked(identity):
                return "revoked"
            key = f"{identity.origin_id}|{identity.channel}|{identity.consumer_profile}|{identity.release_id}|{identity.envelope_sha256}"
            qualification = self._state["qualifications"].get(key)
            if not qualification:
                return "revocation_unknown"
            evaluation = now.astimezone(UTC)
            fresh_until = datetime.fromisoformat(qualification["fresh_until"].replace("Z", "+00:00"))
            offline_until = datetime.fromisoformat(qualification["offline_until"].replace("Z", "+00:00"))
            if evaluation <= fresh_until:
                return "fresh"
            if evaluation <= offline_until:
                return "offline_stale"
            return "expired"

    def assert_release_usable(self, identity: ReleaseIdentity, *, now: datetime) -> str:
        state = self.effective_state(identity, now=now)
        if state not in {"fresh", "offline_stale"}:
            raise ValueError(state)
        return state

    def assert_release_not_revoked(self, identity: ReleaseIdentity) -> None:
        with self._lock:
            if self._state["safety_state"] != "ready" or self._state["pending"]:
                raise ValueError(self._state["safety_state"])
            ledger = CumulativeRevocations(
                self._state["known_revoked_releases"], self._state["known_revoked_public_refs"]
            )
            if ledger.release_is_revoked(identity):
                raise ValueError("revoked")

    def assert_public_refs_usable(self, identities: Sequence[Mapping[str, Any]]) -> None:
        with self._lock:
            if self._state["safety_state"] != "ready" or self._state["pending"]:
                raise ValueError(self._state["safety_state"])
            ledger = CumulativeRevocations(
                self._state["known_revoked_releases"], self._state["known_revoked_public_refs"]
            )
            for item in identities:
                identity = PublicObjectIdentity(**item)
                if ledger.object_is_revoked(identity):
                    raise ValueError("revoked_public_reference")

    def _check_clock(self, now: datetime) -> None:
        current = now.astimezone(UTC)
        monotonic_now = time.monotonic()
        if self._mono_checkpoint is not None:
            previous_mono, previous_utc = self._mono_checkpoint
            elapsed = monotonic_now - previous_mono
            wall_elapsed = (current - previous_utc).total_seconds()
            if abs(wall_elapsed - elapsed) > self.CLOCK_SKEW_SECONDS:
                self._state["safety_state"] = "clock_untrusted"
                self._state["pending"] = False
                self._write()
                raise ValueError("clock_untrusted")
        last = self._state.get("last_trusted_utc")
        if last:
            previous = datetime.fromisoformat(last.replace("Z", "+00:00"))
            if current + timedelta(seconds=self.CLOCK_SKEW_SECONDS) < previous:
                self._state["safety_state"] = "clock_untrusted"
                self._state["pending"] = False
                self._write()
                raise ValueError("clock_untrusted")
        self._mono_checkpoint = (monotonic_now, current)

    def _read(self) -> dict[str, Any]:
        try:
            encrypted = self.path.read_bytes()
        except FileNotFoundError:
            return json.loads(json.dumps(_EMPTY_STATE))
        if len(encrypted) > 16 * 1024 * 1024:
            raise ValueError("distribution security state is oversized")
        if not encrypted.startswith(b"SHDPAPI1"):
            raise ValueError("distribution security state encryption envelope is invalid")
        raw = self._protector.unprotect(encrypted[8:])
        if len(raw) > 16 * 1024 * 1024:
            raise ValueError("distribution security state is oversized")
        value = json.loads(raw.decode("utf-8"))
        if not isinstance(value, dict) or value.get("schema_id") != "DistributionSecurityState" or value.get(
            "schema_version"
        ) != "0.2":
            raise ValueError("distribution security state schema is invalid")
        required = set(_EMPTY_STATE)
        if set(value) != required:
            raise ValueError("distribution security state has missing or unknown fields")
        if value["safety_state"] not in {"pending", "ready", "recovery_required", "clock_untrusted"}:
            raise ValueError("distribution security state value is invalid")
        return value

    def _write(self) -> None:
        plaintext = json.dumps(self._state, ensure_ascii=False, sort_keys=True,
                               separators=(",", ":"), allow_nan=False).encode("utf-8")
        body = b"SHDPAPI1" + self._protector.protect(plaintext)
        descriptor, name = tempfile.mkstemp(prefix=".distribution-state.", suffix=".tmp",
                                            dir=self.path.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(body)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
