"""Local service entry points and explicit invitation-token provisioning."""

from __future__ import annotations

import argparse
import hashlib
import json
import secrets
import socketserver
import sys
from pathlib import Path
from wsgiref.simple_server import WSGIServer, make_server

from starhelp_knowledge.database import KnowledgeDatabase
from starhelp_knowledge.bundle import verify_public_bundle
from starhelp_knowledge.http import KnowledgeApplication
from starhelp_knowledge.policy import ROLE_PERMISSIONS, TokenAuthenticator
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
    token = subcommands.add_parser("create-token", help="provision one invite identity by role")
    token.add_argument("--auth-config", type=Path, default=_default_auth_path())
    token.add_argument("--actor-id", required=True)
    token.add_argument("--role", required=True, choices=sorted(ROLE_PERMISSIONS))
    token.add_argument("--rotate", action="store_true")
    export = subcommands.add_parser("export-bundle", help="export one validated public release bundle")
    export.add_argument("--database", required=True, type=Path)
    export.add_argument("--release", required=True)
    export.add_argument("--output", required=True, type=Path)
    verify = subcommands.add_parser("verify-bundle", help="verify a previously exported public bundle")
    verify.add_argument("--path", required=True, type=Path)
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
        plaintext = secrets.token_urlsafe(32)
        actors[args.actor_id] = {
            "token_sha256": hashlib.sha256(plaintext.encode("utf-8")).hexdigest(),
            "roles": [args.role],
        }
        _save_actors(args.auth_config, actors)
        print(json.dumps({"actor_id": args.actor_id, "role": args.role, "token": plaintext, "token_config": str(args.auth_config)}))
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
    if args.command == "serve":
        if not 1 <= args.port <= 65535:
            print("port must be between 1 and 65535", file=sys.stderr)
            return 2
        service = KnowledgeService(KnowledgeDatabase(args.database))
        authenticator = TokenAuthenticator(_load_actors(args.auth_config))
        app = KnowledgeApplication(service, authenticator)
        with make_server(args.host, args.port, app, server_class=ThreadedWSGIServer) as server:
            print(f"StarHelp knowledge service listening on {args.host}:{args.port}")
            try:
                server.serve_forever()
            except KeyboardInterrupt:
                return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
