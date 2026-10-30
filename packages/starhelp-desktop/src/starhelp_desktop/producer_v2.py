"""Strict v0.2 producer protocol primitives.

This module is deliberately separate from the legacy 0.1 request builder and worker.
It validates closed wire objects and never treats request supplied trust as authority.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

from .producer_request import _validated_feedback


PROFILE = "starhelp.producers.v0.2"
BASIS_PROFILE = "starhelp.public-basis.v1"
POLICY_PROFILE = "starhelp.execution-policy.v1"
HASH_PROFILE = "starhelp.a-native-content-field.v1"
OUTER_KEYS = frozenset({
    "schema_id", "schema_version", "request_id", "authorization_generation",
    "account_snapshot", "producer_request",
})
INNER_REQUIRED_KEYS = frozenset({
    "schema_id", "schema_version", "adapter_profile", "request_id", "request_producer",
    "public_bundle", "account_snapshot", "authorization_context", "task", "evaluation_time",
    "public_basis", "public_basis_sha256", "public_documents",
})
INNER_KEYS = INNER_REQUIRED_KEYS | {"feedback"}
PRODUCER_KEYS = frozenset({
    "name", "package_version", "source_commit", "builder_module", "builder_blob",
    "dependency_lock_sha256", "artifact_kind", "artifact_sha256",
})
BASIS_KEYS = frozenset({
    "profile", "origin_id", "channel", "consumer_profile", "policy_id", "policy_revision",
    "policy_sha256", "epoch", "selected_artifact", "qualification_pair", "latest_pair",
    "qualified_at", "offline_until", "evaluation_time", "state",
})
DOCUMENT_PROFILES = frozenset({
    "starhelp.public-distribution-catalog.v1", "starhelp.public-revocations.v1",
})
OBJECT_KINDS = frozenset({
    "entity", "knowledge", "stage", "template", "variant", "troubleshooting", "resource",
    "evidence",
})
SAFETY_STATES = frozenset({"ready", "pending", "recovery_required", "clock_untrusted"})
REVOCATION_STATES = frozenset({
    "fresh", "offline_stale", "expired", "revoked", "revocation_unknown",
    "recovery_required", "clock_untrusted",
})
MAX_REQUEST_BYTES = 8 * 1024 * 1024
MAX_DOCUMENT_BYTES = {
    "starhelp.public-distribution-catalog.v1": 128 * 1024,
    "starhelp.public-revocations.v1": 256 * 1024,
}
_SHA256 = re.compile(r"^[0-9a-f]{64}$")
_GIT_OBJECT = re.compile(r"^[0-9a-f]{40}$")
_UTC_Z = re.compile(r"^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?Z$")


def canonical_json_bytes(value: Any) -> bytes:
    try:
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise ValueError("value is not bounded canonical JSON") from None


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _closed(value: Any, keys: frozenset[str], label: str, *, optional: frozenset[str] = frozenset()) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) - keys or keys - optional - set(value):
        raise ValueError(f"{label} has missing or unknown fields")
    return value


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{label} must be a positive integer")
    return value


def _digest(value: Any, label: str) -> str:
    if not isinstance(value, str) or not _SHA256.fullmatch(value):
        raise ValueError(f"{label} must be a lowercase SHA-256")
    return value


def _utc(value: Any, label: str) -> datetime:
    if not isinstance(value, str) or not _UTC_Z.fullmatch(value):
        raise ValueError(f"{label} must be a UTC timestamp ending in Z")
    try:
        return datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise ValueError(f"{label} is invalid") from None


@dataclass(frozen=True, slots=True)
class ReleaseIdentity:
    origin_id: str
    channel: str
    consumer_profile: str
    release_id: str
    envelope_sha256: str

    def __post_init__(self) -> None:
        if any(not isinstance(v, str) or not v.strip() for v in (
            self.origin_id, self.channel, self.consumer_profile, self.release_id,
        )):
            raise ValueError("release identity fields must be non-empty strings")
        _digest(self.envelope_sha256, "release envelope digest")

    def as_dict(self) -> dict[str, Any]:
        return {
            "origin_id": self.origin_id, "channel": self.channel,
            "consumer_profile": self.consumer_profile, "release_id": self.release_id,
            "envelope_sha256": self.envelope_sha256,
        }


@dataclass(frozen=True, slots=True)
class PublicObjectIdentity:
    kind: str
    id: str
    revision: int
    hash_profile: str
    content_hash: str

    def __post_init__(self) -> None:
        if self.kind not in OBJECT_KINDS:
            raise ValueError("unknown public object kind")
        if not isinstance(self.id, str) or not self.id.strip():
            raise ValueError("public object id must be a non-empty string")
        _positive_int(self.revision, "public object revision")
        if self.hash_profile != HASH_PROFILE:
            raise ValueError("unknown public object hash profile")
        _digest(self.content_hash, "public object native content_hash")

    def as_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind, "id": self.id, "revision": self.revision,
            "hash_profile": self.hash_profile, "content_hash": self.content_hash,
        }


class CumulativeRevocations:
    """In-memory monotone typed tombstone ledger; persistence is injected by the host."""

    def __init__(self, releases: Sequence[Mapping[str, Any]] = (),
                 objects: Sequence[Mapping[str, Any]] = ()) -> None:
        self._releases: set[tuple[str, ...]] = set()
        self._objects: set[tuple[str, str, int, str, str]] = set()
        self.merge(releases=releases, objects=objects)

    @property
    def releases(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(zip(
            ("origin_id", "channel", "consumer_profile", "release_id", "envelope_sha256"), item
        )) for item in sorted(self._releases))

    @property
    def objects(self) -> tuple[dict[str, Any], ...]:
        return tuple(dict(zip(
            ("kind", "id", "revision", "hash_profile", "content_hash"), item
        )) for item in sorted(self._objects))

    def merge(self, *, releases: Sequence[Mapping[str, Any]],
              objects: Sequence[Mapping[str, Any]]) -> None:
        if not isinstance(releases, Sequence) or isinstance(releases, (str, bytes)):
            raise ValueError("release revocations must be an array")
        if not isinstance(objects, Sequence) or isinstance(objects, (str, bytes)):
            raise ValueError("object revocations must be an array")
        new_releases: set[tuple[str, ...]] = set()
        new_objects: set[tuple[str, str, int, str, str]] = set()
        for entry in releases:
            if not isinstance(entry, Mapping) or set(entry) != {
                "origin_id", "channel", "consumer_profile", "release_id", "envelope_sha256",
            }:
                raise ValueError("release tombstone has an invalid shape")
            identity = ReleaseIdentity(**entry)
            new_releases.add((identity.origin_id, identity.channel, identity.consumer_profile,
                              identity.release_id, identity.envelope_sha256))
        for entry in objects:
            if not isinstance(entry, Mapping) or set(entry) != {
                "kind", "id", "revision", "hash_profile", "content_hash",
            }:
                raise ValueError("object tombstone has an invalid shape")
            identity = PublicObjectIdentity(**entry)
            new_objects.add((identity.kind, identity.id, identity.revision,
                             identity.hash_profile, identity.content_hash))
        self._releases.update(new_releases)
        self._objects.update(new_objects)

    def release_is_revoked(self, identity: ReleaseIdentity) -> bool:
        return (identity.origin_id, identity.channel, identity.consumer_profile,
                identity.release_id, identity.envelope_sha256) in self._releases

    def object_is_revoked(self, identity: PublicObjectIdentity) -> bool:
        return (identity.kind, identity.id, identity.revision, identity.hash_profile,
                identity.content_hash) in self._objects


def build_public_basis_sha256(basis: Mapping[str, Any]) -> str:
    return sha256_hex(canonical_json_bytes(dict(basis)))


def validate_public_documents(documents: Any) -> dict[str, dict[str, str]]:
    if not isinstance(documents, dict) or len(documents) > 4:
        raise ValueError("public_documents must be a map of at most four signed documents")
    result: dict[str, dict[str, str]] = {}
    for digest, doc in documents.items():
        _digest(digest, "public document map key")
        if not isinstance(doc, dict) or set(doc) != {"profile", "raw_json"}:
            raise ValueError("public document has an invalid shape")
        profile, raw_json = doc["profile"], doc["raw_json"]
        if profile not in DOCUMENT_PROFILES or not isinstance(raw_json, str):
            raise ValueError("public document profile or raw JSON is invalid")
        raw = raw_json.encode("utf-8")
        if len(raw) > MAX_DOCUMENT_BYTES[profile] or sha256_hex(raw) != digest:
            raise ValueError("public document digest or byte limit is invalid")
        result[digest] = {"profile": profile, "raw_json": raw_json}
    return result


def validate_public_basis(basis: Any, supplied_digest: Any, documents: Any) -> dict[str, Any]:
    value = _closed(basis, BASIS_KEYS, "public_basis")
    if value["profile"] != BASIS_PROFILE:
        raise ValueError("unsupported public basis profile")
    for field in ("origin_id", "channel", "consumer_profile", "policy_id"):
        if not isinstance(value[field], str) or not value[field].strip():
            raise ValueError(f"public_basis.{field} is invalid")
    _positive_int(value["policy_revision"], "policy revision")
    _positive_int(value["epoch"], "public epoch")
    _digest(value["policy_sha256"], "policy digest")
    if value["state"] not in REVOCATION_STATES:
        raise ValueError("unknown public validity state")
    for name in ("qualified_at", "offline_until", "evaluation_time"):
        _utc(value[name], f"public_basis.{name}")
    artifact = _closed(value["selected_artifact"], frozenset({
        "release_id", "envelope_sha256", "a_producer", "planner", "b_snapshot",
    }), "selected_artifact")
    if not isinstance(artifact["release_id"], str) or not artifact["release_id"]:
        raise ValueError("selected artifact release ID is invalid")
    _digest(artifact["envelope_sha256"], "selected envelope digest")
    a_fields = {"package", "version", "commit"}
    a_tuple = _closed(artifact["a_producer"], frozenset(a_fields), "selected A producer tuple")
    if (any(not isinstance(a_tuple[field], str) or not a_tuple[field] for field in a_fields)
            or not _GIT_OBJECT.fullmatch(a_tuple["commit"])):
        raise ValueError("selected A producer tuple is invalid")
    planner_fields = {"profile", "producer_profile", "component_version", "wheel_sha256"}
    planner = _closed(artifact["planner"], frozenset(planner_fields), "selected planner tuple")
    if any(not isinstance(planner[field], str) or not planner[field] for field in planner_fields):
        raise ValueError("selected planner tuple is invalid")
    _digest(planner["wheel_sha256"], "selected planner wheel digest")
    snapshot_tuple = _closed(artifact["b_snapshot"], frozenset({"profile", "producer_commit"}),
                             "selected B snapshot tuple")
    if (not isinstance(snapshot_tuple["profile"], str) or not snapshot_tuple["profile"]
            or not isinstance(snapshot_tuple["producer_commit"], str)
            or not _GIT_OBJECT.fullmatch(snapshot_tuple["producer_commit"])):
        raise ValueError("selected B snapshot tuple is invalid")
    normalized_documents = validate_public_documents(documents)
    for name in ("qualification_pair", "latest_pair"):
        pair = _closed(value[name], frozenset({"catalog_sha256", "revocations_sha256"}), name)
        for field, expected_profile in (
            ("catalog_sha256", "starhelp.public-distribution-catalog.v1"),
            ("revocations_sha256", "starhelp.public-revocations.v1"),
        ):
            digest = pair[field]
            _digest(digest, f"{name} digest")
            if digest not in normalized_documents:
                raise ValueError(f"{name} references a missing public document")
            if normalized_documents[digest]["profile"] != expected_profile:
                raise ValueError(f"{name} references the wrong public document profile")
    expected = build_public_basis_sha256(value)
    if supplied_digest != expected:
        raise ValueError("public basis digest mismatch")
    return value


def validate_request_producer(value: Any) -> dict[str, Any]:
    producer = _closed(value, PRODUCER_KEYS, "request_producer")
    if producer["name"] != "starhelp-desktop" or producer["artifact_kind"] != "source-lock":
        raise ValueError("unsupported request producer identity")
    for field in ("package_version", "builder_module"):
        if not isinstance(producer[field], str) or not producer[field].strip():
            raise ValueError(f"request_producer.{field} is invalid")
    for field in ("source_commit", "builder_blob"):
        if not isinstance(producer[field], str) or not _GIT_OBJECT.fullmatch(producer[field]):
            raise ValueError(f"request_producer.{field} must be a full Git object ID")
    for field in ("dependency_lock_sha256", "artifact_sha256"):
        _digest(producer[field], f"request_producer.{field}")
    return producer


def build_outer_request_v2(*, request_id: str, authorization_generation: int,
                           profile_id: str, snapshot_revision: int,
                           producer_request: Mapping[str, Any]) -> dict[str, Any]:
    generation = _positive_int(authorization_generation, "authorization generation")
    revision = _positive_int(snapshot_revision, "snapshot revision")
    if not isinstance(request_id, str) or not request_id:
        raise ValueError("request ID is required")
    inner = validate_inner_request_v2(producer_request)
    if inner["request_id"] != request_id:
        raise ValueError("outer and producer request IDs differ")
    auth = inner["authorization_context"]
    snapshot = inner["account_snapshot"]
    if auth != {"profile_id": profile_id, "active": True, "generation": generation}:
        raise ValueError("inner authorization does not match outer authorization")
    try:
        snapshot_data = json.loads(snapshot["raw_json"])
    except (TypeError, ValueError, RecursionError):
        raise ValueError("inner snapshot raw JSON is invalid") from None
    if (not isinstance(snapshot_data, dict) or snapshot_data.get("revision") != revision
            or snapshot_data.get("profile_id") != profile_id):
        raise ValueError("inner snapshot does not match outer snapshot summary")
    outer = {
        "schema_id": "AnalysisRequest", "schema_version": "0.2", "request_id": request_id,
        "authorization_generation": generation,
        "account_snapshot": {
            "profile_id": profile_id, "snapshot_revision": revision,
            "authorization_generation": generation, "authorization_state": "active",
        },
        "producer_request": inner,
    }
    if set(outer) != OUTER_KEYS:
        raise AssertionError("outer request schema drift")
    encoded = canonical_json_bytes(outer) + b"\n"
    if len(encoded) > MAX_REQUEST_BYTES:
        raise ValueError("local_payload_too_large")
    return outer


def build_producer_request_v2(*, request_id: str, request_producer: Mapping[str, Any],
                              public_bundle: Mapping[str, Any],
                              account_snapshot: Mapping[str, Any],
                              authorization_context: Mapping[str, Any], task: Mapping[str, Any],
                              evaluation_time: str, public_basis: Mapping[str, Any],
                              public_documents: Mapping[str, Any],
                              feedback: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Build the closed v0.2 inner request with exactly one copy of each input."""
    request: dict[str, Any] = {
        "schema_id": "ProducerAnalysisRequest", "schema_version": "0.2",
        "adapter_profile": PROFILE, "request_id": request_id,
        "request_producer": dict(request_producer), "public_bundle": dict(public_bundle),
        "account_snapshot": dict(account_snapshot),
        "authorization_context": dict(authorization_context), "task": dict(task),
        "evaluation_time": evaluation_time, "public_basis": dict(public_basis),
        "public_basis_sha256": build_public_basis_sha256(public_basis),
        "public_documents": {key: dict(value) for key, value in public_documents.items()},
    }
    if feedback is not None:
        request["feedback"] = _validated_feedback(dict(feedback), dict(task))
    validate_inner_request_v2(request)
    return request


