"""Local service entry points and explicit invitation-token provisioning."""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import socketserver
import sys
from pathlib import Path
from urllib.parse import quote
from wsgiref.simple_server import WSGIServer, make_server

from starhelp_knowledge import __version__
from starhelp_knowledge.bundle import verify_public_bundle
from starhelp_knowledge.database import KnowledgeDatabase
from starhelp_knowledge.distribution import (
    DISTRIBUTION_CAPABILITY,
    PLANNER_CAPABILITY,
    export_distribution_from_service,
    verify_distribution_envelope,
)
from starhelp_knowledge.errors import KnowledgeError
from starhelp_knowledge.fixture import build_fixture_artifacts
from starhelp_knowledge.http import KnowledgeApplication
from starhelp_knowledge.policy import ROLE_PERMISSIONS, TokenAuthenticator
from starhelp_knowledge.public_distribution import (
    CATALOG_PROFILE,
    REVOCATIONS_PROFILE,
    PublicDistributionStore,
    sign_metadata,
)
from starhelp_knowledge.s3_fixture import build_s3_fixture_artifacts
from starhelp_knowledge.service import KnowledgeService


class ThreadedWSGIServer(socketserver.ThreadingMixIn, WSGIServer):
    daemon_threads = True


def _default_auth_path() -> Path:
    return Path.home() / ".starhelp-knowledge" / "auth.json"


def _load_actors(path: Path) -> dict[str, dict[str, object]]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SystemExit("Auth config could not be read; admin endpoints remain unavailable.") from exc
    actors = data.get("actors") if isinstance(data, dict) else None
    if not isinstance(actors, dict):
        raise SystemExit("Auth config must contain an actors object.")
    clean: dict[str, dict[str, object]] = {}
    for actor_id, actor in actors.items():
        if not isinstance(actor_id, str) or not isinstance(actor, dict):
            continue
        token_hash, roles = actor.get("token_sha256"), actor.get("roles")
        if isinstance(token_hash, str) and isinstance(roles, list):
            clean[actor_id] = {"token_sha256": token_hash, "roles": roles}
    return clean


