"""Replay actual locked A/B outputs against an independently installed C wheel."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import sys
import zipfile
from copy import deepcopy
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture-dir", required=True, type=Path)
    parser.add_argument("--b-cases", required=True, type=Path)
    parser.add_argument("--installed-root", required=True, type=Path)
    parser.add_argument("--dependency-root", required=True, type=Path)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--consumer-source-commit", required=True)
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    if not args.report.resolve().is_relative_to(root):
        raise SystemExit("replay reports must stay inside C's package")
    installed = args.installed_root.resolve()
    sys.path[:0] = [str(installed), str(args.dependency_root.resolve()), str(Path(__file__).resolve().parent)]
    from interop_inputs import CapturedInputs, result_summary
    import starhelp_planner
    import cryptography
    from starhelp_planner import analyze_producers
    if not Path(starhelp_planner.__file__).resolve().is_relative_to(installed):
        raise SystemExit("C was not imported from the isolated wheel installation")
    with zipfile.ZipFile(args.wheel) as archive:
        for name in archive.namelist():
            if name.startswith("starhelp_planner/") and name.endswith(".py"):
                if (installed / name).read_bytes() != archive.read(name):
                    raise SystemExit("installed C implementation does not match the pinned wheel")
    data = CapturedInputs(args.capture_dir, args.b_cases)
    cases = []

    def run(name, request, predicate):
        before = deepcopy(request)
        result = analyze_producers(request)
        unchanged = before == request
        passed = unchanged and bool(predicate(result))
        cases.append({"name": name, "outcome": "passed" if passed else "failed", "inputs_unchanged": unchanged, "a_raw_sha256": request["public_bundle"]["sha256"], "b_raw_sha256": request["account_snapshot"]["sha256"], "result": result_summary(result)})
        return result

    def available(result):
        analysis = result.get("analysis") or {}
        return [*analysis.get("current_equipment_plans", []), *analysis.get("rearrangement_plans", [])]

    for stage in data.view["stages"]:
        suffix = stage["stage_id"]
        template = next(item for item in data.view["templates"] if suffix in item["stage_ids"])
        variants = [item for item in data.view["variants"] if item["template_id"] == template["id"]]
        main_variant = next(item for item in variants if item["variant_kind"] == "main")
        alternatives = [item for item in variants if item["variant_kind"] == "complete_alternate"]
        normal = run("normal:" + suffix, data.request(stage, name="normal"), lambda result: result["status"] == "plans_available" and main_variant["id"] in [plan["variant"]["id"] for plan in available(result)])
        if alternatives:
            alternative = alternatives[0]
            req = data.request(stage, name="complete-alternative")
            main_chars = {slot["character_id"] for team in main_variant["teams"].values() for slot in team}
            alt_chars = {slot["character_id"] for team in alternative["teams"].values() for slot in team}
            req["task"]["excluded_character_ids"] = sorted(main_chars - alt_chars)
            run("complete-alternative:" + suffix, req, lambda result: alternative["id"] in [plan["variant"]["id"] for plan in available(result)] and all(plan["variant"]["id"] in {v["id"] for v in variants} for plan in available(result)))
        else:
            cases.append({"name": "complete-alternative:" + suffix, "outcome": "not_exercised", "needed": "producer must export an approved complete alternate"})
        req = data.request(stage, name="no-match")
        req["task"]["public_goal"] = {"kind": "fixture:consumer-no-matching-goal"}
        run("no-match:" + suffix, req, lambda result: result["status"] == "no_reviewed_template" and not available(result) and bool(result["analysis"]["public_material"]["evidence_refs"]))
    stage = data.view["stages"][0]
    def unknown_fields(result):
        plans = available(result) + (result.get("analysis") or {}).get("pending_confirmation_candidates", [])
        conditions = [condition for plan in plans for condition in plan["condition_results"]]
        return bool(conditions) and all(condition["match_status"] == "unknown" and condition["observed"] is None for condition in conditions)
    run("missing-fields", data.request(stage, name="missing-fields", b_case="missing_fields"), unknown_fields)
    run("missing-unit-context", data.request(stage, name="missing-measurements", b_case="confirmed_field_without_measurement"), lambda result: unknown_fields(result) and any(condition["reason_code"] == "missing_unit" for plan in available(result) for condition in plan["condition_results"]))
    req = data.request(stage, name="unknown-ownership", b_case="unknown_ownership")
    first_character = next(iter(json.loads(req["account_snapshot"]["raw_json"])["ownership"]))
    req["task"]["fixed_character_ids"] = [first_character]
    run("unknown-ownership", req, lambda result: not available(result) and result["status"] == "confirmation_required")
    req = data.request(stage, name="cross-release")
    req["public_bundle"]["expected_release_id"] = data.release + "-other"
    run("cross-release", req, lambda result: result.get("error", {}).get("code") == "producer_release_mismatch")
    req = data.request(stage, name="tampered-transport")
    req["public_bundle"]["raw_json"] += " "  # Keep the expected hash unchanged; never repair it.
    run("tampered-transport", req, lambda result: result.get("error", {}).get("code") == "producer_digest_mismatch")
    req = data.request(stage, name="unknown-signing-key")
    req["distribution_trust"]["public_keys"] = {}
    run("unknown-signing-key", req, lambda result: result.get("error", {}).get("code") == "unknown_signing_key")
    req = data.request(stage, name="wrong-public-key")
    req["distribution_trust"]["public_keys"][data.locks["fixture_key_id"]] = "00" * 32
    run("wrong-public-key", req, lambda result: result.get("error", {}).get("code") == "invalid_signature")
    req = data.request(stage, name="withdrawn-evidence")
    req["latest_known_validity"]["withdrawn_public_refs"] = [{"id": data.view["evidence"][0]["id"], "revision": data.view["evidence"][0]["revision"]}]
    run("withdrawn-evidence", req, lambda result: not available(result) and (result.get("analysis") or {}).get("error", {}).get("code") == "withdrawn_public_object")
    requirements = [requirement for variant in data.view["variants"] for team in variant["teams"].values() for slot in team for requirement in slot.get("equipment_requirements", [])]
    # Coverage gaps are requirements, never relabelled as passing tests.
    if not requirements:
        for name in ("equipment-lock", "ambiguous-equipment"):
            cases.append({"name": name, "outcome": "not_exercised", "needed": "A must export a complete approved variant with explicit equipment type/slot requirements and public equipment entities"})
    else:
        cases.append({"name": "equipment-lock-and-ambiguity", "outcome": "not_exercised", "needed": "capture matching B equipment models and add nontrivial requirement replay before accepting this producer"})
    modes = sorted({item["scope"]["mode_id"] for item in data.view["stages"]})
    if len(modes) < 3:
        cases.append({"name": "three-mode-coverage", "outcome": "not_exercised", "needed": "three actual producer-generated synthetic mode samples", "actual_modes": modes})
    report = {
        "synthetic_only": True, "consumer_component_version": importlib.metadata.version("starhelp-planner"), "native_rule_version": starhelp_planner.PLANNER_VERSION,
        "consumer_source_commit": args.consumer_source_commit, "consumer_wheel_sha256": hashlib.sha256(args.wheel.read_bytes()).hexdigest(),
        "consumer_import_verified": True, "cryptography_version": cryptography.__version__,
        "a_producer_commit": data.locks["a_producer_commit"], "a_raw_sha256": data.locks["a_raw_sha256"], "release_id": data.release,
        "b_producer_commit": data.locks["b_snapshot_commit"], "cases": cases,
        "technical_interoperability_accepted": all(case["outcome"] == "passed" for case in cases),
        "production_content_or_mvp_accepted": False,
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"passed": sum(case["outcome"] == "passed" for case in cases), "failed": sum(case["outcome"] == "failed" for case in cases), "not_exercised": sum(case["outcome"] == "not_exercised" for case in cases), "technical_interoperability_accepted": report["technical_interoperability_accepted"]}))
    if any(case["outcome"] == "failed" for case in cases):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