def validate_inner_request_v2(request: Any) -> dict[str, Any]:
    inner = _closed(request, INNER_KEYS, "producer request", optional=frozenset({"feedback"}))
    if (inner["schema_id"] != "ProducerAnalysisRequest" or inner["schema_version"] != "0.2"
            or inner["adapter_profile"] != PROFILE):
        raise ValueError("unsupported v0.2 producer profile")
    if not isinstance(inner["request_id"], str) or not inner["request_id"]:
        raise ValueError("producer request ID is invalid")
    validate_request_producer(inner["request_producer"])
    auth = inner["authorization_context"]
    if (not isinstance(auth, dict) or set(auth) != {"profile_id", "active", "generation"}
            or not isinstance(auth["profile_id"], str) or auth["active"] is not True):
        raise ValueError("producer authorization context is invalid")
    _positive_int(auth["generation"], "authorization generation")
    snapshot = inner["account_snapshot"]
    if not isinstance(snapshot, dict) or set(snapshot) != {
        "producer", "producer_commit", "format_profile", "raw_json", "sha256",
    }:
        raise ValueError("producer account snapshot envelope is invalid")
    for field in ("producer", "producer_commit", "format_profile", "raw_json"):
        if not isinstance(snapshot[field], str):
            raise ValueError("producer account snapshot fields must be strings")
    snapshot_raw = snapshot["raw_json"].encode("utf-8")
    if len(snapshot_raw) > 512 * 1024 or sha256_hex(snapshot_raw) != snapshot["sha256"]:
        raise ValueError("producer account snapshot digest or size is invalid")
    try:
        snapshot_data = json.loads(snapshot["raw_json"])
    except (ValueError, RecursionError):
        raise ValueError("producer account snapshot raw JSON is invalid") from None
    if (not isinstance(snapshot_data, dict)
            or snapshot_data.get("profile_id") != inner["authorization_context"].get("profile_id")):
        raise ValueError("producer account snapshot does not match its authorization context")
    _positive_int(snapshot_data.get("revision"), "serialized snapshot revision")
    bundle = inner["public_bundle"]
    if not isinstance(bundle, dict) or set(bundle) != {
        "producer", "producer_commit", "format_profile", "expected_release_id", "raw_json", "sha256",
    }:
        raise ValueError("producer public bundle envelope is invalid")
    if any(not isinstance(bundle[k], str) for k in bundle):
        raise ValueError("producer public bundle fields must be strings")
    bundle_raw = bundle["raw_json"].encode("utf-8")
    if len(bundle_raw) > 2 * 1024 * 1024 or sha256_hex(bundle_raw) != bundle["sha256"]:
        raise ValueError("producer public bundle digest or size is invalid")
    _utc(inner["evaluation_time"], "evaluation_time")
    basis = validate_public_basis(inner["public_basis"], inner["public_basis_sha256"],
                                  inner["public_documents"])
    if basis["evaluation_time"] != inner["evaluation_time"]:
        raise ValueError("public basis and producer evaluation times differ")
    if (basis["selected_artifact"]["release_id"] != bundle["expected_release_id"]
            or basis["selected_artifact"]["envelope_sha256"] != sha256_hex(bundle_raw)):
        raise ValueError("public basis does not bind the selected raw bundle")
    if basis["state"] not in {"fresh", "offline_stale"}:
        raise ValueError("public basis is not executable")
    if not isinstance(inner["task"], dict):
        raise ValueError("producer task must be an object")
    if "feedback" in inner:
        feedback = inner["feedback"]
        if feedback is not None:
            validated_feedback = _validated_feedback(feedback, inner["task"])
            if validated_feedback != feedback:
                raise ValueError("feedback is not in canonical supported form")
    return inner


