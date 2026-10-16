"""Compare a temporary producer copy to fixed Git objects without changing it."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path


def check_source(repository: Path, commit: str, package_subdir: str, source_root: Path) -> dict:
    def git(*args):
        return subprocess.run(["git", "-C", str(repository), *args], check=True, capture_output=True).stdout
    paths = git("ls-tree", "-r", "--name-only", commit, "--", package_subdir).decode("utf-8").splitlines()
    expected = {path.removeprefix(package_subdir + "/"): path for path in paths}
    actual = {str(path.relative_to(source_root)).replace("\\", "/") for path in source_root.rglob("*") if path.is_file()}
    if actual != set(expected):
        raise ValueError("temporary producer file set differs from the fixed Git tree")
    hashes = {}
    for relative, path in expected.items():
        reference = git("show", f"{commit}:{path}")
        if (source_root / relative).read_bytes() != reference:
            raise ValueError(f"temporary producer source differs from pinned commit: {relative}")
        hashes[relative] = hashlib.sha256(reference).hexdigest()
    return {"commit": commit, "package_subdir": package_subdir, "git_tree": git("rev-parse", f"{commit}:{package_subdir}").decode().strip(), "all_files_verified": True, "file_sha256": hashes}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--package-subdir", required=True)
    parser.add_argument("--source-root", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if not args.report.resolve().is_relative_to(root):
        raise SystemExit("source verification report must stay in C's package")
    result = check_source(args.repository, args.commit, args.package_subdir, args.source_root.resolve())
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"commit": args.commit, "verified_files": len(result["file_sha256"]), "all_files_verified": True}))


if __name__ == "__main__":
    main()
