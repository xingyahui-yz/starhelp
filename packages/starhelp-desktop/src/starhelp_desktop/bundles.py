from __future__ import annotations

import hashlib
import hmac
import json
import math
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Protocol


class BundleRejected(ValueError):
    pass


class SignatureVerifier(Protocol):
    def verify(self, key_id: str, signed_bytes: bytes, signature: bytes) -> bool: ...


class PublicBundleSource(Protocol):
    """Public-only transport. Implementations receive no account/profile object.

    Byte-returning transports preserve the producer's exact serialized release through validation
    and cache activation; object-returning fixture sources use canonical JSON serialization.
    """

    def discover_release(self, current_release_id: str | None) -> str | None: ...

    def fetch_release(self, release_id: str) -> object: ...


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON constant")


def _decode_bundle_json(raw: bytes, *, max_bytes: int = 64 * 1024 * 1024) -> dict[str, Any]:
    if len(raw) > max_bytes:
        raise ValueError("bundle exceeds the 64 MiB size limit")
    value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique_json_object,
                       parse_constant=_reject_json_constant)
    if not isinstance(value, dict):
        raise ValueError("bundle JSON root must be an object")
    return value


def _validate_bundle_tree(root: object, *, max_bytes: int, max_depth: int, max_nodes: int) -> None:
    pending: list[tuple[object, int, bool]] = [(root, 0, False)]
    active_containers: set[int] = set()
    nodes = 0
    encoded_size = 0

    def add_size(amount: int) -> None:
        nonlocal encoded_size
        encoded_size += amount
        if encoded_size > max_bytes:
            raise BundleRejected("bundle exceeds the 64 MiB serialized size limit")

    def json_string_size(value: str) -> int:
        if len(value) > 1_000_000:
            raise BundleRejected("bundle string exceeds the 1,000,000-character limit")
        try:
            return len(json.dumps(value, ensure_ascii=False).encode("utf-8"))
        except (UnicodeEncodeError, ValueError):
            raise BundleRejected("bundle contains an invalid JSON string") from None

    while pending:
        value, depth, leaving = pending.pop()
        if leaving:
            active_containers.remove(id(value))
            continue
        nodes += 1
        if nodes > max_nodes:
            raise BundleRejected("bundle exceeds the JSON node limit")
        if depth > max_depth:
            raise BundleRejected("bundle exceeds the JSON nesting limit")
        if isinstance(value, dict):
            identity = id(value)
            if identity in active_containers:
                raise BundleRejected("bundle contains a circular object reference")
            active_containers.add(identity)
            add_size(2)
            pending.append((value, depth, True))
            for key, item in value.items():
                if not isinstance(key, str):
                    raise BundleRejected("bundle object keys must be strings")
                add_size(json_string_size(key) + 2)
                pending.append((item, depth + 1, False))
                add_size(1)
        elif isinstance(value, list):
            identity = id(value)
            if identity in active_containers:
                raise BundleRejected("bundle contains a circular object reference")
            active_containers.add(identity)
            add_size(2 + len(value))
            pending.append((value, depth, True))
            pending.extend((item, depth + 1, False) for item in reversed(value))
        elif isinstance(value, str):
            add_size(json_string_size(value))
        elif isinstance(value, int) and not isinstance(value, bool):
            if value.bit_length() > 256:
                raise BundleRejected("bundle integer exceeds the 256-bit limit")
            add_size(len(str(value)))
        elif isinstance(value, float):
            if not math.isfinite(value):
                raise BundleRejected("bundle contains a non-finite number")
            add_size(len(repr(value)))
        elif value is None or isinstance(value, bool):
            add_size(5 if value is None else (4 if value else 5))
        else:
            raise BundleRejected("bundle contains a non-JSON value")