def load_execution_policy(path: Path, *, expected_sha256: str) -> dict[str, Any]:
    """Load an explicitly configured policy file; no stdin-controlled paths are accepted."""
    _digest(expected_sha256, "expected execution policy digest")
    raw = path.read_bytes()
    if len(raw) > 2 * 1024 * 1024 or sha256_hex(raw) != expected_sha256:
        raise ValueError("execution policy file digest or size is invalid")
    policy = json.loads(raw.decode("utf-8"))
    if not isinstance(policy, dict) or set(policy) != {"config", "context"}:
        raise ValueError("execution policy wrapper is invalid")
    config, context = policy["config"], policy["context"]
    config_keys = {
        "profile", "policy_id", "revision", "allow_production", "keys", "allowed_a_producers",
        "allowed_b_snapshots", "allowed_request_producers", "allowed_c_components", "limits",
        "freshness",
    }
    context_keys = {
        "origin_id", "channel", "consumer_profile", "public_epoch", "basis_sha256",
        "evaluation_time", "known_revoked_releases", "known_revoked_public_refs", "safety_state",
    }
    if not isinstance(config, dict) or set(config) != config_keys:
        raise ValueError("execution policy config has missing or unknown fields")
    if not isinstance(context, dict) or set(context) != context_keys:
        raise ValueError("execution policy context has missing or unknown fields")
    if config["profile"] != POLICY_PROFILE or config["allow_production"] is not False:
        raise ValueError("only explicit synthetic v0.2 execution policy is accepted")
    if not isinstance(config["policy_id"], str) or not config["policy_id"].strip():
        raise ValueError("execution policy ID is invalid")
    _positive_int(config["revision"], "execution policy revision")
    _positive_int(context["public_epoch"], "public epoch")
    _digest(context["basis_sha256"], "context public basis digest")
    _utc(context["evaluation_time"], "context evaluation time")
    for field in ("origin_id", "channel", "consumer_profile"):
        if not isinstance(context[field], str) or not context[field].strip():
            raise ValueError(f"execution context {field} is invalid")
    if context["safety_state"] not in SAFETY_STATES:
        raise ValueError("unknown execution policy safety state")
    if context["safety_state"] != "ready":
        raise ValueError("execution policy safety state does not permit analysis")
    limits = config["limits"]
    limit_maxima = {
        "request_bytes": MAX_REQUEST_BYTES, "response_bytes": 16 * 1024 * 1024,
        "envelope_raw_bytes": 2 * 1024 * 1024, "snapshot_raw_bytes": 512 * 1024,
        "catalog_raw_bytes": 128 * 1024, "revocations_raw_bytes": 256 * 1024,
        "feedback_bytes": 64 * 1024, "feedback_fields": 64, "documents_count": 4,
        "json_nodes": 100_000, "json_depth": 48, "raw_chars": 8_000_000,
    }
    if not isinstance(limits, dict) or set(limits) != set(limit_maxima):
        raise ValueError("execution policy limits have missing or unknown fields")
    for name, maximum in limit_maxima.items():
        amount = limits[name]
        if not isinstance(amount, int) or isinstance(amount, bool) or not 1 <= amount <= maximum:
            raise ValueError(f"execution policy limit {name} exceeds the frozen maximum")
    freshness = config["freshness"]
    freshness_keys = {
        "catalog_ttl_seconds", "refresh_interval_seconds", "offline_max_seconds",
        "clock_skew_seconds",
    }
    if not isinstance(freshness, dict) or set(freshness) != freshness_keys:
        raise ValueError("execution policy freshness fields are invalid")
    freshness_limits = {
        "catalog_ttl_seconds": 24 * 60 * 60,
        "refresh_interval_seconds": 6 * 60 * 60,
        "offline_max_seconds": 72 * 60 * 60,
        "clock_skew_seconds": 300,
    }
    for name, maximum in freshness_limits.items():
        amount = freshness[name]
        if not isinstance(amount, int) or isinstance(amount, bool) or not 1 <= amount <= maximum:
            raise ValueError(f"execution policy freshness {name} exceeds the development maximum")
    key_fields = {"key_id", "public_key_hex", "purposes", "not_before", "not_after", "revoked"}
    allowed_purposes = {
        "synthetic-release", "synthetic-catalog", "synthetic-revocations",
        "production-release", "production-catalog", "production-revocations",
    }
    keys = config["keys"]
    if not isinstance(keys, list) or not keys:
        raise ValueError("execution policy requires explicit synthetic keys")
    for key in keys:
        if not isinstance(key, dict) or set(key) != key_fields:
            raise ValueError("execution policy key entry has missing or unknown fields")
        if not isinstance(key["key_id"], str) or not key["key_id"]:
            raise ValueError("execution policy key ID is invalid")
        if (not isinstance(key["public_key_hex"], str)
                or not re.fullmatch(r"[0-9a-f]{64}", key["public_key_hex"])):
            raise ValueError("execution policy public key must be 32-byte lowercase hex")
        purposes = key["purposes"]
        if (not isinstance(purposes, list) or not purposes
                or any(not isinstance(purpose, str) for purpose in purposes)
                or len(purposes) != len(set(purposes))
                or any(purpose not in allowed_purposes for purpose in purposes)
                or any(purpose.startswith("production-") for purpose in purposes)):
            raise ValueError("synthetic execution policy contains a production or invalid key purpose")
        _utc(key["not_before"], "key not_before")
        _utc(key["not_after"], "key not_after")
        if not isinstance(key["revoked"], bool):
            raise ValueError("execution policy key revoked flag must be boolean")
    arrays = ("allowed_a_producers", "allowed_b_snapshots", "allowed_request_producers",
              "allowed_c_components")
    for name in arrays:
        if not isinstance(config[name], list) or not config[name]:
            raise ValueError(f"execution policy {name} must be a non-empty allowlist")
    if (not isinstance(context["known_revoked_releases"], list)
            or not isinstance(context["known_revoked_public_refs"], list)):
        raise ValueError("execution context tombstones must be arrays")
    a_fields = {"package", "version", "commit", "envelope_profile", "native_profile", "planner_profile"}
    for entry in config["allowed_a_producers"]:
        if not isinstance(entry, dict) or set(entry) != a_fields:
            raise ValueError("A producer allowlist entry is malformed")
        if any(not isinstance(entry[field], str) or not entry[field] for field in a_fields):
            raise ValueError("A producer allowlist fields must be non-empty strings")
        if not _GIT_OBJECT.fullmatch(entry["commit"]):
            raise ValueError("A producer allowlist commit is invalid")
    snapshot_fields = {"profile", "producer_commit"}
    for entry in config["allowed_b_snapshots"]:
        if (not isinstance(entry, dict) or set(entry) != snapshot_fields
                or not isinstance(entry["profile"], str) or not entry["profile"]
                or not isinstance(entry["producer_commit"], str)
                or not _GIT_OBJECT.fullmatch(entry["producer_commit"])):
            raise ValueError("B snapshot allowlist entry is malformed")
    for entry in config["allowed_request_producers"]:
        validate_request_producer(entry)
    c_fields = {"profile", "producer_profile", "component_version", "wheel_sha256"}
    for entry in config["allowed_c_components"]:
        if not isinstance(entry, dict) or set(entry) != c_fields:
            raise ValueError("C component allowlist entry is malformed")
        if any(not isinstance(entry[field], str) or not entry[field] for field in c_fields):
            raise ValueError("C component allowlist fields must be non-empty strings")
        _digest(entry["wheel_sha256"], "C wheel digest")
    for entry in context["known_revoked_releases"]:
        if not isinstance(entry, dict) or set(entry) != {
            "origin_id", "channel", "consumer_profile", "release_id", "envelope_sha256",
        }:
            raise ValueError("execution context release tombstone is malformed")
        ReleaseIdentity(**entry)
    for entry in context["known_revoked_public_refs"]:
        if not isinstance(entry, dict) or set(entry) != {
            "kind", "id", "revision", "hash_profile", "content_hash",
        }:
            raise ValueError("execution context object tombstone is malformed")
        PublicObjectIdentity(**entry)
    return policy


