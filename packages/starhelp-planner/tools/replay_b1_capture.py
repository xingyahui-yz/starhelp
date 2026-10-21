"""Replay fixed B1 capture bytes; distinguish source checks from installed wheels."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import sys
import zipfile
from copy import deepcopy
from pathlib import Path


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--dependency-root", required=True, type=Path)
    parser.add_argument("--report", required=True, type=Path)
    runtime = parser.add_mutually_exclusive_group(required=True)
    runtime.add_argument("--source-only", action="store_true")
    runtime.add_argument("--installed-root", type=Path)
    parser.add_argument("--wheel", type=Path)
    parser.add_argument("--wheel-sha256")
    parser.add_argument("--source-commit")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    report = args.report.resolve()
    if not report.is_relative_to(root) or report.exists():
        raise SystemExit("report must be a new file inside C's component")
    if args.source_only and (args.wheel or args.wheel_sha256 or args.source_commit):
        raise SystemExit("source-only development reports cannot assert an installed wheel or immutable source commit")
    if args.installed_root and not all((args.wheel, args.wheel_sha256, args.source_commit)):
        raise SystemExit("installed replay requires wheel, expected raw hash and actual build source commit")
    installed = (root / "src") if args.source_only else args.installed_root.resolve()
    sys.path[:0] = [str(installed), str(args.dependency_root.resolve())]
    import starhelp_planner
    from starhelp_planner import analyze_producers, prepare_producer_request
    from starhelp_planner.adapters.b_snapshot import B_INTEROP_COMMIT, B_INTEROP_PROFILE

    module_path = Path(starhelp_planner.__file__).resolve()
    if not module_path.is_relative_to(installed):
        raise SystemExit("planner was not loaded from the selected source/install root")
    wheel_proof = None
    if args.installed_root:
        raw = args.wheel.read_bytes()
        if sha(raw) != args.wheel_sha256:
            raise SystemExit("wheel differs from the explicit expected raw hash")
        verified = {}
        with zipfile.ZipFile(args.wheel) as archive:
            for name in archive.namelist():
                if name.startswith("starhelp_planner/") and not name.endswith("/"):
                    expected = archive.read(name)
                    if (installed / name).read_bytes() != expected:
                        raise SystemExit("installed planner module differs from the fixed wheel")
                    verified[name] = sha(expected)
        if importlib.metadata.version("starhelp-planner") != starhelp_planner.COMPONENT_VERSION:
            raise SystemExit("installed metadata and component version differ")
        wheel_proof = {"wheel_file": args.wheel.name, "raw_sha256": sha(raw), "build_source_commit": args.source_commit, "installed_package_files": verified, "installed_metadata_version": importlib.metadata.version("starhelp-planner")}
    capture = args.capture.resolve()
    locks_raw = (capture / "producer-locks.json").read_bytes()
    locks = json.loads(locks_raw)
    if locks.get("synthetic_only") is not True or locks.get("producer_commit") != B_INTEROP_COMMIT or locks.get("format_profile") != B_INTEROP_PROFILE or locks.get("source_verified_before_and_after") is not True:
        raise SystemExit("capture is not the actual fixed B1 synthetic delivery")

    def read(name):
        if Path(name).name != name:
            raise ValueError("capture filename escapes its directory")
        raw = (capture / name).read_bytes()
        if sha(raw) != locks["files"][name]:
            raise ValueError("captured raw input changed")
        return raw

    for name in locks["files"]:
        read(name)
    cases, checks, negative_cases = [], [], []
    observed = {}

    def check(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    for name, case in locks["cases"].items():
        wrapper = json.loads(read(case["wrapper"]))
        request = wrapper["producer_request"]
        snapshot = read(case["snapshot"])
        check(name + "/raw_snapshot", request["account_snapshot"]["raw_json"].encode("utf-8") == snapshot and request["account_snapshot"]["sha256"] == sha(snapshot), "actual builder bytes, independent serializer bytes and raw file hash must agree")
        check(name + "/producer_tuple", request["account_snapshot"]["producer_commit"] == B_INTEROP_COMMIT and request["account_snapshot"]["format_profile"] == B_INTEROP_PROFILE and request["public_bundle"]["producer_commit"] == locks["a_producer_commit"] and request["public_bundle"]["sha256"] == locks["a_raw_sha256"], "actual A and B1 tuple; metadata/host identities are separate")
        prepared = prepare_producer_request(request)
        before = deepcopy(request)
        result = analyze_producers(request)
        check(name + "/input_unchanged", request == before, "analysis does not mutate original raw strings or caller inputs")
        analysis = result.get("analysis") or {}
        public = json.loads(request["public_bundle"]["raw_json"])
        view = public["objects"]["planner-view:" + locks["a_release_id"]]["bundle"]
        stage = next(item for item in view["stages"] if item["stage_id"] == case["stage_id"])
        template = next(item for item in view["templates"] if stage["stage_id"] in item["stage_ids"])
        declared = {item["id"]: item for item in view["variants"] if item["template_id"] == template["id"]}
        main_id = next(identifier for identifier, item in declared.items() if item["variant_kind"] == "main")
        alternate_ids = {identifier for identifier, item in declared.items() if item["variant_kind"] == "complete_alternate"}
        plans = [*analysis.get("current_equipment_plans", []), *analysis.get("rearrangement_plans", [])]
        pending = analysis.get("pending_confirmation_candidates", [])
        allocations = [{"variant_id": plan["variant"]["id"], "plan_kind": plan["plan_kind"], "equipment": plan.get("equipment")} for plan in plans]
        actions = [action for plan in plans for action in (plan.get("equipment") or {}).get("actions", [])]
        plan_ids = {plan["variant"]["id"] for plan in plans}
        pending_ids = {plan["variant"]["id"] for plan in pending}
        ownership = json.loads(snapshot)["ownership"]
        observed[name] = {"request": request, "status": result["status"], "actions": actions, "pending": pending}
        check(name + "/adapter", prepared["status"] == "ready" and result.get("error") is None, "preparation success is distinct from the native domain result")
        locked = set(request["task"].get("locked_local_instance_ids", []))
        check(name + "/lock_actions", not any(action["local_instance_id"] in locked for action in actions), "no available plan moves a locked instance")
        for allocation in allocations:
            ids = [item["local_instance_id"] for item in (allocation["equipment"] or {}).get("assignments", [])]
            check(name + "/unique_instances/" + allocation["variant_id"], len(ids) == len(set(ids)), "exclusive allocation uses each UUID at most once in one complete variant")
        for plan in plans:
            identifier = plan["variant"]["id"]
            expected_team = {(partition, seat["slot_id"], seat["character_id"]) for partition, team in declared.get(identifier, {}).get("teams", {}).items() for seat in team}
            actual_team = {(seat["partition_id"], seat["slot_id"], seat["character_id"]) for seat in plan["team"]}
            check(name + "/complete_reviewed_variant/" + identifier, identifier in declared and actual_team == expected_team and len(plan["team"]) == len(expected_team), "all partitions and slots come from one exact published complete variant")
        if name.endswith(("normal", "missing_fields", "confirmed_field_without_measurement", "conflicting_condition_field")):
            check(name + "/expected_plans", result["status"] == "plans_available" and main_id in plan_ids and alternate_ids <= plan_ids, "the fixed fixtures have no hard measurement requirement; both complete variants must remain available")
        if name.endswith("complete_alternate"):
            check(name + "/expected_alternate", result["status"] == "plans_available" and bool(plan_ids & alternate_ids) and main_id not in plan_ids and plan_ids <= alternate_ids, "the main-only character is excluded and only an independently approved full alternate is returned")
        if name.endswith("main_current_equipment"):
            current = [plan for plan in analysis.get("current_equipment_plans", []) if plan["variant"]["id"] == main_id]
            check(name + "/current_main_without_moves", len(current) == 1 and not current[0]["equipment"]["actions"], "the main variant's already-equipped assignment is selected with zero moves")
        if name.endswith("not_owned"):
            feasible_rosters = {identifier for identifier, item in declared.items() if all(ownership.get(seat["character_id"]) != "not_owned" for team in item["teams"].values() for seat in team)}
            expected_status = "plans_available" if feasible_rosters else "no_feasible_variant"
            check(name + "/expected_not_owned", result["status"] == expected_status and main_id not in plan_ids and plan_ids <= feasible_rosters and bool(feasible_rosters) == bool(plan_ids), "confirmed non-ownership excludes every affected complete roster")
        if name.endswith("unknown_ownership"):
            known_rosters = {identifier for identifier, item in declared.items() if all(ownership.get(seat["character_id"]) == "owned" for team in item["teams"].values() for seat in team)}
            expected_status = "plans_available" if known_rosters else "confirmation_required"
            check(name + "/expected_unknown_ownership", result["status"] == expected_status and main_id in pending_ids and main_id not in plan_ids and plan_ids <= known_rosters, "unknown ownership is pending, while independent confirmed rosters may remain available")
        if name.endswith(("confirmed_field_without_measurement", "conflicting_condition_field")):
            conditions = [condition for plan in [*plans, *pending] for condition in plan["condition_results"]]
            reason = "conflicting_field" if name.endswith("conflicting_condition_field") else "missing_unit"
            check(name + "/unknown_measurement", any(condition["match_status"] == "unknown" and condition["reason_code"] == reason for condition in conditions), "actual B1 FieldFact lacks unit/context or contains a conflict; no supplied numeric value is declared satisfied")
        if name.endswith("player_confirmed_move"):
            check(name + "/actual_move", bool(actions), "must produce at least one real cross-character move")
        if name.endswith(("locked_move", "ambiguous_move", "source_confirmed_move")):
            check(name + "/no_cross_character_move", not actions, "lock or unreliable identity must prevent the required move")
            check(name + "/pending_partial_inventory", bool(pending), "partial inventory must not be promoted into a proof of global infeasibility")
        if name.endswith("same_type_distinct_instance"):
            check(name + "/spare_instance_used", bool(actions) and all(action["local_instance_id"] not in locked for action in actions), "a distinct unlocked UUID must be allocated")
        normal_native = prepared.get("native_request", {})
        check(name + "/coverage", normal_native.get("account_snapshot", {}).get("coverage") == {"roster": "partial", "inventory": "partial", "materials": "unknown"}, "B has no complete inventory/material claims")
        cases.append({"name": name, "mode_id": case["mode_id"], "stage_id": case["stage_id"], "actual_gate": "C native analysis" if result.get("analysis") is not None else "C producer adapter", "status": result["status"], "adapter_error": (result.get("error") or {}).get("code"), "native_error": (analysis.get("error") or {}).get("code"), "available": allocations, "pending": pending, "condition_results": [{"variant_id": plan["variant"]["id"], "conditions": plan.get("condition_results")} for plan in plans], "rejected_variants": analysis.get("rejected_variants", []), "diagnostics": result.get("compatibility", {}).get("diagnostics", [])})
    for name, item in observed.items():
        if name.endswith("locked_move"):
            moving = observed[name.removesuffix("locked_move") + "player_confirmed_move"]
            check(name + "/lock_changes_observed_allocation", bool(moving["actions"]) and not item["actions"] and item["status"] == "confirmation_required" and item["request"]["account_snapshot"] == moving["request"]["account_snapshot"], "the same snapshot moves before the lock; the lock removes all available moves and leaves partial-inventory pending candidates")

    def negative(name, request, *, code, gate, origin="consumer task/trust change; producer raw bytes unchanged"):
        original = deepcopy(request)
        result = analyze_producers(request)
        analysis = result.get("analysis") or {}
        actual_code = (result.get("error") or analysis.get("error") or {}).get("code")
        actual_gate = "C native analysis" if result.get("analysis") is not None else "C producer adapter"
        passed = actual_code == code and actual_gate == gate and request == original
        if code == "no_reviewed_template":
            passed = result["status"] == code and actual_gate == gate and not analysis.get("current_equipment_plans") and not analysis.get("rearrangement_plans") and request == original
        check(name, passed, "expected gate/code: " + gate + "/" + code)
        negative_cases.append({"name": name, "origin": origin, "actual_gate": actual_gate, "actual_code": actual_code, "status": result["status"], "expected_code": code, "passed": passed, "public_raw_sha256": sha(request["public_bundle"]["raw_json"].encode("utf-8")), "declared_public_transport_sha256": request["public_bundle"]["sha256"], "base_public_raw_sha256": locks["a_raw_sha256"]})

    base_request = next(iter(observed.values()))["request"]
    stage_requests = {}
    for item in observed.values():
        stage_requests.setdefault(item["request"]["task"]["scope"]["stage_id"], item["request"])
    for stage_id, base_request in stage_requests.items():
        request = deepcopy(base_request)
        request["task"]["public_goal"] = {"kind": "fixture:consumer-no-template"}
        negative("no-reviewed-template/" + stage_id, request, code="no_reviewed_template", gate="C native analysis", origin="C consumer task negative; B1 builder separately rejects this undeclared goal before C")
    base_request = next(iter(observed.values()))["request"]
    request = deepcopy(base_request)
    request["task"]["scope"]["extra"] = "unsupported"
    negative("task-extra-scope-key", request, code="invalid_producer_payload", gate="C producer adapter")
    request = deepcopy(base_request)
    request["task"]["scope"]["stage_revision"] = True
    negative("task-boolean-scope-revision", request, code="invalid_producer_payload", gate="C producer adapter")
    request = deepcopy(base_request)
    request["public_bundle"]["raw_json"] += " "
    negative("tampered-original-transport", request, code="producer_digest_mismatch", gate="C producer adapter", origin="negative transport bytes changed; original expected hash and all captured files unchanged; no deeper gate claimed")
    request = deepcopy(base_request)
    request["distribution_trust"]["public_keys"] = {}
    negative("unknown-signing-key", request, code="unknown_signing_key", gate="C producer adapter")
    request = deepcopy(base_request)
    request["distribution_trust"]["public_keys"] = {key: "00" * 32 for key in request["distribution_trust"]["public_keys"]}
    negative("wrong-signing-key", request, code="invalid_signature", gate="C producer adapter")
    request = deepcopy(base_request)
    request["public_bundle"]["expected_release_id"] = "fixture:wrong-release"
    negative("requested-release-mismatch", request, code="producer_release_mismatch", gate="C producer adapter")
    request = deepcopy(base_request)
    public = json.loads(request["public_bundle"]["raw_json"])
    view = public["objects"]["planner-view:" + locks["a_release_id"]]["bundle"]
    request["latest_known_validity"]["withdrawn_public_refs"] = [{"id": view["evidence"][0]["id"], "revision": view["evidence"][0]["revision"]}]
    negative("withdrawn-required-evidence", request, code="withdrawn_public_object", gate="C native analysis")
    request = deepcopy(base_request)
    public = json.loads(request["public_bundle"]["raw_json"])
    del public["objects"]["native-release:" + locks["a_release_id"]]
    negative_raw = json.dumps(public, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    # A separate, explicitly constructed negative transport input. Keep the
    # original capture and signed manifest/member hashes unchanged. This raw
    # digest describes the negative input; it is not an A artifact repair.
    request["public_bundle"].update(raw_json=negative_raw.decode("utf-8"), sha256=sha(negative_raw))
    negative("missing-signed-native-object", request, code="producer_dependency_missing", gate="C producer adapter", origin="C-constructed negative transport, not A output: omitted object with untouched signed manifest/member hashes; fresh negative-input transport digest; original artifact bytes/hash retained")
    source_hashes = {path.relative_to(root).as_posix(): sha(path.read_bytes()) for path in sorted((installed / "starhelp_planner").rglob("*.py"))} if args.source_only else None
    not_exercised = ["B2 host/worker integration", "complete inventory/material positive calculations", "final-loadout panel positive calculations"]
    if locks["a_producer_commit"] != "dcb1e3ee220b85229bedc6c79d72ebe495825f37":
        not_exercised.append("new A S3 positive acceptance in this older-A report")
    elif not any(item.get("conditions") for item in view["variants"]):
        not_exercised.append("statistical conditions absent from this S3 A release; separate actual B1/old-A measurement replay required")
    result = {"synthetic_only": True, "runtime_kind": "source_only_development" if args.source_only else "isolated_installed_wheel", "component_version": starhelp_planner.COMPONENT_VERSION, "native_rule_version": starhelp_planner.PLANNER_VERSION, "source_file_sha256": source_hashes, "wheel_proof": wheel_proof, "capture_lock_raw_sha256": sha(locks_raw), "b_serializer_commit": B_INTEROP_COMMIT, "b_serializer_profile": B_INTEROP_PROFILE, "b_host_commit": None, "a_producer_commit": locks["a_producer_commit"], "a_release_id": locks["a_release_id"], "a_raw_sha256": locks["a_raw_sha256"], "cases": cases, "negative_cases": negative_cases, "checks": checks, "summary": {"passed": sum(item["passed"] for item in checks), "failed": sum(not item["passed"] for item in checks), "modes_observed": sorted({case["mode_id"] for case in cases}), "builder_rejections": len(locks["builder_rejections"])}, "builder_boundary_results": locks["builder_rejections"], "not_exercised": not_exercised, "full_three_party_acceptance": False, "M0_complete": False}
    report.parent.mkdir(parents=True, exist_ok=True)
    report.write_text(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps(result["summary"]))
    if result["summary"]["failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