class Ed25519Keyring:
    """Verify releases against pinned publisher public keys provided by the coordinator."""

    def __init__(self, trusted_public_keys: dict[str, bytes]) -> None:
        self._keys = dict(trusted_public_keys)

    def verify(self, key_id: str, signed_bytes: bytes, signature: bytes) -> bool:
        public_key = self._keys.get(key_id)
        if public_key is None:
            return False
        try:
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            Ed25519PublicKey.from_public_bytes(public_key).verify(signature, signed_bytes)
            return True
        except ImportError:
            return False
        except Exception:
            return False


@dataclass(frozen=True, slots=True)
class ValidatedBundle:
    release_id: str
    schema_version: str
    payload_json: bytes
    coverage: dict[str, Any]
    verified_at: datetime

    def payload(self) -> dict[str, Any]:
        try:
            return _decode_bundle_json(self.payload_json)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
            raise BundleRejected("cached bundle JSON is invalid") from exc


class BundleValidator:
    """Validates the local v0.1-draft transfer envelope before it can be enabled."""

    SUPPORTED_SCHEMA_VERSIONS = frozenset({"0.1-draft"})
    MAX_BUNDLE_BYTES = 64 * 1024 * 1024
    MAX_JSON_DEPTH = 64
    MAX_JSON_NODES = 500_000

    @staticmethod
    def _canonical(value: object) -> bytes:
        return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                          allow_nan=False).encode("utf-8")

    def validate(
        self,
        envelope: object,
        *,
        supported_capabilities: frozenset[str],
        expected_release_id: str | None = None,
        signature_verifier: SignatureVerifier | None = None,
    ) -> ValidatedBundle:
        """Validate an envelope, preserving exact UTF-8 bytes when the caller supplies them."""
        original_bytes: bytes | None = None
        if isinstance(envelope, bytes):
            original_bytes = envelope
        elif isinstance(envelope, str):
            if len(envelope) > self.MAX_BUNDLE_BYTES:
                raise BundleRejected("bundle exceeds the 64 MiB size limit")
            try:
                original_bytes = envelope.encode("utf-8")
            except UnicodeEncodeError:
                raise BundleRejected("bundle JSON is not valid UTF-8") from None
        if original_bytes is not None:
            if len(original_bytes) > self.MAX_BUNDLE_BYTES:
                raise BundleRejected("bundle exceeds the 64 MiB size limit")
            try:
                envelope = _decode_bundle_json(original_bytes, max_bytes=self.MAX_BUNDLE_BYTES)
            except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError) as exc:
                raise BundleRejected("bundle JSON is invalid") from exc
        if not isinstance(envelope, dict):
            raise BundleRejected("bundle root must be an object")
        _validate_bundle_tree(
            envelope,
            max_bytes=self.MAX_BUNDLE_BYTES,
            max_depth=self.MAX_JSON_DEPTH,
            max_nodes=self.MAX_JSON_NODES,
        )
        manifest = envelope.get("manifest")
        if not isinstance(manifest, dict):
            raise BundleRejected("manifest is required")
        if envelope.get("schema_id") != "PublicBundle" or envelope.get("contract_version") != "0.1-draft":
            raise BundleRejected("unsupported public bundle envelope")
        release_id = manifest.get("index_release_id")
        schema_version = envelope.get("schema_version")
        if not isinstance(release_id, str) or not release_id:
            raise BundleRejected("release ID is missing")
        signature = envelope.get("signature")
        key_id = manifest.get("signing_key_id")
        if signature_verifier is None or not isinstance(signature, str) or not isinstance(key_id, str):
            raise BundleRejected("trusted release signature verification is unavailable")
        try:
            signature_bytes = bytes.fromhex(signature)
        except ValueError:
            raise BundleRejected("release signature encoding is malformed") from None
        if not signature_verifier.verify(key_id, self._canonical(manifest), signature_bytes):
            raise BundleRejected("release manifest signature verification failed")
        if expected_release_id is not None and release_id != expected_release_id:
            raise BundleRejected("bundle release does not match requested release")
        if schema_version not in self.SUPPORTED_SCHEMA_VERSIONS:
            raise BundleRejected("unsupported bundle schema; execution is disabled")
        capabilities = manifest.get("required_capabilities", [])
        if not isinstance(capabilities, list) or not all(isinstance(item, str) for item in capabilities):
            raise BundleRejected("required capabilities are malformed")
        unsupported = set(capabilities) - supported_capabilities
        if unsupported:
            raise BundleRejected("bundle requires unsupported capabilities")

        members = manifest.get("members")
        objects = envelope.get("objects")
        if not isinstance(members, dict) or not isinstance(objects, dict) or not members:
            raise BundleRejected("bundle members and complete objects are required")
        if set(members) != set(objects):
            raise BundleRejected("bundle object dependencies are incomplete")
        for object_id, expected_hash in members.items():
            if not isinstance(expected_hash, str) or len(expected_hash) != 64:
                raise BundleRejected("member hash is malformed")
            actual = hashlib.sha256(self._canonical(objects[object_id])).hexdigest()
            if not hmac.compare_digest(actual, expected_hash):
                raise BundleRejected("bundle member hash mismatch")
        self._check_references(objects)
        coverage = manifest.get("coverage")
        if not isinstance(coverage, dict):
            raise BundleRejected("coverage summary is required")
        if original_bytes is not None:
            payload_json = original_bytes
        else:
            try:
                payload_json = json.dumps(envelope, ensure_ascii=False, sort_keys=True,
                                          separators=(",", ":"), allow_nan=False).encode("utf-8")
            except (TypeError, ValueError):
                raise BundleRejected("bundle contains a non-JSON value") from None
        if len(payload_json) > self.MAX_BUNDLE_BYTES:
            raise BundleRejected("bundle exceeds the 64 MiB size limit")
        return ValidatedBundle(
            release_id=release_id,
            schema_version=schema_version,
            payload_json=payload_json,
            coverage=coverage,
            verified_at=datetime.now(UTC),
        )

    @staticmethod
    def _check_references(objects: dict[str, Any]) -> None:
        object_ids = set(objects)
        for object_id, value in objects.items():
            if not isinstance(value, dict):
                raise BundleRejected(f"object {object_id} must be an object")
            refs = value.get("refs", [])
            if not isinstance(refs, list) or not all(isinstance(ref, str) for ref in refs):
                raise BundleRejected(f"object {object_id} has malformed references")
            missing = set(refs) - object_ids
            if missing:
                raise BundleRejected(f"object {object_id} has missing dependencies")


