"""Run a committed A fixture/export command from an isolated fixed checkout."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_producer_source import check_source


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--a-source", required=True, type=Path)
    parser.add_argument("--a-repository", required=True, type=Path)
    parser.add_argument("--a-commit", required=True)
    parser.add_argument("--b-repository", required=True, type=Path)
    parser.add_argument("--dependency-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--fixture-kind", choices=("legacy", "s3"), default="legacy")
    parser.add_argument("--artifact-commit")
    args = parser.parse_args()
    package = Path(__file__).resolve().parents[1]
    source, output = args.a_source.resolve(), args.output.resolve()
    if not output.is_relative_to(package):
        raise SystemExit("producer output must stay within C's package")
    if output.exists():
        raise SystemExit("use a new capture directory; captured producer outputs are immutable")
    proof = check_source(args.a_repository, args.a_commit, "packages/starhelp-knowledge", source)
    producer_root = source.parent.parent
    actual_head = subprocess.run(["git", "-C", str(producer_root), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
    if actual_head != args.a_commit:
        raise SystemExit("A's exporter must run from a detached producer checkout at the requested commit")
    sys.dont_write_bytecode = True
    sys.path[:0] = [str(source / "src"), str(args.dependency_root.resolve())]
    from starhelp_knowledge.cli import main as producer_main
    from starhelp_knowledge import __version__ as producer_version
    # This is the producer's own fixture publication/export entry, not C-made JSON.
    command = "build-s3-interop-fixture" if args.fixture_kind == "s3" else "build-fixture-distribution"
    result = producer_main([command, "--output-dir", str(output), "--b-root", str(args.b_repository)])
    if result != 0:
        raise SystemExit("A fixture/export command failed")
    file = output / ("starhelp-interop-min-v0.1-s3.bpublic.json" if args.fixture_kind == "s3" else "knowledge-planner-fixture-v1.bpublic.json")
    public_key = output / "fixture-ed25519-public.pem"
    result = producer_main(["verify-distribution", "--path", str(file), "--trusted-public-key", str(public_key), "--trusted-key-id", "starhelp-fixture-ed25519-v1", "--supported-capability", "starhelp.knowledge-distribution.v1"])
    if result != 0:
        raise SystemExit("A's own distribution verification failed")
    bundle = json.loads(file.read_bytes())
    release = bundle["manifest"]["index_release_id"]
    projected = bundle["objects"][f"planner-view:{release}"]["bundle"]
    if projected["manifest"]["source_proof"]["producer_commit"] != args.a_commit:
        raise SystemExit("A output producer commit does not match the fixed executing source")
    # Confirm that the invoked export did not edit producer source files.
    check_source(args.a_repository, args.a_commit, "packages/starhelp-knowledge", source)
    locks = {
        "synthetic_only": True, "a_producer_commit": args.a_commit, "a_package_version": producer_version,
        "entry_point": "starhelp_knowledge.cli.main " + command,
        "independent_verifier": "starhelp_knowledge.cli.main verify-distribution",
        "distribution_profile": bundle["manifest"]["distribution_profile"], "release_id": release,
        "a_artifact": file.name, "a_raw_sha256": hashlib.sha256(file.read_bytes()).hexdigest(),
        "fixture_public_key": public_key.name, "fixture_key_id": "starhelp-fixture-ed25519-v1",
        "b_snapshot_commit": "045965bce4fbc38a3baa79b594535c9dd983d776",
        "b_snapshot": "synthetic-b-snapshot-045965b.json",
        "source_proof": proof,
        "files": {path.name: hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(output.iterdir()) if path.is_file() and path.suffix in {".json", ".txt", ".pem"}},
        "production_trust_established": False,
    }
    if args.artifact_commit:
        artifact_prefix = "packages/starhelp-knowledge/artifacts/" + ("interop-min-v0.1-s3/" if args.fixture_kind == "s3" else "")
        matches = {}
        for name, expected in locks["files"].items():
            reference = subprocess.run(["git", "-C", str(args.a_repository), "show", f"{args.artifact_commit}:{artifact_prefix}{name}"], check=True, capture_output=True).stdout
            if reference != (output / name).read_bytes():
                raise SystemExit("regenerated artifact differs from its fixed delivery Git blob")
            matches[name] = expected
        locks.update(official_delivery_artifact_commit=args.artifact_commit, official_git_blob_bytes_match=matches)
    (output / "consumer-capture-locks.json").write_text(json.dumps(locks, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"a_producer_commit": args.a_commit, "a_raw_sha256": locks["a_raw_sha256"], "release": release}))


if __name__ == "__main__":
    main()
