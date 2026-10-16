"""Extract immutable producer Git objects into C without touching its checkout."""

from __future__ import annotations

import argparse
import io
import re
import subprocess
import sys
import tarfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_producer_source import check_source


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True, type=Path)
    parser.add_argument("--commit", required=True)
    parser.add_argument("--package-subdir", required=True)
    parser.add_argument("--destination", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    destination = args.destination.resolve()
    prefix = args.package_subdir.rstrip("/")
    if not re.fullmatch(r"[0-9a-f]{40}", args.commit) or Path(prefix).is_absolute() or ".." in Path(prefix).parts:
        raise SystemExit("an immutable commit and relative package prefix are required")
    if not destination.is_relative_to(root) or destination.exists():
        raise SystemExit("extract into a new directory inside C's package")
    raw = subprocess.run(["git", "-C", str(args.repository), "archive", "--format=tar", args.commit, prefix], capture_output=True, check=True).stdout
    with tarfile.open(fileobj=io.BytesIO(raw)) as archive:
        for member in archive.getmembers():
            name = member.name.rstrip("/")
            if not (member.isfile() or member.isdir()) or not (name.startswith(prefix + "/") or member.isdir() and (prefix.startswith(name + "/") or name == prefix)):
                raise SystemExit("unexpected producer archive member")
        archive.extractall(destination, filter="data")
    result = check_source(args.repository, args.commit, prefix, destination / prefix)
    print(f"Verified {len(result['file_sha256'])} files from {args.commit}")


if __name__ == "__main__":
    main()