class PublicBundleCache:
    """Keeps at most two validated public releases and switches current atomically."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.current_file = self.root / "current-release"

    @staticmethod
    def _filename(release_id: str) -> str:
        safe = "".join(char for char in release_id if char.isalnum() or char in "._-")
        if not safe or safe != release_id:
            raise ValueError("unsafe public release ID")
        return f"release-{safe}.json"

    def activate(self, bundle: ValidatedBundle) -> None:
        # The validated immutable bytes are written as-is; callers cannot mutate the signed object
        # graph after verification and smuggle changed members into the active cache.
        body = bundle.payload_json
        destination = self.root / self._filename(bundle.release_id)
        self._atomic_write(destination, body)
        self._atomic_write(self.current_file, bundle.release_id.encode("utf-8"))
        releases = sorted(
            (path for path in self.root.glob("release-*.json")),
            key=lambda path: path.stat().st_mtime_ns,
            reverse=True,
        )
        for old in releases[2:]:
            old.unlink(missing_ok=True)

    def current_release_id(self) -> str | None:
        if not self.current_file.exists():
            return None
        return self.current_file.read_text(encoding="utf-8").strip()

    def available_release_ids(self) -> tuple[str, ...]:
        return tuple(sorted(path.stem.removeprefix("release-") for path in self.root.glob("release-*.json")))

    def read_release(self, release_id: str) -> bytes:
        """Read a cached release by its validated identifier; callers must revalidate it."""
        return (self.root / self._filename(release_id)).read_bytes()

    def inspect_cached_metadata(self, release_id: str) -> dict[str, Any]:
        """Return bounded manifest display fields without authenticating or enabling the bundle.

        UI callers must label this metadata as unverified. Analysis consumers must use
        PublicBundleSynchronizer.load_release(), which checks the signature and object graph.
        """
        raw = self.read_release(release_id)
        envelope = _decode_bundle_json(raw, max_bytes=BundleValidator.MAX_BUNDLE_BYTES)
        _validate_bundle_tree(
            envelope,
            max_bytes=BundleValidator.MAX_BUNDLE_BYTES,
            max_depth=BundleValidator.MAX_JSON_DEPTH,
            max_nodes=BundleValidator.MAX_JSON_NODES,
        )
        manifest = envelope.get("manifest")
        if not isinstance(manifest, dict):
            raise BundleRejected("cached release manifest is unavailable")
        coverage = manifest.get("coverage")
        freshness_keys = (
            "created_at", "published_at", "verified_at", "last_verified_at",
            "valid_until", "expires_at", "freshness", "freshness_status",
        )
        freshness = {
            key: manifest[key]
            for key in freshness_keys
            if key in manifest
            and (isinstance(manifest[key], (str, int, float, bool)) or manifest[key] is None)
        }
        return {
            "declared_release_id": manifest.get("index_release_id"),
            "coverage": coverage if isinstance(coverage, dict) else None,
            "freshness": freshness,
            "cache_file_modified_at": datetime.fromtimestamp(
                (self.root / self._filename(release_id)).stat().st_mtime, UTC
            ).isoformat(),
        }

    @staticmethod
    def _atomic_write(destination: Path, data: bytes) -> None:
        descriptor, name = tempfile.mkstemp(prefix=".bundle.", suffix=".tmp", dir=destination.parent)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise


@dataclass(frozen=True, slots=True)
class BundleSyncResult:
    previous_release_id: str | None
    current_release_id: str | None
    updated: bool


class PublicBundleSynchronizer:
    """Explicitly invoked public release sync with verify-before-activate semantics."""

    _RELEASE_ID = re.compile(r"^[A-Za-z0-9._-]{1,128}$")

    def __init__(
        self,
        cache: PublicBundleCache,
        *,
        validator: BundleValidator | None = None,
        signature_verifier: SignatureVerifier,
        supported_capabilities: frozenset[str],
    ) -> None:
        self._cache = cache
        self._validator = validator or BundleValidator()
        self._signature_verifier = signature_verifier
        self._supported_capabilities = supported_capabilities

    def sync(self, source: PublicBundleSource) -> BundleSyncResult:
        previous = self._cache.current_release_id()
        candidate = source.discover_release(previous)
        if candidate is None or candidate == previous:
            return BundleSyncResult(previous, previous, False)
        if not isinstance(candidate, str) or not self._RELEASE_ID.fullmatch(candidate):
            raise BundleRejected("discovered public release ID is malformed")
        envelope = source.fetch_release(candidate)
        validated = self._validator.validate(
            envelope,
            supported_capabilities=self._supported_capabilities,
            expected_release_id=candidate,
            signature_verifier=self._signature_verifier,
        )
        self._cache.activate(validated)
        return BundleSyncResult(previous, validated.release_id, True)

    def load_current(self) -> ValidatedBundle | None:
        """Reload and cryptographically revalidate the selected cached release."""
        release_id = self._cache.current_release_id()
        if release_id is None:
            return None
        return self.load_release(release_id)

    def load_release(self, release_id: str) -> ValidatedBundle:
        """Validate cached bytes again before any consumer uses their public objects."""
        try:
            raw = self._cache.read_release(release_id)
        except FileNotFoundError:
            raise
        return self._validator.validate(
            raw,
            supported_capabilities=self._supported_capabilities,
            expected_release_id=release_id,
            signature_verifier=self._signature_verifier,
        )
