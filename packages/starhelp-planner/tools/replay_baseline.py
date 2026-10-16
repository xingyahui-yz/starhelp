"""Replay locked baseline outputs using either a source tree or installed C wheel."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-dir", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    parser.add_argument("--installed-root", type=Path)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--consumer-source-commit")
    args = parser.parse_args()
    if args.installed_root:
        sys.path.insert(0, str(args.installed_root.resolve()))
    from starhelp_planner.adapters import analyze_producers
    from starhelp_planner.adapters.b_snapshot import B_PROFILE, adapt_snapshot
    from starhelp_planner.adapters.common import ADAPTER_PROFILE, A_BASELINE, B_COMMIT
    import starhelp_planner

    if args.installed_root and not Path(starhelp_planner.__file__).resolve().is_relative_to(args.installed_root.resolve()):
        raise SystemExit("C was not imported from the requested isolated installation")
    capture = args.capture_dir.resolve()
    locks = json.loads((capture / "producer-locks.json").read_bytes())
    def envelope(producer, key, profile, commit):
        entry = locks[key]
        raw = (capture / entry["file"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != entry["raw_sha256"]:
            raise SystemExit("captured producer output changed")
        return {"producer": producer, "producer_commit": commit, "format_profile": profile, "raw_json": raw.decode("utf-8"), "sha256": entry["raw_sha256"]}
    context = json.loads((capture / "caller-context.json").read_bytes())
    request = {
        "schema_id": "ProducerAnalysisRequest", "schema_version": "0.1", "adapter_profile": ADAPTER_PROFILE,
        "request_id": "fixture:baseline-replay",
        "public_bundle": envelope("starhelp_knowledge", "a", "starhelp.knowledge.native.313508f", A_BASELINE),
        "account_snapshot": envelope("starhelp_desktop", "b", B_PROFILE, B_COMMIT),
        "authorization_context": context,
    }
    result = analyze_producers(request)
    normalized, b_proof, diagnostics = adapt_snapshot(request["account_snapshot"], context, [])
    report = {
        "synthetic_only": True, "execution": "isolated installed wheel" if args.installed_root else "source tree",
        "producer_locks": {key: locks[key] for key in ("a", "b")},
        "baseline_result": result, "snapshot_mapping": {"proof": b_proof, "coverage": normalized["coverage"], "diagnostics": diagnostics},
        "positive_interoperability_accepted": False,
        "consumer_source_commit": args.consumer_source_commit,
        "consumer_wheel_sha256": hashlib.sha256(args.wheel.read_bytes()).hexdigest() if args.wheel else None,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8", newline="\n")
    if result.get("error", {}).get("code") != "producer_semantics_missing":
        raise SystemExit("baseline did not produce the expected explicit semantic refusal")
    print(json.dumps({"baseline_integrity": "valid", "executable_conversion": "refused", "positive_interoperability_accepted": False}))


if __name__ == "__main__":
    main()