def _save_actors(path: Path, actors: dict[str, dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps({"actors": actors}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="starhelp-knowledge")
    subcommands = parser.add_subparsers(dest="command", required=True)
    init = subcommands.add_parser("init", help="create or migrate the public knowledge database")
    init.add_argument("--database", required=True, type=Path)
    serve = subcommands.add_parser("serve", help="run the local HTTP service")
    serve.add_argument("--database", required=True, type=Path)
    serve.add_argument("--auth-config", type=Path, default=_default_auth_path())
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8765)
    serve.add_argument("--distribution-store", type=Path)
    serve.add_argument("--instance-id", default="starhelp-knowledge-local")
    token = subcommands.add_parser("create-token", help="provision one invite identity with one or more roles")
    token.add_argument("--auth-config", type=Path, default=_default_auth_path())
    token.add_argument("--actor-id", required=True)
    token.add_argument(
        "--role",
        required=True,
        action="append",
        choices=sorted(ROLE_PERMISSIONS),
        help="assign a role; repeat to combine least-privilege permissions",
    )
    token.add_argument("--rotate", action="store_true")
    export = subcommands.add_parser("export-bundle", help="export one validated public release bundle")
    export.add_argument("--database", required=True, type=Path)
    export.add_argument("--release", required=True)
    export.add_argument("--output", required=True, type=Path)
    verify = subcommands.add_parser("verify-bundle", help="verify a previously exported public bundle")
    verify.add_argument("--path", required=True, type=Path)
    export_distribution = subcommands.add_parser(
        "export-distribution", help="sign a published release using an external Ed25519 key"
    )
    export_distribution.add_argument("--database", required=True, type=Path)
    export_distribution.add_argument("--release", required=True)
    export_distribution.add_argument("--profile", choices=["starhelp.local.v0.2"], required=True)
    export_distribution.add_argument("--private-key", required=True, type=Path)
    export_distribution.add_argument("--key-id", required=True)
    export_distribution.add_argument("--producer-commit", required=True)
    export_distribution.add_argument("--output", required=True, type=Path)
    verify_distribution = subcommands.add_parser(
        "verify-distribution", help="independently verify B signature, A release and C profile hashes"
    )
    verify_distribution.add_argument("--path", required=True, type=Path)
    verify_distribution.add_argument("--trusted-public-key", required=True, type=Path)
    verify_distribution.add_argument("--trusted-key-id", required=True)
    verify_distribution.add_argument("--supported-capability", action="append")
    verify_distribution.add_argument("--planner-capability", action="append")
    fixture = subcommands.add_parser(
        "build-fixture-distribution", help="build deterministic synthetic artifacts with a test-only key"
    )
    fixture.add_argument("--output-dir", required=True, type=Path)
    fixture.add_argument("--b-root", required=True, type=Path)
    fixture.add_argument("--overwrite", action="store_true")
    s3_fixture = subcommands.add_parser(
        "build-s3-interop-fixture", help="build the frozen three-mode S3 synthetic delivery"
    )
    s3_fixture.add_argument("--output-dir", required=True, type=Path)
    s3_fixture.add_argument("--b-root", required=True, type=Path)
    publish = subcommands.add_parser(
        "publish-public-distribution", help="verify and publish immutable synthetic public distribution bytes"
    )
    publish.add_argument("--config", required=True, type=Path)
    publish.add_argument("--metadata-private-key", required=True, type=Path)
    publish.add_argument("--output-store", required=True, type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.command == "init":
        version = KnowledgeDatabase(args.database).migrate()
        print(json.dumps({"database": str(args.database), "schema_version": version}))
        return 0
    if args.command == "create-token":
        actors = _load_actors(args.auth_config)
        if args.actor_id in actors and not args.rotate:
            print("actor already exists; pass --rotate to replace its token", file=sys.stderr)
            return 2
        roles = list(dict.fromkeys(args.role))
        plaintext = secrets.token_urlsafe(32)
        actors[args.actor_id] = {
            "token_sha256": hashlib.sha256(plaintext.encode("utf-8")).hexdigest(),
            "roles": roles,
        }
        _save_actors(args.auth_config, actors)
        response = {"actor_id": args.actor_id, "roles": roles, "token": plaintext, "token_config": str(args.auth_config)}
        if len(roles) == 1:
            response["role"] = roles[0]
        print(json.dumps(response))
        print("Store this token securely; it is shown once and is not written to the config file.", file=sys.stderr)
        return 0
    if args.command == "export-bundle":
        service = KnowledgeService(KnowledgeDatabase(args.database))
        bundle = service.get_release_bundle(args.release)
        digest = verify_public_bundle(bundle)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        temporary = args.output.with_suffix(args.output.suffix + ".tmp")
        temporary.write_text(json.dumps(bundle, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n", encoding="utf-8")
        temporary.replace(args.output)
        print(json.dumps({"output": str(args.output), "release_id": bundle["manifest"]["index_release_id"], "content_hash": digest}))
        return 0
    if args.command == "verify-bundle":
        try:
            bundle = json.loads(args.path.read_text(encoding="utf-8"))
            digest = verify_public_bundle(bundle)
        except (OSError, json.JSONDecodeError) as exc:
            print("bundle could not be read as JSON", file=sys.stderr)
            return 2
        print(json.dumps({"path": str(args.path), "content_hash": digest, "valid": True}))
        return 0
    if args.command == "export-distribution":
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

            key = serialization.load_pem_private_key(args.private_key.read_bytes(), password=None)
            if not isinstance(key, Ed25519PrivateKey):
                raise ValueError
            service = KnowledgeService(KnowledgeDatabase(args.database))
            envelope = export_distribution_from_service(
                service,
                args.release,
                producer_version=__version__,
                producer_commit=args.producer_commit,
                signing_private_key=key,
                signing_key_id=args.key_id,
            )
            args.output.parent.mkdir(parents=True, exist_ok=True)
            temporary = args.output.with_suffix(args.output.suffix + ".tmp")
            temporary.write_bytes(json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n")
            temporary.replace(args.output)
        except ImportError:
            print("the optional cryptography package is required for signing", file=sys.stderr)
            return 2
        except KnowledgeError as exc:
            print(f"distribution export failed: {exc.code}", file=sys.stderr)
            return 2
        except Exception:
            print("distribution export failed", file=sys.stderr)
            return 2
        print(json.dumps({"output": str(args.output), "release_id": args.release, "profile": args.profile, "signing_key_id": args.key_id}))
        return 0
    if args.command == "verify-distribution":
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

            envelope = json.loads(args.path.read_text(encoding="utf-8"))
            key = serialization.load_pem_public_key(args.trusted_public_key.read_bytes())
            if not isinstance(key, Ed25519PublicKey):
                raise ValueError
            public_bytes = key.public_bytes_raw()
            result = verify_distribution_envelope(
                envelope,
                trusted_public_keys={args.trusted_key_id: public_bytes},
                trusted_key_id=args.trusted_key_id,
                supported_distribution_capabilities=set(args.supported_capability or [DISTRIBUTION_CAPABILITY]),
                supported_planner_capabilities=set(args.planner_capability or [PLANNER_CAPABILITY]),
            )
        except ImportError:
            print("the optional cryptography package is required for verification", file=sys.stderr)
            return 2
        except KnowledgeError as exc:
            print(f"distribution verification failed: {exc.code}", file=sys.stderr)
            return 2
        except Exception:
            print("distribution could not be verified", file=sys.stderr)
            return 2
        print(json.dumps({"path": str(args.path), "valid": True, **result}, sort_keys=True))
        return 0
    if args.command == "build-fixture-distribution":
        try:
            result = build_fixture_artifacts(args.output_dir, b_root=args.b_root, overwrite=args.overwrite)
        except ImportError:
            print("the optional cryptography package is required for fixture signing", file=sys.stderr)
            return 2
        except KnowledgeError as exc:
            print(f"synthetic fixture artifacts could not be created: {exc.code}", file=sys.stderr)
            return 2
        except Exception:
            print("synthetic fixture artifacts could not be created", file=sys.stderr)
            return 2
        print(json.dumps({**result, "fixture_only": True}, sort_keys=True))
        return 0
    if args.command == "build-s3-interop-fixture":
        try:
            result = build_s3_fixture_artifacts(args.output_dir, b_root=args.b_root)
        except ImportError:
            print("the optional cryptography package is required for fixture signing", file=sys.stderr)
            return 2
        except KnowledgeError as exc:
            print(f"S3 synthetic fixture artifacts could not be created: {exc.code}", file=sys.stderr)
            return 2
        except FileExistsError:
            print("S3 fixture output path already contains immutable artifacts", file=sys.stderr)
            return 2
        except Exception:
            print("S3 synthetic fixture artifacts could not be created", file=sys.stderr)
            return 2
        print(json.dumps({**result, "fixture_only": True}, sort_keys=True))
        return 0
    if args.command == "publish-public-distribution":
        try:
            from cryptography.hazmat.primitives import serialization
            from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

            config = json.loads(args.config.read_text(encoding="utf-8"))
            if not isinstance(config, dict) or set(config) != {
                "envelope_paths", "envelope_trusted_public_key", "envelope_trusted_key_id",
                "metadata_key_id", "catalog_payload", "revocations_payload",
            }:
                raise ValueError
            envelope_paths = config["envelope_paths"]
            if not isinstance(envelope_paths, dict) or not envelope_paths:
                raise ValueError
            envelope_key = serialization.load_pem_public_key(Path(config["envelope_trusted_public_key"]).read_bytes())
            if not isinstance(envelope_key, Ed25519PublicKey):
                raise ValueError
            envelope_key_bytes = envelope_key.public_bytes_raw()
            verified_envelopes: dict[str, bytes] = {}
            for release_id, path_value in envelope_paths.items():
                envelope_raw = Path(path_value).read_bytes()
                envelope = json.loads(envelope_raw.decode("utf-8"))
                result = verify_distribution_envelope(
                    envelope,
                    trusted_public_keys={config["envelope_trusted_key_id"]: envelope_key_bytes},
                    trusted_key_id=config["envelope_trusted_key_id"],
                    supported_distribution_capabilities={DISTRIBUTION_CAPABILITY},
                    supported_planner_capabilities={PLANNER_CAPABILITY},
                )
                if envelope.get("manifest", {}).get("index_release_id") != release_id or result.get("release_id") != release_id:
                    raise ValueError
                verified_envelopes[release_id] = envelope_raw
            listed_release_ids = {item.get("release_id") for item in config["catalog_payload"].get("distributions", [])}
            if listed_release_ids != set(verified_envelopes):
                raise ValueError
            metadata_key = serialization.load_pem_private_key(args.metadata_private_key.read_bytes(), password=None)
            if not isinstance(metadata_key, Ed25519PrivateKey):
                raise ValueError
            revocations_raw = sign_metadata(
                REVOCATIONS_PROFILE, config["revocations_payload"], signing_private_key=metadata_key,
                key_id=config["metadata_key_id"],
            )
            catalog_payload = dict(config["catalog_payload"])
            descriptors = config["catalog_payload"]["distributions"]
            catalog_payload["distributions"] = []
            for descriptor in descriptors:
                entry = dict(descriptor)
                artifact_raw = verified_envelopes[entry["release_id"]]
                entry["envelope_sha256"] = hashlib.sha256(artifact_raw).hexdigest()
                entry["size_bytes"] = len(artifact_raw)
                catalog_payload["distributions"].append(entry)
            rev_snapshot = dict(catalog_payload["revocation_snapshot"])
            rev_snapshot.update({
                "path": f"/v1/distribution-revocations?profile={catalog_payload['consumer_profile']}&channel={quote(catalog_payload['channel'], safe='')}",
                "sha256": hashlib.sha256(revocations_raw).hexdigest(),
                "size_bytes": len(revocations_raw),
                "sequence": config["revocations_payload"]["sequence"],
            })
            catalog_payload["revocation_snapshot"] = rev_snapshot
            catalog_raw = sign_metadata(
                CATALOG_PROFILE, catalog_payload, signing_private_key=metadata_key,
                key_id=config["metadata_key_id"],
            )
            store = PublicDistributionStore(args.output_store)
            for release_id, envelope_raw in verified_envelopes.items():
                store.store_artifact(release_id, envelope_raw)
            metadata_public = metadata_key.public_key().public_bytes_raw()
            receipt = store.publish_metadata(
                catalog_raw,
                revocations_raw,
                trusted_keys={config["metadata_key_id"]: {
                    "public_key": metadata_public,
                    "purposes": ["synthetic-catalog", "synthetic-revocations"],
                    "not_before": "1970-01-01T00:00:00Z",
                    "not_after": "9999-12-31T23:59:59Z",
                    "revoked": False,
                }},
                purpose_prefix="synthetic",
            )
        except ImportError:
            print("the optional cryptography package is required for signed distribution publishing", file=sys.stderr)
            return 2
        except KnowledgeError as exc:
            print(f"public distribution publish failed: {exc.code}", file=sys.stderr)
            return 2
        except Exception as exc:
            print(f"public distribution publish failed ({type(exc).__name__}); inspect configuration without exposing keys", file=sys.stderr)
            return 2
        print(json.dumps({**receipt, "fixture_only": True}, sort_keys=True))
        return 0
    if args.command == "serve":
        if not 1 <= args.port <= 65535:
            print("port must be between 1 and 65535", file=sys.stderr)
            return 2
        if args.host != "127.0.0.1":
            print("serve is restricted to the fixed loopback address 127.0.0.1", file=sys.stderr)
            return 2
        if not args.instance_id or len(args.instance_id) > 120 or any(ord(ch) < 33 or ord(ch) > 126 for ch in args.instance_id):
            print("instance-id must be a short printable non-sensitive identifier", file=sys.stderr)
            return 2
        service = KnowledgeService(KnowledgeDatabase(args.database))
        authenticator = TokenAuthenticator(_load_actors(args.auth_config))
        distribution_store = PublicDistributionStore(args.distribution_store) if args.distribution_store else None
        app = KnowledgeApplication(service, authenticator, distribution_store=distribution_store, instance_id=args.instance_id)
        with make_server(args.host, args.port, app, server_class=ThreadedWSGIServer) as server:
            print(f"StarHelp knowledge service listening on {args.host}:{args.port}")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
