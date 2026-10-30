"""Strict signature, scope, sequence and typed tombstone validation for v0.2 metadata."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Mapping, Protocol
from urllib.parse import quote

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from .bundles import BundleRejected, BundleValidator, PublicBundleCache, SignatureVerifier
from .distribution_state import VerifiedMetadataPair
from .distribution_state import DistributionSecurityStore
from .producer_v2 import (
    HASH_PROFILE,
    OBJECT_KINDS,
    ReleaseIdentity,
    canonical_json_bytes,
    sha256_hex,
)


CATALOG_PROFILE = "starhelp.public-distribution-catalog.v1"
REVOCATIONS_PROFILE = "starhelp.public-revocations.v1"
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_OBJECT = re.compile(r"^[0-9a-f]{40}$")
_UTC_Z = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z$")
_REASONS = {"rights_withdrawn", "source_correction", "integrity_issue", "policy_change"}


class DistributionMetadataRejected(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class VerifiedCatalogMetadata:
    raw: bytes
    payload: dict[str, Any]
    sequence: int
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class DistributionActivationResult:
    previous_release_id: str | None
    current_release_id: str
    updated: bool
    analysis_status: str
    analysis_reason: str | None


class DistributionMetadataSource(Protocol):
    def fetch_catalog(self) -> bytes: ...

    def fetch_revocations(self) -> bytes: ...

    def fetch_envelope(self, release_id: str) -> bytes: ...


@dataclass(frozen=True, slots=True)
class DistributionMetadataTrust:
    origin_id: str
    channel: str
    consumer_profile: str
    keys: tuple[Mapping[str, Any], ...]
    clock_skew_seconds: int = 300
    supported_capabilities: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if any(not isinstance(item, str) or not item.strip() for item in (
            self.origin_id, self.channel, self.consumer_profile,
        )):
            raise ValueError("distribution trust scope must be explicitly configured")
        if not isinstance(self.clock_skew_seconds, int) or isinstance(
            self.clock_skew_seconds, bool
        ) or not 0 <= self.clock_skew_seconds <= 300:
            raise ValueError("distribution clock skew exceeds the frozen maximum")


class DistributionMetadataVerifier:
    def __init__(self, trust: DistributionMetadataTrust) -> None:
        self._trust = trust

    def verify_pair(self, catalog_raw: bytes, revocations_raw: bytes, *,
                    now: datetime) -> VerifiedMetadataPair:
        if now.tzinfo is None:
            raise ValueError("trusted UTC time must be timezone aware")
        catalog, catalog_sequence, catalog_expiry = self._verify_signed(
            catalog_raw, profile=CATALOG_PROFILE, purpose="synthetic-catalog",
            max_bytes=128 * 1024, now=now,
        )
        self._validate_catalog(catalog)
        verified_catalog = VerifiedCatalogMetadata(
            catalog_raw, catalog, catalog_sequence, catalog_expiry
        )
        return self.verify_revocations(verified_catalog, revocations_raw, now=now)

    def verify_catalog(self, raw: bytes, *, now: datetime) -> VerifiedCatalogMetadata:
        if now.tzinfo is None:
            raise ValueError("trusted UTC time must be timezone aware")
        payload, sequence, expiry = self._verify_signed(
            raw, profile=CATALOG_PROFILE, purpose="synthetic-catalog",
            max_bytes=128 * 1024, now=now,
        )
        self._validate_catalog(payload)
        return VerifiedCatalogMetadata(raw, payload, sequence, expiry)

    def verify_revocations(self, catalog: VerifiedCatalogMetadata, raw: bytes, *,
                           now: datetime) -> VerifiedMetadataPair:
        if now.tzinfo is None:
            raise ValueError("trusted UTC time must be timezone aware")
        catalog_payload = catalog.payload
        reference = catalog_payload["revocation_snapshot"]
        if len(raw) != reference["size_bytes"]:
            raise DistributionMetadataRejected("revocation_snapshot_size_mismatch")
        if sha256_hex(raw) != reference["sha256"]:
            raise DistributionMetadataRejected("revocation_snapshot_digest_mismatch")
        revocations, revocation_sequence, revocation_expiry = self._verify_signed(
            raw, profile=REVOCATIONS_PROFILE,
            purpose="synthetic-revocations", max_bytes=256 * 1024, now=now,
        )
        self._validate_revocations(revocations, catalog_payload,
                                   expected_sequence=reference["sequence"])
        releases = tuple({
            "origin_id": catalog_payload["origin_id"], "channel": catalog_payload["channel"],
            "consumer_profile": catalog_payload["consumer_profile"], "release_id": item["release_id"],
            "envelope_sha256": item["envelope_sha256"],
        } for item in revocations["revoked_releases"])
        objects = tuple({
            "kind": item["kind"], "id": item["id"], "revision": item["revision"],
            "hash_profile": HASH_PROFILE, "content_hash": item["content_hash"],
        } for item in revocations["revoked_public_refs"])
        return VerifiedMetadataPair(
            catalog_raw=catalog.raw, revocations_raw=raw,
            catalog_sequence=catalog.sequence, revocations_sequence=revocation_sequence,
            catalog_expires_at=catalog.expires_at, revocations_expires_at=revocation_expiry,
            releases=releases, objects=objects,
        )

    def _verify_signed(self, raw: bytes, *, profile: str, purpose: str, max_bytes: int,
                       now: datetime) -> tuple[dict[str, Any], int, datetime]:
        if not isinstance(raw, bytes) or not raw or len(raw) > max_bytes:
            raise DistributionMetadataRejected("distribution_metadata_size_invalid")
        try:
            envelope = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_object,
                                  parse_constant=_reject_constant)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
            raise DistributionMetadataRejected("distribution_metadata_json_invalid") from None
        if not isinstance(envelope, dict) or set(envelope) != {"profile", "payload", "signature"}:
            raise DistributionMetadataRejected("distribution_metadata_envelope_invalid")
        if envelope["profile"] != profile or not isinstance(envelope["payload"], dict):
            raise DistributionMetadataRejected("distribution_metadata_profile_mismatch")
        signature = envelope["signature"]
        if not isinstance(signature, dict) or set(signature) != {"algorithm", "key_id", "value"}:
            raise DistributionMetadataRejected("distribution_metadata_signature_invalid")
        if signature["algorithm"] != "Ed25519" or not isinstance(signature["key_id"], str):
            raise DistributionMetadataRejected("distribution_metadata_signature_invalid")
        value = signature["value"]
        if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{128}", value):
            raise DistributionMetadataRejected("distribution_metadata_signature_invalid")
        key = self._find_key(signature["key_id"], purpose, now)
        signed = profile.encode("ascii") + b"\n" + canonical_json_bytes({
            "profile": profile, "algorithm": signature["algorithm"],
            "key_id": signature["key_id"], "payload": envelope["payload"],
        })
        try:
            Ed25519PublicKey.from_public_bytes(bytes.fromhex(key["public_key_hex"])).verify(
                bytes.fromhex(value), signed
            )
        except (InvalidSignature, ValueError):
            raise DistributionMetadataRejected("distribution_signature_invalid") from None
        payload = envelope["payload"]
        schema = CATALOG_PROFILE if profile == CATALOG_PROFILE else REVOCATIONS_PROFILE
        if payload.get("schema_version") != schema:
            raise DistributionMetadataRejected("distribution_metadata_schema_unsupported")
        for field, expected in (
            ("origin_id", self._trust.origin_id), ("channel", self._trust.channel),
            ("consumer_profile", self._trust.consumer_profile),
        ):
            if payload.get(field) != expected:
                raise DistributionMetadataRejected("distribution_metadata_context_mismatch")
        issued_at = _parse_time(payload.get("issued_at"), "issued_at")
        valid_until = _parse_time(payload.get("valid_until"), "valid_until")
        current = now.astimezone(UTC)
        if valid_until <= issued_at or issued_at > current + timedelta(
            seconds=self._trust.clock_skew_seconds
        ) or current > valid_until:
            raise DistributionMetadataRejected("distribution_metadata_time_invalid")
        sequence = payload.get("sequence")
        if not isinstance(sequence, int) or isinstance(sequence, bool) or sequence < 1:
            raise DistributionMetadataRejected("distribution_metadata_sequence_invalid")
        return payload, sequence, valid_until

    def _find_key(self, key_id: str, purpose: str, now: datetime) -> Mapping[str, Any]:
        matches = [key for key in self._trust.keys if key.get("key_id") == key_id]
        if len(matches) != 1:
            raise DistributionMetadataRejected("distribution_signing_key_unknown")
        key = matches[0]
        purposes = key.get("purposes")
        if (key.get("revoked") is not False or not isinstance(purposes, list)
                or purpose not in purposes):
            raise DistributionMetadataRejected("distribution_signing_key_purpose_invalid")
        public_key = key.get("public_key_hex")
        if not isinstance(public_key, str) or not re.fullmatch(r"[0-9a-f]{64}", public_key):
            raise DistributionMetadataRejected("distribution_signing_key_invalid")
        not_before = _parse_time(key.get("not_before"), "key not_before")
        not_after = _parse_time(key.get("not_after"), "key not_after")
        current = now.astimezone(UTC)
        if not_before > current or current > not_after:
            raise DistributionMetadataRejected("distribution_signing_key_expired")
        return key

    def _validate_catalog(self, payload: dict[str, Any]) -> None:
        required = {
            "schema_version", "origin_id", "channel", "consumer_profile", "sequence", "issued_at",
            "valid_until", "active_release_id", "distributions", "revocation_snapshot",
        }
        if set(payload) != required:
            raise DistributionMetadataRejected("distribution_catalog_shape_invalid")
        items = payload["distributions"]
        if not isinstance(items, list) or not 1 <= len(items) <= 2:
            raise DistributionMetadataRejected("distribution_catalog_releases_invalid")
        release_ids: list[str] = []
        rollback_count = 0
        active_count = 0
        for item in items:
            fields = {
                "release_id", "download_path", "envelope_sha256", "size_bytes", "envelope_profile",
                "a_producer", "required_capabilities", "planner", "b_snapshot", "rollback_allowed",
            }
            if not isinstance(item, dict) or set(item) != fields:
                raise DistributionMetadataRejected("distribution_catalog_entry_invalid")
            release_id = item["release_id"]
            if (not isinstance(release_id, str) or not release_id
                    or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
                           for char in release_id)):
                raise DistributionMetadataRejected("distribution_catalog_entry_invalid")
            release_ids.append(release_id)
            if item["download_path"] != f"/v1/distributions/{quote(release_id, safe='')}" \
                    or not isinstance(item["envelope_sha256"], str) \
                    or not _SHA256.fullmatch(item["envelope_sha256"]):
                raise DistributionMetadataRejected("distribution_catalog_entry_invalid")
            if (not isinstance(item["size_bytes"], int) or isinstance(item["size_bytes"], bool)
                    or not 1 <= item["size_bytes"] <= 64 * 1024 * 1024):
                raise DistributionMetadataRejected("distribution_catalog_entry_invalid")
            if item["envelope_profile"] != "starhelp.b-publicbundle-envelope.v1":
                raise DistributionMetadataRejected("distribution_catalog_entry_invalid")
            a = item["a_producer"]
            if (not isinstance(a, dict) or set(a) != {"package", "version", "commit"}
                    or a["package"] != "starhelp-knowledge" or not isinstance(a["version"], str)
                    or not a["version"] or not isinstance(a["commit"], str)
                    or not _GIT_OBJECT.fullmatch(a["commit"])):
                raise DistributionMetadataRejected("distribution_catalog_entry_invalid")
            capabilities = item["required_capabilities"]
            if (not isinstance(capabilities, list)
                    or any(not isinstance(capability, str) or not capability for capability in capabilities)
                    or capabilities != sorted(set(capabilities))
                    or not set(capabilities).issubset(self._trust.supported_capabilities)):
                raise DistributionMetadataRejected("distribution_catalog_entry_invalid")
            planner = item["planner"]
            if (not isinstance(planner, dict) or set(planner) != {
                "profile", "producer_profile", "component_version", "wheel_sha256",
            } or any(not isinstance(value, str) or not value for value in planner.values())
                    or not _SHA256.fullmatch(planner["wheel_sha256"])):
                raise DistributionMetadataRejected("distribution_catalog_entry_invalid")
            snapshot = item["b_snapshot"]
            if (not isinstance(snapshot, dict) or set(snapshot) != {"profile", "producer_commit"}
                    or not isinstance(snapshot["profile"], str) or not snapshot["profile"]
                    or not isinstance(snapshot["producer_commit"], str)
                    or not _GIT_OBJECT.fullmatch(snapshot["producer_commit"])):
                raise DistributionMetadataRejected("distribution_catalog_entry_invalid")
            if not isinstance(item["rollback_allowed"], bool):
                raise DistributionMetadataRejected("distribution_catalog_entry_invalid")
            rollback_count += int(item["rollback_allowed"])
            if release_id == payload["active_release_id"]:
                active_count += 1
                if item["rollback_allowed"]:
                    raise DistributionMetadataRejected("distribution_catalog_entry_invalid")
        if release_ids != sorted(set(release_ids)) or rollback_count > 1 or active_count != 1:
            raise DistributionMetadataRejected("distribution_catalog_releases_invalid")
        revocation = payload["revocation_snapshot"]
        if not isinstance(revocation, dict) or set(revocation) != {
            "path", "sha256", "size_bytes", "sequence",
        }:
            raise DistributionMetadataRejected("distribution_catalog_revocation_invalid")
        if (not isinstance(revocation["path"], str)
                or revocation["path"] != "/v1/distribution-revocations"
                or not isinstance(revocation["sha256"], str)
                or not _SHA256.fullmatch(revocation["sha256"])
                or not isinstance(revocation["size_bytes"], int)
                or isinstance(revocation["size_bytes"], bool)
                or not 1 <= revocation["size_bytes"] <= 256 * 1024
                or not isinstance(revocation["sequence"], int)
                or isinstance(revocation["sequence"], bool) or revocation["sequence"] < 1):
            raise DistributionMetadataRejected("distribution_catalog_revocation_invalid")

    @staticmethod
    def _validate_revocations(payload: dict[str, Any], catalog: dict[str, Any], *,
                              expected_sequence: int) -> None:
        if set(payload) != {
            "schema_version", "origin_id", "channel", "consumer_profile", "sequence", "issued_at",
            "valid_until", "revoked_releases", "revoked_public_refs",
        }:
            raise DistributionMetadataRejected("distribution_revocations_shape_invalid")
        if payload["sequence"] != expected_sequence:
            raise DistributionMetadataRejected("distribution_revocations_sequence_mismatch")
        if payload["sequence"] < 1:
            raise DistributionMetadataRejected("distribution_revocations_sequence_invalid")
        for field in ("origin_id", "channel", "consumer_profile"):
            if payload[field] != catalog[field]:
                raise DistributionMetadataRejected("distribution_revocations_context_mismatch")
        releases = payload["revoked_releases"]
        if not isinstance(releases, list):
            raise DistributionMetadataRejected("distribution_revocations_shape_invalid")
        seen_release_ids: set[str] = set()
        for item in releases:
            if not isinstance(item, dict) or set(item) != {
                "release_id", "envelope_sha256", "reason_code", "effective_at",
            }:
                raise DistributionMetadataRejected("distribution_revocations_entry_invalid")
            if (not isinstance(item["release_id"], str) or not item["release_id"]
                    or item["release_id"] in seen_release_ids
                    or not isinstance(item["envelope_sha256"], str)
                    or not _SHA256.fullmatch(item["envelope_sha256"])
                    or not isinstance(item["reason_code"], str)
                    or item["reason_code"] not in _REASONS):
                raise DistributionMetadataRejected("distribution_revocations_entry_invalid")
            seen_release_ids.add(item["release_id"])
            if _parse_time(item["effective_at"], "effective_at") > _parse_time(
                payload["issued_at"], "issued_at"
            ):
                raise DistributionMetadataRejected("future_revocation_not_supported")
        refs = payload["revoked_public_refs"]
        if not isinstance(refs, list):
            raise DistributionMetadataRejected("distribution_revocations_shape_invalid")
        seen_refs: set[tuple[str, str, int, str]] = set()
        for item in refs:
            if not isinstance(item, dict) or set(item) != {
                "kind", "id", "revision", "content_hash", "reason_code", "effective_at",
            }:
                raise DistributionMetadataRejected("distribution_revocations_entry_invalid")
            revision = item["revision"]
            if (not isinstance(item["kind"], str) or item["kind"] not in OBJECT_KINDS
                    or not isinstance(item["id"], str)
                    or not item["id"] or not isinstance(revision, int) or isinstance(revision, bool)
                    or revision < 1 or not isinstance(item["content_hash"], str)
                    or not _SHA256.fullmatch(item["content_hash"])
                    or not isinstance(item["reason_code"], str)
                    or item["reason_code"] not in _REASONS):
                raise DistributionMetadataRejected("distribution_revocations_entry_invalid")
            identity = (item["kind"], item["id"], revision, item["content_hash"])
            if identity in seen_refs:
                raise DistributionMetadataRejected("distribution_revocations_entry_invalid")
            seen_refs.add(identity)
            if _parse_time(item["effective_at"], "effective_at") > _parse_time(
                payload["issued_at"], "issued_at"
            ):
                raise DistributionMetadataRejected("future_revocation_not_supported")


class DistributionMetadataSynchronizer:
    """Perform the durable pending-catalog then complete-revocation commit sequence."""

    def __init__(self, source: DistributionMetadataSource,
                 verifier: DistributionMetadataVerifier,
                 security_state: DistributionSecurityStore) -> None:
        self._source = source
        self._verifier = verifier
        self._security = security_state

    def sync(self, *, now: datetime | None = None) -> VerifiedMetadataPair:
        self._security.begin_update()
        catalog_raw = self._source.fetch_catalog()
        catalog_time = now or datetime.now(UTC)
        catalog = self._verifier.verify_catalog(catalog_raw, now=catalog_time)
        self._security.accept_verified_catalog(
            sequence=catalog.sequence, digest=sha256_hex(catalog_raw), observed_at=catalog_time,
        )
        revocations_raw = self._source.fetch_revocations()
        complete_time = datetime.now(UTC) if now is None else now
        pair = self._verifier.verify_revocations(catalog, revocations_raw, now=complete_time)
        self._security.commit_verified_pair(pair, observed_at=complete_time)
        return pair

    def sync_and_activate(self, cache: PublicBundleCache, *,
                          signature_verifier: SignatureVerifier,
                          supported_capabilities: frozenset[str],
                          allowed_a_producers: tuple[Mapping[str, Any], ...],
                          allowed_c_components: tuple[Mapping[str, Any], ...],
                          allowed_b_snapshots: tuple[Mapping[str, Any], ...],
                          validator: BundleValidator | None = None,
                          now: datetime | None = None) -> DistributionActivationResult:
        pair = self.sync(now=now)
        catalog = self._verifier.verify_catalog(pair.catalog_raw, now=now or datetime.now(UTC))
        descriptor = next(
            item for item in catalog.payload["distributions"]
            if item["release_id"] == catalog.payload["active_release_id"]
        )
        identity = ReleaseIdentity(
            catalog.payload["origin_id"], catalog.payload["channel"],
            catalog.payload["consumer_profile"], descriptor["release_id"],
            descriptor["envelope_sha256"],
        )
        self._security.assert_release_not_revoked(identity)
        a_tuple = descriptor["a_producer"]
        if not any(all(entry.get(key) == a_tuple[key] for key in ("package", "version", "commit"))
                   for entry in allowed_a_producers):
            raise BundleRejected("distribution_unsupported")
        if descriptor["planner"] not in allowed_c_components:
            raise BundleRejected("distribution_unsupported")
        if descriptor["b_snapshot"] not in allowed_b_snapshots:
            raise BundleRejected("distribution_unsupported")
        if descriptor["release_id"] in cache.available_release_ids():
            cached_digest = sha256_hex(cache.read_release(descriptor["release_id"]))
            if cached_digest != descriptor["envelope_sha256"]:
                raise BundleRejected("immutable_release_identity_conflict")
        raw = self._source.fetch_envelope(descriptor["release_id"])
        if len(raw) != descriptor["size_bytes"] or sha256_hex(raw) != descriptor[
            "envelope_sha256"
        ]:
            raise BundleRejected("distribution_artifact_digest_mismatch")
        parsed_bundle = (validator or BundleValidator()).validate(
            raw, supported_capabilities=supported_capabilities,
            expected_release_id=descriptor["release_id"],
            signature_verifier=signature_verifier,
        )
        envelope = parsed_bundle.payload()
        manifest = envelope.get("manifest")
        if (not isinstance(manifest, dict)
                or manifest.get("distribution_profile") != descriptor["envelope_profile"]
                or manifest.get("index_release_id") != descriptor["release_id"]
                or manifest.get("required_capabilities") != descriptor["required_capabilities"]):
            raise BundleRejected("distribution_tuple_mismatch")
        matching_native = next(
            entry for entry in allowed_a_producers
            if all(entry.get(key) == a_tuple[key] for key in ("package", "version", "commit"))
        )
        if (manifest.get("native_profile") != matching_native["native_profile"]
                or manifest.get("planner_profile") != matching_native["planner_profile"]):
            raise BundleRejected("distribution_tuple_mismatch")
        previous = cache.current_release_id()
        self._security.qualify_artifact(
            identity, pair=pair, allowed=True,
            observed_at=now or datetime.now(UTC),
            artifact_expires_at=min(pair.catalog_expires_at, pair.revocations_expires_at),
        )
        cache.activate(parsed_bundle)
        analyzable = len(raw) <= 2 * 1024 * 1024
        return DistributionActivationResult(
            previous, descriptor["release_id"], previous != descriptor["release_id"],
            "ready" if analyzable else "stored_not_analyzable",
            None if analyzable else "local_payload_too_large",
        )


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON key")
        result[key] = value
    return result


def _reject_constant(_value: str) -> None:
    raise ValueError("non-finite JSON value")


def _parse_time(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not _UTC_Z.fullmatch(value):
        raise DistributionMetadataRejected(f"distribution_metadata_{label}_invalid")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise DistributionMetadataRejected(f"distribution_metadata_{label}_invalid") from None
