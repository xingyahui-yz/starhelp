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

from .producer_v2 import CumulativeRevocations, ReleaseIdentity, sha256_hex
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
    "latest_pair": None, "known_revoked_releases": [], "known_revoked_public_refs": [],
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
                "fresh_until": fresh_until.isoformat().replace("+00:00", "Z"),
                "offline_until": offline_until.isoformat().replace("+00:00", "Z"),
            }
            self._state["qualifications"][key] = record
            self._state["public_epoch"] += 1
            self._write()
            return dict(record)

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
