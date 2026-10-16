"""In-memory signature verification using caller-pinned public keys, never files."""

from __future__ import annotations

import hashlib
from typing import Any

from .common import canonical, fail


def verify_manifest_signature(manifest: dict[str, Any], signature: Any, trust: Any) -> dict[str, Any]:
    if type(trust) is not dict or trust.get("purpose") != "synthetic-test" or type(trust.get("public_keys")) is not dict:
        fail("signature_trust_unavailable", "this technical profile requires separately configured synthetic-test public keys")
    key_id = manifest.get("signing_key_id")
    public_hex = trust["public_keys"].get(key_id)
    if type(key_id) is not str or type(public_hex) is not str:
        fail("unknown_signing_key", "signing key is not in the caller's pinned test keyring")
    try:
        public_bytes = bytes.fromhex(public_hex)
        signature_bytes = bytes.fromhex(signature) if type(signature) is str else b""
    except ValueError:
        fail("invalid_signature", "signature/public key encoding is invalid")
    if len(public_bytes) != 32 or len(signature_bytes) != 64:
        fail("invalid_signature", "signature/public key has an invalid size")
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError:
        fail("signature_verification_unavailable", "install the optional producer-signature dependency; no verification bypass is available")
    try:
        Ed25519PublicKey.from_public_bytes(public_bytes).verify(signature_bytes, canonical(manifest))
    except Exception:
        fail("invalid_signature", "original manifest signature verification failed")
    return {
        "signature_verified": True, "signature_algorithm": "Ed25519",
        "signing_key_id": key_id, "public_key_sha256": hashlib.sha256(public_bytes).hexdigest(),
        "public_key_encoding": "raw-32-byte-Ed25519",
        "trust_basis": "caller-pinned synthetic-test public key", "production_trust_established": False,
    }
