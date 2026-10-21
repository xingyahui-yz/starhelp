"""Verify a separately fixed B2 host preserves B1 and loads the fixed C wheel.

This is source/load verification only. It does not claim worker/request replay,
candidate build attestation, account acceptance or production trust.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_producer_source import check_source

B1_COMMIT = "103741e02c90ac672017f783058bdd8dacae982e"
C_WHEEL_NAME = "starhelp_planner-0.4.0-py3-none-any.whl"
C_WHEEL_SHA256 = "3b5b8de8f2ef71cd07f1cfb7724cb0a1564f316860232b58728386d52c47aea2"
SEAM = ("models.py", "profiles.py", "producer_request.py", "bundles.py", "storage.py")


def verify_host(repository, source, host_commit, capture, dependency_root, wheel):
    if not re.fullmatch(r"[0-9a-f]{40}", host_commit) or host_commit == B1_COMMIT:
        raise ValueError("supply the actual separately fixed B2 host commit")
    locks = json.loads((capture / "producer-locks.json").read_bytes())
    if locks.get("producer_commit") != B1_COMMIT or locks.get("synthetic_only") is not True:
        raise ValueError("the independently captured B1 source proof is required")
    proof = check_source(repository, host_commit, "packages/starhelp-desktop", source)
    seam = {}
    for name in SEAM:
        path = "src/starhelp_desktop/" + name
        b1_hash = locks["source_proof"]["file_sha256"][path]
        if proof["file_sha256"].get(path) != b1_hash:
            raise ValueError("B2 changed a fixed B1 serializer/encoder dependency: " + path)
        seam[path] = b1_hash
    vendor = source / "packaging/vendor" / C_WHEEL_NAME
    if wheel.name != C_WHEEL_NAME or hashlib.sha256(wheel.read_bytes()).hexdigest() != C_WHEEL_SHA256 or vendor.read_bytes() != wheel.read_bytes():
        raise ValueError("B2 vendor is not the exact fixed C 0.4.0 wheel")
    program = """
import hashlib,json,sys
from pathlib import Path
sys.path[:0]=[str(Path(sys.argv[1])/'src'),sys.argv[2]]
from starhelp_desktop import planner_worker,models,profiles,producer_request
planner,version,profile=planner_worker._load_planner()
vendor=Path(sys.argv[1])/'packaging/vendor/starhelp_planner-0.4.0-py3-none-any.whl'
if not str(planner.__file__).replace('\\\\','/').startswith(str(vendor).replace('\\\\','/')+'/'):
 raise SystemExit('actual C module did not load from the B2 vendor wheel')
if version!='0.4.0' or profile!='starhelp.producers.v0.1' or planner.PLANNER_VERSION!='0.2.0':
 raise SystemExit('actual C module version/profile mismatch')
loaded={}
for module in (planner_worker,models,profiles,producer_request):
 path=Path(module.__file__).resolve()
 loaded[module.__name__]={'path':path.relative_to(Path(sys.argv[1])).as_posix(),'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
print(json.dumps({'component_version':version,'native_rule_version':planner.PLANNER_VERSION,'producer_adapter_profile':profile,'C_module_from_exact_B2_vendor':True,'loaded_B_modules':loaded}))
"""
    completed = subprocess.run([sys.executable, "-I", "-B", "-c", program, str(source), str(dependency_root)], stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, timeout=30, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    load = json.loads(completed.stdout)
    for module in load["loaded_B_modules"].values():
        if proof["file_sha256"].get(module["path"]) != module["sha256"]:
            raise ValueError("loaded B2 module does not match the fixed host Git blob")
    if check_source(repository, host_commit, "packages/starhelp-desktop", source) != proof:
        raise ValueError("B2 source changed during verification")
    return {"synthetic_only": True, "b_host_commit": host_commit, "b_serializer_commit": B1_COMMIT, "b_serializer_profile": locks["format_profile"], "b_host_source_proof": proof, "b1_seam_hashes_equal": seam, "C_wheel_sha256": C_WHEEL_SHA256, "actual_module_load": load, "worker_request_replay_executed": False, "candidate_build_provenance_attested": False, "full_three_party_acceptance": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--b-repository", required=True, type=Path)
    parser.add_argument("--b-source", required=True, type=Path)
    parser.add_argument("--b-host-commit", required=True)
    parser.add_argument("--b1-capture", required=True, type=Path)
    parser.add_argument("--dependency-root", required=True, type=Path)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source, report = args.b_source.resolve(), args.report.resolve()
    if not source.is_relative_to(root) or not report.is_relative_to(root) or report.exists():
        raise SystemExit("use a fixed source copy and new report inside C's component")
    result = verify_host(args.b_repository, source, args.b_host_commit, args.b1_capture.resolve(), args.dependency_root.resolve(), args.wheel.resolve())
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps({"b_host_commit": args.b_host_commit, "seam_files_verified": len(result["b1_seam_hashes_equal"]), "C_module_from_exact_B2_vendor": True, "worker_request_replay_executed": False}))


if __name__ == "__main__":
    main()
