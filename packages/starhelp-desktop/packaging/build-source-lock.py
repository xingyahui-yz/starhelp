from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import tomllib
from pathlib import Path


def canonical(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                          text=True, encoding="utf-8").stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the post-commit B v0.2 source lock")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[3]
    package = root / "packages" / "starhelp-desktop"
    status = git(root, "status", "--porcelain", "--", "packages/starhelp-desktop/src",
                 "packages/starhelp-desktop/pyproject.toml")
    if status:
        raise SystemExit("commit the B v0.2 source before generating source-lock")
    commit = git(root, "rev-parse", "HEAD")
    if len(commit) != 40:
        raise SystemExit("source-lock requires a full Git commit ID")
    project = tomllib.loads((package / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    dependencies = []
    for source in sorted((package / "src" / "starhelp_desktop").glob("*.py")):
        relative = source.relative_to(root).as_posix()
        raw = source.read_bytes()
        blob = git(root, "rev-parse", f"{commit}:{relative}")
        dependencies.append({
            "path": relative, "git_blob": blob,
            "raw_sha256": hashlib.sha256(raw).hexdigest(),
        })
    builder_path = "packages/starhelp-desktop/src/starhelp_desktop/producer_v2.py"
    builder = next(item for item in dependencies if item["path"] == builder_path)
    dependency_digest = hashlib.sha256(canonical(dependencies)).hexdigest()
    document = {
        "schema_id": "BSourceLock", "schema_version": "0.2",
        "name": "starhelp-desktop", "package_version": project["version"],
        "source_commit": commit, "builder_module": "starhelp_desktop.producer_v2",
        "builder_blob": builder["git_blob"],
        "dependency_lock_sha256": dependency_digest,
        "dependencies": dependencies,
    }
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(canonical(document) + b"\n")
    print(json.dumps({
        "path": output.as_posix(), "source_commit": commit,
        "builder_blob": builder["git_blob"],
        "dependency_lock_sha256": dependency_digest,
        "artifact_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "dependency_count": len(dependencies),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