def validate_execution_policy_context(policy: Mapping[str, Any], request: Mapping[str, Any]) -> None:
    """Bind the separately loaded host policy/context to one v0.2 producer request."""
    inner = validate_inner_request_v2(request)
    config, context = policy["config"], policy["context"]
    basis = inner["public_basis"]
    if hashlib.sha256(canonical_json_bytes(config)).hexdigest() != basis["policy_sha256"]:
        raise ValueError("execution policy digest does not match public basis")
    if (config["policy_id"] != basis["policy_id"]
            or config["revision"] != basis["policy_revision"]):
        raise ValueError("execution policy identity does not match public basis")
    for field in ("origin_id", "channel", "consumer_profile"):
        if context[field] != basis[field]:
            raise ValueError(f"execution context {field} does not match public basis")
    if context["public_epoch"] != basis["epoch"]:
        raise ValueError("execution context epoch does not match public basis")
    if context["basis_sha256"] != inner["public_basis_sha256"]:
        raise ValueError("execution context basis digest mismatch")
    if context["evaluation_time"] != basis["evaluation_time"]:
        raise ValueError("execution context evaluation time mismatch")
    producer = inner["request_producer"]
    if producer not in config["allowed_request_producers"]:
        raise ValueError("request producer is not admitted by execution policy")
    selected_a = basis["selected_artifact"]["a_producer"]
    if not any(all(entry[field] == selected_a[field] for field in ("package", "version", "commit"))
               for entry in config["allowed_a_producers"]):
        raise ValueError("selected A producer tuple is not admitted by execution policy")
    if basis["selected_artifact"]["planner"] not in config["allowed_c_components"]:
        raise ValueError("selected C component tuple is not admitted by execution policy")
    expected_snapshot = {
        "profile": inner["account_snapshot"]["format_profile"],
        "producer_commit": inner["account_snapshot"]["producer_commit"],
    }
    if (basis["selected_artifact"]["b_snapshot"] != expected_snapshot
            or expected_snapshot not in config["allowed_b_snapshots"]):
        raise ValueError("selected B snapshot tuple is not admitted by execution policy")


