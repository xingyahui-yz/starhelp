"""Capture fixed B's native-order compact encoding for B's request builder replay."""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_producer_source import check_source

B_COMMIT = "045965bce4fbc38a3baa79b594535c9dd983d776"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--b-repository", required=True, type=Path)
    parser.add_argument("--b-source", required=True, type=Path)
    parser.add_argument("--base-capture", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    component = Path(__file__).resolve().parents[1]
    source, output = args.b_source.resolve(), args.output.resolve()
    if not source.is_relative_to(component) or not output.is_relative_to(component) or output.exists():
        raise SystemExit("use a fixed source copy and a new output directory inside C")
    locks = json.loads((args.base_capture / "consumer-capture-locks.json").read_bytes())
    if locks.get("synthetic_only") is not True or locks.get("b_snapshot_commit") != B_COMMIT:
        raise SystemExit("only the fixed synthetic B capture is accepted")
    name = locks["b_snapshot"]
    if Path(name).name != name:
        raise SystemExit("invalid capture filename")
    original = (args.base_capture / name).read_bytes()
    original_sha = hashlib.sha256(original).hexdigest()
    if original_sha != locks["files"][name]:
        raise SystemExit("original snapshot bytes changed")
    proof = check_source(args.b_repository, B_COMMIT, "packages/starhelp-desktop", source)
    program = """
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(sys.argv[1]) / 'src'))
from starhelp_desktop.profiles import _snapshot_from_dict, _snapshot_to_dict
snapshot = _snapshot_from_dict(json.loads(sys.stdin.buffer.read()))
raw = json.dumps(_snapshot_to_dict(snapshot), ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')
sys.stdout.buffer.write(raw)
"""
    raw = subprocess.run(
        [sys.executable, "-I", "-B", "-c", program, str(source)], input=original,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=30,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    ).stdout
    if json.loads(raw) != json.loads(original):
        raise SystemExit("fixed B serialization changed snapshot values")
    if check_source(args.b_repository, B_COMMIT, "packages/starhelp-desktop", source) != proof:
        raise SystemExit("fixed B source changed during capture")
    output.mkdir(parents=True)
    filename = "b-045965b-compact-v1.json"
    (output / filename).write_bytes(raw)
    result = {
        "synthetic_only": True, "producer_commit": B_COMMIT,
        "entry_point": "starhelp_desktop.profiles._snapshot_to_dict",
        "encoding_profile": "utf8-json-native-order-compact-no-newline-v1",
        "encoding": {"ensure_ascii": False, "separators": [",", ":"], "allow_nan": False, "sort_keys": False, "trailing_newline": False},
        "original_snapshot_sha256": original_sha,
        "decoded_json_values_unchanged": True, "file": filename,
        "raw_sha256": hashlib.sha256(raw).hexdigest(), "source_proof": proof,
    }
    (output / "producer-locks.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"producer_commit": B_COMMIT, "raw_sha256": result["raw_sha256"], "decoded_json_values_unchanged": True}))


if __name__ == "__main__":
    main()
