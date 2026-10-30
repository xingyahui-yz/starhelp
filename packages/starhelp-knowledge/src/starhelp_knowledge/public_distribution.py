"""Strict signed catalog/revocation metadata and immutable public artifacts.

This is the publishing side of the local v0.2 contract. It stores the exact
bytes it signs or receives and never regenerates an artifact during download.
Trust and signing keys are supplied by the caller; this module stores neither.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from urllib.parse import quote

from starhelp_knowledge.errors import Conflict, IntegrityFailure, InvalidPayload, NotFound, UnsupportedCapability

CATALOG_PROFILE = "starhelp.public-distribution-catalog.v1"
REVOCATIONS_PROFILE = "starhelp.public-revocations.v1"
CONSUMER_PROFILE = "starhelp.local.v0.2"
NATIVE_HASH_PROFILE = "starhelp.a-native-content-field.v1"
MAX_CATALOG_BYTES = 128 * 1024
MAX_REVOCATIONS_BYTES = 256 * 1024
MAX_ENVELOPE_ANALYSIS_BYTES = 2 * 1024 * 1024
MAX_ENVELOPE_STORE_BYTES = 64 * 1024 * 1024
MAX_JSON_NODES = 100_000
MAX_JSON_DEPTH = 48
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_RELEASE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,199}$")
_REASON_CODES = {"rights_withdrawn", "source_correction", "integrity_issue", "policy_change"}
_RECORD_KINDS = {"entity", "knowledge", "stage", "template", "variant", "troubleshooting", "resource", "evidence"}
_KEY_PURPOSES = {
    "synthetic-release", "synthetic-catalog", "synthetic-revocations",
    "production-release", "production-catalog", "production-revocations",
}
_CATALOG_FIELDS = {
    "schema_version", "origin_id", "channel", "consumer_profile", "sequence", "issued_at",
    "valid_until", "active_release_id", "distributions", "revocation_snapshot",
}
_DISTRIBUTION_FIELDS = {
    "release_id", "download_path", "envelope_sha256", "size_bytes", "envelope_profile",
    "a_producer", "required_capabilities", "planner", "b_snapshot", "rollback_allowed",
}
_REVOCATIONS_FIELDS = {
    "schema_version", "origin_id", "channel", "consumer_profile", "sequence", "issued_at",
    "valid_until", "revoked_releases", "revoked_public_refs",
}


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
    except (TypeError, ValueError):
        raise InvalidPayload("metadata contains a non-JSON value") from None


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise InvalidPayload("metadata contains a duplicate JSON key")
        result[key] = value
    return result


def _check_tree(value: Any, *, depth: int = 0, count: list[int] | None = None) -> None:
    if count is None:
        count = [0]
    count[0] += 1
    if count[0] > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
        raise InvalidPayload("metadata exceeds structural limits")
    if isinstance(value, dict):
        for key, child in value.items():
            if not isinstance(key, str):
                raise InvalidPayload("metadata object keys must be strings")
            _check_tree(child, depth=depth + 1, count=count)
    elif isinstance(value, list):
        for child in value:
            _check_tree(child, depth=depth + 1, count=count)
    elif isinstance(value, float):
        import math

        if not math.isfinite(value):
            raise InvalidPayload("metadata contains a non-finite number")
    elif value is not None and not isinstance(value, str | int | bool):
        raise InvalidPayload("metadata contains an unsupported value")


def strict_json_loads(raw: bytes, *, max_bytes: int) -> Any:
    if not isinstance(raw, bytes) or len(raw) > max_bytes:
        raise InvalidPayload("metadata exceeds byte limit")
    try:
        text = raw.decode("utf-8", errors="strict")
        value = json.loads(
            text,
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=lambda _: (_ for _ in ()).throw(InvalidPayload("metadata contains a non-JSON number")),
        )
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise InvalidPayload("metadata is not strict UTF-8 JSON") from None
    _check_tree(value)
    return value


def _exact(value: Any, fields: set[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise InvalidPayload(f"{label} has an invalid field set")
    return value


def _string(value: Any, label: str, *, max_length: int = 200) -> str:
    if type(value) is not str or not value or len(value) > max_length:
        raise InvalidPayload(f"{label} must be a non-empty string")
    return value


def _integer(value: Any, label: str, *, minimum: int = 1, maximum: int | None = None) -> int:
    if type(value) is not int or value < minimum or (maximum is not None and value > maximum):
        raise InvalidPayload(f"{label} is outside its allowed integer range")
    return value


def _hex(value: Any, label: str, *, length: int = 64) -> str:
    pattern = _HEX64 if length == 64 else _HEX40
    if type(value) is not str or pattern.fullmatch(value) is None:
        raise InvalidPayload(f"{label} must be lowercase hexadecimal")
    return value


def parse_utc(value: Any, label: str) -> datetime:
    if type(value) is not str or not re.fullmatch(r"\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,6})?Z", value):
        raise InvalidPayload(f"{label} must be a UTC timestamp ending in Z")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00").astimezone(UTC)
    except ValueError:
        raise InvalidPayload(f"{label} is not a valid timestamp") from None


def _validate_context(payload: dict[str, Any]) -> None:
    _string(payload["origin_id"], "origin_id")
    _string(payload["channel"], "channel", max_length=80)
    if payload["consumer_profile"] != CONSUMER_PROFILE:
        raise UnsupportedCapability("unsupported consumer profile")
    _integer(payload["sequence"], "sequence")
    issued = parse_utc(payload["issued_at"], "issued_at")
    valid_until = parse_utc(payload["valid_until"], "valid_until")
    if valid_until <= issued:
        raise InvalidPayload("valid_until must be later than issued_at")
    if valid_until - issued > timedelta(hours=24):
        raise InvalidPayload("metadata validity may not exceed the development TTL")


def _validate_distribution(entry: Any) -> dict[str, Any]:
    item = _exact(entry, _DISTRIBUTION_FIELDS, "distribution")
    release_id = _string(item["release_id"], "release_id")
    if _RELEASE_ID.fullmatch(release_id) is None or release_id in {".", ".."}:
        raise InvalidPayload("release_id is not a safe path identity")
    if item["download_path"] != f"/v1/distributions/{release_id}":
        raise InvalidPayload("download_path must be the fixed release route")
    _hex(item["envelope_sha256"], "envelope_sha256")
    _integer(item["size_bytes"], "size_bytes", maximum=MAX_ENVELOPE_STORE_BYTES)
    if item["envelope_profile"] != "starhelp.b-publicbundle-envelope.v1":
        raise UnsupportedCapability("unsupported envelope profile")
    a_producer = _exact(item["a_producer"], {"package", "version", "commit"}, "a_producer")
    if a_producer["package"] != "starhelp-knowledge":
        raise UnsupportedCapability("unsupported A package")
    _string(a_producer["version"], "A producer version", max_length=80)
    _hex(a_producer["commit"], "A producer commit", length=40)
    capabilities = item["required_capabilities"]
    if (not isinstance(capabilities, list) or not capabilities
        or any(type(value) is not str or not value for value in capabilities)
        or capabilities != sorted(set(capabilities))):
        raise InvalidPayload("required_capabilities must be unique and sorted")
    planner = _exact(item["planner"], {"profile", "producer_profile", "component_version", "wheel_sha256"}, "planner")
    for key in ("profile", "producer_profile", "component_version"):
        _string(planner[key], f"planner {key}", max_length=160)
    _hex(planner["wheel_sha256"], "planner wheel_sha256")
    snapshot = _exact(item["b_snapshot"], {"profile", "producer_commit"}, "b_snapshot")
    _string(snapshot["profile"], "B snapshot profile", max_length=160)
    _hex(snapshot["producer_commit"], "B producer commit", length=40)
    if type(item["rollback_allowed"]) is not bool:
        raise InvalidPayload("rollback_allowed must be boolean")
    return item


def validate_catalog_payload(payload: Any) -> dict[str, Any]:
    data = _exact(payload, _CATALOG_FIELDS, "catalog payload")
    if data["schema_version"] != CATALOG_PROFILE:
        raise UnsupportedCapability("unsupported catalog schema")
    _validate_context(data)
    active = _string(data["active_release_id"], "active_release_id")
    distributions = data["distributions"]
    if not isinstance(distributions, list) or not 1 <= len(distributions) <= 2:
        raise InvalidPayload("catalog must list one or two distributions")
    entries = [_validate_distribution(entry) for entry in distributions]
    ids = [item["release_id"] for item in entries]
    if len(ids) != len(set(ids)) or ids.count(active) != 1:
        raise InvalidPayload("catalog release identities are duplicate or active release is missing")
    if next(item for item in entries if item["release_id"] == active)["rollback_allowed"]:
        raise InvalidPayload("active release cannot be a rollback target")
    if sum(bool(item["rollback_allowed"]) for item in entries) > 1:
        raise InvalidPayload("catalog may contain at most one rollback target")
    if ids != sorted(ids):
        raise InvalidPayload("catalog distributions must be sorted by release_id")
    snapshot = _exact(data["revocation_snapshot"], {"path", "sha256", "size_bytes", "sequence"}, "revocation_snapshot")
    expected_path = f"/v1/distribution-revocations?profile={CONSUMER_PROFILE}&channel={quote(data['channel'], safe='')}"
    if snapshot["path"] != expected_path:
        raise InvalidPayload("revocation snapshot path must be fixed for this profile and channel")
    _hex(snapshot["sha256"], "revocation snapshot sha256")
    _integer(snapshot["size_bytes"], "revocation snapshot size_bytes", maximum=MAX_REVOCATIONS_BYTES)
    _integer(snapshot["sequence"], "revocation snapshot sequence")
    return data


def _release_identity(value: Any) -> dict[str, Any]:
    item = _exact(value, {"release_id", "envelope_sha256", "reason_code", "effective_at"}, "revoked release")
    _string(item["release_id"], "revoked release_id")
    _hex(item["envelope_sha256"], "revoked envelope_sha256")
    if item["reason_code"] not in _REASON_CODES:
        raise InvalidPayload("invalid revocation reason code")
    return item


def _public_ref_identity(value: Any) -> dict[str, Any]:
    item = _exact(value, {"kind", "id", "revision", "hash_profile", "content_hash", "reason_code", "effective_at"}, "revoked public ref")
    if item["kind"] not in _RECORD_KINDS:
        raise InvalidPayload("invalid public object kind")
    _string(item["id"], "public object id")
    _integer(item["revision"], "public object revision")
    if item["hash_profile"] != NATIVE_HASH_PROFILE:
        raise UnsupportedCapability("unknown public object hash profile")
    _hex(item["content_hash"], "public object content_hash")
    if item["reason_code"] not in _REASON_CODES:
        raise InvalidPayload("invalid revocation reason code")
    return item


def validate_revocations_payload(payload: Any) -> dict[str, Any]:
    data = _exact(payload, _REVOCATIONS_FIELDS, "revocations payload")
    if data["schema_version"] != REVOCATIONS_PROFILE:
        raise UnsupportedCapability("unsupported revocations schema")
    _validate_context(data)
    issued = parse_utc(data["issued_at"], "issued_at")
    releases, refs = data["revoked_releases"], data["revoked_public_refs"]
    if not isinstance(releases, list) or not isinstance(refs, list):
        raise InvalidPayload("revocation collections must be arrays")
    release_items = [_release_identity(item) for item in releases]
    ref_items = [_public_ref_identity(item) for item in refs]
    if any(parse_utc(item["effective_at"], "effective_at") > issued for item in [*release_items, *ref_items]):
        raise InvalidPayload("future scheduled revocations are not supported")
    release_keys = [(item["release_id"], item["envelope_sha256"]) for item in release_items]
    if len(release_keys) != len(set(release_keys)) or len({key[0] for key in release_keys}) != len(release_keys):
        raise InvalidPayload("a release_id may occur only once in a revocation snapshot")
    ref_keys = [(item["kind"], item["id"], item["revision"], item["hash_profile"], item["content_hash"]) for item in ref_items]
    if len(ref_keys) != len(set(ref_keys)):
        raise InvalidPayload("duplicate public ref revocation")
    if release_keys != sorted(release_keys) or ref_keys != sorted(ref_keys):
        raise InvalidPayload("revocation arrays must be sorted by identity")
    return data


def signature_message(profile: str, algorithm: str, key_id: str, payload: dict[str, Any]) -> bytes:
    return profile.encode("ascii") + b"\n" + canonical_json_bytes({
        "profile": profile, "algorithm": algorithm, "key_id": key_id, "payload": payload,
    })


def sign_metadata(profile: str, payload: dict[str, Any], *, signing_private_key: Any, key_id: str) -> bytes:
    if profile == CATALOG_PROFILE:
        payload = validate_catalog_payload(payload)
    elif profile == REVOCATIONS_PROFILE:
        payload = validate_revocations_payload(payload)
    else:
        raise UnsupportedCapability("unsupported metadata signature profile")
    _string(key_id, "key_id", max_length=160)
    signature = signing_private_key.sign(signature_message(profile, "Ed25519", key_id, payload)).hex()
    envelope = {"profile": profile, "payload": payload, "signature": {
        "algorithm": "Ed25519", "key_id": key_id, "value": signature,
    }}
    return canonical_json_bytes(envelope) + b"\n"


def verify_metadata(
    raw: bytes,
    *,
    expected_profile: str,
    purpose: str,
    trusted_keys: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    expected_purpose_suffix = "catalog" if expected_profile == CATALOG_PROFILE else "revocations"
    if purpose not in {f"synthetic-{expected_purpose_suffix}", f"production-{expected_purpose_suffix}"}:
        raise IntegrityFailure("metadata purpose does not match its signature profile")
    max_bytes = MAX_CATALOG_BYTES if expected_profile == CATALOG_PROFILE else MAX_REVOCATIONS_BYTES
    envelope = strict_json_loads(raw, max_bytes=max_bytes)
    _exact(envelope, {"profile", "payload", "signature"}, "signed metadata envelope")
    if envelope["profile"] != expected_profile:
        raise UnsupportedCapability("metadata profile does not match request")
    signature = _exact(envelope["signature"], {"algorithm", "key_id", "value"}, "metadata signature")
    key_id = _string(signature["key_id"], "key_id", max_length=160)
    if signature["algorithm"] != "Ed25519" or type(signature["value"]) is not str or re.fullmatch(r"[0-9a-f]{128}", signature["value"]) is None:
        raise IntegrityFailure("metadata signature format is invalid")
    record = trusted_keys.get(key_id)
    if not isinstance(record, dict) or purpose not in record.get("purposes", []):
        raise IntegrityFailure("metadata key is not trusted for this purpose")
    if set(record) != {"public_key", "purposes", "not_before", "not_after", "revoked"}:
        raise IntegrityFailure("metadata key trust record is incomplete")
    public_key = record.get("public_key")
    if (not isinstance(public_key, bytes) or len(public_key) != 32 or type(record.get("revoked")) is not bool
        or record["revoked"] or not isinstance(record.get("purposes"), list)
        or any(type(item) is not str or item not in _KEY_PURPOSES for item in record["purposes"])
        or len(record["purposes"]) != len(set(record["purposes"]))):
        raise IntegrityFailure("metadata key is unavailable")
    if expected_profile == CATALOG_PROFILE:
        payload = validate_catalog_payload(envelope["payload"])
    elif expected_profile == REVOCATIONS_PROFILE:
        payload = validate_revocations_payload(envelope["payload"])
    else:
        raise UnsupportedCapability("unsupported metadata profile")
    issued_at = parse_utc(payload["issued_at"], "issued_at")
    if not parse_utc(record["not_before"], "key not_before") <= issued_at <= parse_utc(record["not_after"], "key not_after"):
        raise IntegrityFailure("metadata key is outside its trusted validity period")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

        Ed25519PublicKey.from_public_bytes(public_key).verify(
            bytes.fromhex(signature["value"]),
            signature_message(expected_profile, "Ed25519", key_id, payload),
        )
    except Exception:
        raise IntegrityFailure("metadata signature verification failed") from None
    return payload


def build_p1_native_test_vectors(
    envelope: dict[str, Any],
    *,
    trusted_public_keys: dict[str, bytes],
    trusted_key_id: str,
) -> dict[str, Any]:
    """Expose one verifier-backed native record and evidence hash vector."""
    from starhelp_knowledge.bundle import verify_public_bundle
    from starhelp_knowledge.distribution import (
        DISTRIBUTION_CAPABILITY,
        PLANNER_CAPABILITY,
        verify_distribution_envelope,
    )
    from starhelp_knowledge.records import content_hash

    result = verify_distribution_envelope(
        envelope,
        trusted_public_keys=trusted_public_keys,
        trusted_key_id=trusted_key_id,
        supported_distribution_capabilities={DISTRIBUTION_CAPABILITY},
        supported_planner_capabilities={PLANNER_CAPABILITY},
    )
    release_id = result["release_id"]
    native_bundle = envelope["objects"][f"native-release:{release_id}"]["bundle"]
    planner_view = envelope["objects"][f"planner-view:{release_id}"]["bundle"]
    verify_public_bundle(native_bundle)
    first_record: tuple[str, dict[str, Any]] | None = None
    for kind in sorted(native_bundle["records"]):
        if native_bundle["records"][kind]:
            first_record = (kind, native_bundle["records"][kind][0])
            break
    if first_record is None or not native_bundle["evidence"]:
        raise InvalidPayload("verified envelope must contain at least one native record and evidence")
    kind, record = first_record
    record_source = {
        "kind": kind, "id": record["id"], "scope": record["scope"], "payload": record["payload"],
        "evidence": record["evidence_refs"], "dependencies": record["dependency_refs"],
    }
    record_hash = content_hash(record_source)
    if record_hash != record["content_hash"]:
        raise IntegrityFailure("native record content_hash does not match A verifier inputs")
    evidence = native_bundle["evidence"][0]
    evidence_source = {key: evidence[key] for key in ("url", "title", "excerpt", "locator", "scope", "relation")}
    evidence_hash = content_hash(evidence_source)
    if evidence_hash != evidence["content_hash"]:
        raise IntegrityFailure("native evidence content_hash does not match A verifier inputs")
    projected = next((item for item in planner_view.get("evidence", []) if item.get("id") == evidence["id"]), None)
    if (not isinstance(projected, dict) or projected.get("revision") != 1
        or projected.get("source_content_hash") != evidence["content_hash"]):
        raise IntegrityFailure("planner projection does not explicitly bind native evidence revision one")
    return {
        "profile": NATIVE_HASH_PROFILE,
        "native_verifier": "starhelp_knowledge.bundle.verify_public_bundle",
        "record": {
            "kind": kind, "id": record["id"], "revision": record["revision"],
            "hash_profile": NATIVE_HASH_PROFILE, "content_hash": record["content_hash"],
            "computation_source": "starhelp_knowledge.records.content_hash({kind,id,scope,payload,evidence,dependencies})",
            "inputs": record_source,
        },
        "evidence": {
            "kind": "evidence", "id": evidence["id"], "revision": 1,
            "hash_profile": NATIVE_HASH_PROFILE, "content_hash": evidence["content_hash"],
            "revision_source": "verified planner_view.evidence[].revision == 1 and source_content_hash matches native evidence.content_hash",
            "computation_source": "starhelp_knowledge.records.content_hash({url,title,excerpt,locator,scope,relation})",
            "inputs": evidence_source,
        },
    }


class PublicDistributionStore:
    """Filesystem store for exact, immutable artifacts and current signed metadata."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.artifacts = self.root / "artifacts"
        self.catalogs = self.root / "catalogs"
        self.revocations = self.root / "revocations"
        self._lock = threading.RLock()

    @staticmethod
    def digest(raw: bytes) -> str:
        return hashlib.sha256(raw).hexdigest()

    def _atomic_immutable(self, path: Path, raw: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            if not hmac.compare_digest(path.read_bytes(), raw):
                raise Conflict("immutable artifact path already contains different bytes")
            return
        temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
        try:
            with temporary.open("xb") as stream:
                stream.write(raw)
                stream.flush()
                os.fsync(stream.fileno())
            try:
                if os.name == "nt":
                    # Windows rename fails if the destination exists, so it is an
                    # atomic create without the hard-link privilege requirement.
                    os.rename(temporary, path)
                else:
                    os.link(temporary, path)
            except (FileExistsError, PermissionError):
                if not path.exists() or not hmac.compare_digest(path.read_bytes(), raw):
                    raise Conflict("immutable artifact path already contains different bytes") from None
        finally:
            temporary.unlink(missing_ok=True)

    def _atomic_pointer(self, path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + f".{os.getpid()}.tmp")
        raw = canonical_json_bytes(value) + b"\n"
        with temporary.open("wb") as stream:
            stream.write(raw)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)

    def artifact_path(self, release_id: str, digest: str) -> Path:
        if _RELEASE_ID.fullmatch(release_id or "") is None or release_id in {".", ".."}:
            raise InvalidPayload("release_id is not a safe path identity")
        _hex(digest, "envelope_sha256")
        return self.artifacts / release_id / f"{digest}.bpublic"

    def store_artifact(self, release_id: str, raw: bytes) -> dict[str, Any]:
        if not isinstance(raw, bytes) or not 1 <= len(raw) <= MAX_ENVELOPE_STORE_BYTES:
            raise InvalidPayload("envelope exceeds store limits")
        digest = self.digest(raw)
        with self._lock:
            path = self.artifact_path(release_id, digest)
            self._atomic_immutable(path, raw)
        return {"release_id": release_id, "sha256": digest, "size_bytes": len(raw)}

    def publish_metadata(
        self,
        catalog_raw: bytes,
        revocations_raw: bytes,
        *,
        trusted_keys: dict[str, dict[str, Any]],
        purpose_prefix: str = "synthetic",
    ) -> dict[str, Any]:
        if purpose_prefix != "synthetic":
            raise UnsupportedCapability("production metadata publishing is disabled in this build")
        catalog = verify_metadata(catalog_raw, expected_profile=CATALOG_PROFILE, purpose=f"{purpose_prefix}-catalog", trusted_keys=trusted_keys)
        revocations = verify_metadata(revocations_raw, expected_profile=REVOCATIONS_PROFILE, purpose=f"{purpose_prefix}-revocations", trusted_keys=trusted_keys)
        context = ("origin_id", "channel", "consumer_profile")
        if any(catalog[key] != revocations[key] for key in context):
            raise IntegrityFailure("catalog and revocations contexts do not match")
        snapshot = catalog["revocation_snapshot"]
        rev_digest = self.digest(revocations_raw)
        if (snapshot["sha256"] != rev_digest or snapshot["size_bytes"] != len(revocations_raw)
            or snapshot["sequence"] != revocations["sequence"]):
            raise IntegrityFailure("catalog does not bind the exact revocation bytes")
        active = catalog["active_release_id"]
        revoked_release_ids = {item["release_id"] for item in revocations["revoked_releases"]}
        if active in revoked_release_ids:
            raise IntegrityFailure("catalog active release is revoked")
        with self._lock:
            current_path = self.root / "current.json"
            current = strict_json_loads(current_path.read_bytes(), max_bytes=16_384) if current_path.exists() else None
            if current is not None:
                if (current["origin_id"], current["channel"], current["consumer_profile"]) != tuple(catalog[key] for key in context):
                    raise Conflict("distribution store cannot mix trust scopes")
                old_catalog = self.catalogs / current["catalog_file"]
                old_revocations = self.revocations / current["revocations_file"]
                old_catalog_payload = self._verify_stored(old_catalog.read_bytes(), CATALOG_PROFILE, f"{purpose_prefix}-catalog", trusted_keys)
                old_rev_payload = self._verify_stored(old_revocations.read_bytes(), REVOCATIONS_PROFILE, f"{purpose_prefix}-revocations", trusted_keys)
                self._check_sequence(catalog, current["catalog_sequence"], current["catalog_sha256"], self.digest(catalog_raw), label="catalog")
                self._check_sequence(revocations, current["revocations_sequence"], current["revocations_sha256"], rev_digest, label="revocations")
                old_release_keys = {(row["release_id"], row["envelope_sha256"]) for row in old_rev_payload["revoked_releases"]}
                new_release_keys = {(row["release_id"], row["envelope_sha256"]) for row in revocations["revoked_releases"]}
                old_ref_keys = {(row["kind"], row["id"], row["revision"], row["hash_profile"], row["content_hash"]) for row in old_rev_payload["revoked_public_refs"]}
                new_ref_keys = {(row["kind"], row["id"], row["revision"], row["hash_profile"], row["content_hash"]) for row in revocations["revoked_public_refs"]}
                if not old_release_keys <= new_release_keys or not old_ref_keys <= new_ref_keys:
                    raise IntegrityFailure("revocation snapshot must retain all previously published tombstones")
            for item in catalog["distributions"]:
                path = self.artifact_path(item["release_id"], item["envelope_sha256"])
                if not path.is_file():
                    raise NotFound("catalog references an artifact that has not been stored")
                raw = path.read_bytes()
                if len(raw) != item["size_bytes"] or self.digest(raw) != item["envelope_sha256"]:
                    raise IntegrityFailure("stored artifact does not match catalog")
            catalog_digest = self.digest(catalog_raw)
            rev_file_digest = self.digest(revocations_raw)
            catalog_name = f"{catalog['sequence']}-{catalog_digest}.json"
            rev_name = f"{revocations['sequence']}-{rev_file_digest}.json"
            self._atomic_immutable(self.catalogs / catalog_name, catalog_raw)
            self._atomic_immutable(self.revocations / rev_name, revocations_raw)
            state = {
                "origin_id": catalog["origin_id"], "channel": catalog["channel"],
                "consumer_profile": catalog["consumer_profile"],
                "catalog_sequence": catalog["sequence"], "catalog_sha256": catalog_digest,
                "catalog_file": catalog_name,
                "revocations_sequence": revocations["sequence"], "revocations_sha256": rev_file_digest,
                "revocations_file": rev_name, "active_release_id": active,
            }
            self._atomic_pointer(current_path, state)
        return {"catalog_sequence": catalog["sequence"], "catalog_sha256": catalog_digest,
                "revocations_sequence": revocations["sequence"], "revocations_sha256": rev_file_digest,
                "active_release_id": active, "allow_production": False}

    @staticmethod
    def _check_sequence(payload: dict[str, Any], previous_sequence: int, previous_digest: str, current_digest: str, *, label: str) -> None:
        if payload["sequence"] < previous_sequence:
            raise Conflict(f"{label} sequence cannot move backwards")
        if payload["sequence"] == previous_sequence and not hmac.compare_digest(previous_digest, current_digest):
            raise Conflict(f"{label} same-sequence bytes conflict")

    @staticmethod
    def _verify_stored(raw: bytes, profile: str, purpose: str, trusted_keys: dict[str, dict[str, Any]]) -> dict[str, Any]:
        return verify_metadata(raw, expected_profile=profile, purpose=purpose, trusted_keys=trusted_keys)

    def _current(self) -> tuple[dict[str, Any], bytes, bytes, dict[str, Any], dict[str, Any]]:
        pointer = self.root / "current.json"
        if not pointer.exists():
            raise NotFound("public distribution is not configured")
        state = strict_json_loads(pointer.read_bytes(), max_bytes=16_384)
        _exact(state, {
            "origin_id", "channel", "consumer_profile", "catalog_sequence", "catalog_sha256",
            "catalog_file", "revocations_sequence", "revocations_sha256", "revocations_file",
            "active_release_id",
        }, "distribution pointer")
        if (type(state["catalog_file"]) is not str or re.fullmatch(r"[1-9][0-9]*-[0-9a-f]{64}\.json", state["catalog_file"]) is None
            or type(state["revocations_file"]) is not str or re.fullmatch(r"[1-9][0-9]*-[0-9a-f]{64}\.json", state["revocations_file"]) is None):
            raise IntegrityFailure("distribution pointer path is invalid")
        catalog_raw = (self.catalogs / state["catalog_file"]).read_bytes()
        rev_raw = (self.revocations / state["revocations_file"]).read_bytes()
        if (self.digest(catalog_raw) != state["catalog_sha256"]
            or self.digest(rev_raw) != state["revocations_sha256"]):
            raise IntegrityFailure("stored metadata bytes do not match the committed pointer")
        catalog = strict_json_loads(catalog_raw, max_bytes=MAX_CATALOG_BYTES)
        revocations = strict_json_loads(rev_raw, max_bytes=MAX_REVOCATIONS_BYTES)
        if not isinstance(catalog, dict) or catalog.get("profile") != CATALOG_PROFILE or not isinstance(catalog.get("payload"), dict):
            raise IntegrityFailure("stored catalog representation is invalid")
        if not isinstance(revocations, dict) or revocations.get("profile") != REVOCATIONS_PROFILE or not isinstance(revocations.get("payload"), dict):
            raise IntegrityFailure("stored revocation representation is invalid")
        validate_catalog_payload(catalog["payload"])
        validate_revocations_payload(revocations["payload"])
        if (catalog.get("payload", {}).get("sequence") != state["catalog_sequence"]
            or catalog.get("payload", {}).get("origin_id") != state["origin_id"]
            or catalog.get("payload", {}).get("channel") != state["channel"]
            or revocations.get("payload", {}).get("sequence") != state["revocations_sequence"]
            or revocations.get("payload", {}).get("origin_id") != state["origin_id"]
            or catalog.get("payload", {}).get("revocation_snapshot", {}).get("sha256") != state["revocations_sha256"]
            or catalog.get("payload", {}).get("revocation_snapshot", {}).get("sequence") != state["revocations_sequence"]):
            raise IntegrityFailure("stored metadata does not match its committed scope")
        return state, catalog_raw, rev_raw, catalog["payload"], revocations["payload"]

    def get_catalog(self, *, profile: str, channel: str) -> bytes:
        _, raw, _, catalog, _ = self._current()
        if profile != catalog["consumer_profile"] or channel != catalog["channel"]:
            raise NotFound()
        return raw

    def get_revocations(self, *, profile: str, channel: str) -> bytes:
        _, _, raw, catalog, revocations = self._current()
        if profile != catalog["consumer_profile"] or channel != catalog["channel"] or catalog["origin_id"] != revocations["origin_id"]:
            raise NotFound()
        return raw

    def get_artifact(self, release_id: str) -> bytes:
        _, _, _, catalog, revocations = self._current()
        item = next((row for row in catalog["distributions"] if row["release_id"] == release_id), None)
        if item is None:
            raise NotFound()
        if any(row["release_id"] == release_id and row["envelope_sha256"] == item["envelope_sha256"] for row in revocations["revoked_releases"]):
            raise NotFound("release has been revoked")
        path = self.artifact_path(release_id, item["envelope_sha256"])
        try:
            raw = path.read_bytes()
        except OSError:
            raise NotFound("distribution artifact is unavailable") from None
        if len(raw) != item["size_bytes"] or self.digest(raw) != item["envelope_sha256"]:
            raise IntegrityFailure("stored artifact does not match catalog")
        return raw

    def readiness(self) -> tuple[str, str | None]:
        try:
            _, _, _, catalog, _ = self._current()
            active = catalog["active_release_id"]
            self.get_artifact(active)
            return "available", active
        except (OSError, KeyError, InvalidPayload, IntegrityFailure, NotFound):
            return "unavailable", None
