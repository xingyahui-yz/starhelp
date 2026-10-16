"""Exercise B's actual pinned public-bundle validator, with real Ed25519 keys."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_producer_source import check_source

B_COMMIT = "045965bce4fbc38a3baa79b594535c9dd983d776"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--b-source", required=True, type=Path)
    parser.add_argument("--b-repository", required=True, type=Path)
    parser.add_argument("--bundle", required=True, type=Path)
    parser.add_argument("--expected-sha256", required=True)
    parser.add_argument("--expected-release", required=True)
    parser.add_argument("--public-key", type=Path)
    parser.add_argument("--key-id")
    parser.add_argument("--dependency-root", type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--expect-rejection", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if not args.report.resolve().is_relative_to(root):
        raise SystemExit("report must stay within C's package")
    source = args.b_source.resolve()
    proof = check_source(args.b_repository, B_COMMIT, "packages/starhelp-desktop", source)
    raw = args.bundle.read_bytes()
    if hashlib.sha256(raw).hexdigest() != args.expected_sha256:
        raise SystemExit("A producer bytes differ from the locked artifact")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(source / "src"))
    if args.dependency_root:
        sys.path.insert(0, str(args.dependency_root.resolve()))
    from starhelp_desktop.bundles import BundleRejected, BundleValidator, Ed25519Keyring
    import starhelp_desktop
    if not Path(starhelp_desktop.__file__).resolve().is_relative_to(source):
        raise SystemExit("B was not loaded from the fixed producer copy")
    public_keys, key_sha, crypto_version = {}, None, None
    if args.public_key:
        if not args.key_id:
            raise SystemExit("a separate pinned key ID is required")
        import cryptography
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        public_key = serialization.load_pem_public_key(args.public_key.read_bytes())
        if not isinstance(public_key, Ed25519PublicKey):
            raise SystemExit("fixture trust key must be Ed25519")
        public_bytes = public_key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
        public_keys[args.key_id] = public_bytes
        key_sha = hashlib.sha256(public_bytes).hexdigest()
        crypto_version = cryptography.__version__
    error = None
    try:
        validated = BundleValidator().validate(
            json.loads(raw), supported_capabilities=frozenset({"starhelp.knowledge-distribution.v1"}),
            expected_release_id=args.expected_release, signature_verifier=Ed25519Keyring(public_keys),
        )
        accepted = True
        release = validated.release_id
    except BundleRejected as exc:
        accepted, release, error = False, None, str(exc)
    result = {
        "synthetic_only": True, "b_producer_commit": B_COMMIT,
        "validator": "starhelp_desktop.bundles.BundleValidator", "signature_verifier": "starhelp_desktop.bundles.Ed25519Keyring",
        "a_artifact_sha256": args.expected_sha256, "expected_release": args.expected_release,
        "key_id": args.key_id, "public_key_sha256": key_sha, "cryptography_version": crypto_version,
        "accepted": accepted, "release": release, "error": error,
        "source_git_tree": proof["git_tree"], "all_source_files_verified": True,
        "production_trust_established": False,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"accepted": accepted, "expected_rejection": args.expect_rejection, "error": error}))
    if accepted == args.expect_rejection:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