def build_request_producer(*, package_version: str, source_commit: str, builder_module: str,
                           builder_blob: str, dependency_lock_sha256: str,
                           source_lock_bytes: bytes) -> dict[str, str]:
    """Create the request identity from a previously committed, non-self-referential lock."""
    value = {
        "name": "starhelp-desktop", "package_version": package_version,
        "source_commit": source_commit, "builder_module": builder_module,
        "builder_blob": builder_blob, "dependency_lock_sha256": dependency_lock_sha256,
        "artifact_kind": "source-lock", "artifact_sha256": sha256_hex(source_lock_bytes),
    }
    return validate_request_producer(value)


def load_request_producer_from_source_lock(path: Path) -> dict[str, str]:
    """Validate the exact source-lock artifact bytes before using them in a request."""
    raw = path.read_bytes()
    if len(raw) > 4 * 1024 * 1024:
        raise ValueError("source-lock artifact exceeds the local limit")
    lock = json.loads(raw.decode("utf-8"))
    required = {
        "schema_id", "schema_version", "name", "package_version", "source_commit",
        "builder_module", "builder_blob", "dependency_lock_sha256", "dependencies",
    }
    if not isinstance(lock, dict) or set(lock) != required:
        raise ValueError("source-lock artifact has missing or unknown fields")
    if lock["schema_id"] != "BSourceLock" or lock["schema_version"] != "0.2":
        raise ValueError("unsupported B source-lock schema")
    dependencies = lock["dependencies"]
    if not isinstance(dependencies, list) or not dependencies:
        raise ValueError("source-lock dependency table is empty")
    normalized = []
    paths: set[str] = set()
    builder_path = None
    for item in dependencies:
        if not isinstance(item, dict) or set(item) != {"path", "git_blob", "raw_sha256"}:
            raise ValueError("source-lock dependency entry is malformed")
        if not isinstance(item["path"], str) or not item["path"] or item["path"] in paths:
            raise ValueError("source-lock dependency path is invalid or duplicated")
        paths.add(item["path"])
        if not isinstance(item["git_blob"], str) or not _GIT_OBJECT.fullmatch(item["git_blob"]):
            raise ValueError("source-lock dependency Git blob is invalid")
        _digest(item["raw_sha256"], "source-lock dependency raw digest")
        if item["path"] == "packages/starhelp-desktop/src/starhelp_desktop/producer_v2.py":
            builder_path = item
        normalized.append({"path": item["path"], "git_blob": item["git_blob"],
                           "raw_sha256": item["raw_sha256"]})
    if [item["path"] for item in normalized] != sorted(paths):
        raise ValueError("source-lock dependency table must use stable path ordering")
    if builder_path is None or lock["builder_module"] != "starhelp_desktop.producer_v2":
        raise ValueError("source-lock does not identify the v0.2 builder module")
    if lock["builder_blob"] != builder_path["git_blob"]:
        raise ValueError("source-lock builder blob conflicts with dependency table")
    if hashlib.sha256(canonical_json_bytes(normalized)).hexdigest() != lock[
        "dependency_lock_sha256"
    ]:
        raise ValueError("source-lock dependency table digest mismatch")
    value = {
        "name": lock["name"], "package_version": lock["package_version"],
        "source_commit": lock["source_commit"], "builder_module": lock["builder_module"],
        "builder_blob": lock["builder_blob"],
        "dependency_lock_sha256": lock["dependency_lock_sha256"],
        "artifact_kind": "source-lock", "artifact_sha256": sha256_hex(raw),
    }
    return validate_request_producer(value)
