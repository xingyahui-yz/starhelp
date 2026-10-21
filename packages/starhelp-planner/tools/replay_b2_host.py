"""Replay immutable B1 inputs through a separately fixed actual B2 host/worker.

Only synthetic captures are accepted. All scratch paths stay in C. A source
worker and an optional hash-pinned Windows worker are separate observations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import tempfile
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_producer_source import check_source
from replay_b_bridge import verify_candidate
from verify_b2_host import C_WHEEL_NAME, C_WHEEL_SHA256, verify_host


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--b-repository", required=True, type=Path)
    parser.add_argument("--b-source", required=True, type=Path)
    parser.add_argument("--b-host-commit", required=True)
    parser.add_argument("--capture", required=True, type=Path)
    parser.add_argument("--expected-report", required=True, type=Path)
    parser.add_argument("--dependency-root", required=True, type=Path)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--candidate-manifest-sha256")
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source, report = args.b_source.resolve(), args.report.resolve()
    if not source.is_relative_to(root) or not report.is_relative_to(root) or report.exists():
        raise SystemExit("use a fixed source copy and a new report inside C")
    if bool(args.candidate) != bool(args.candidate_manifest_sha256):
        raise SystemExit("candidate path and expected manifest hash must be supplied together")
    host = verify_host(args.b_repository, source, args.b_host_commit, args.capture.resolve(), args.dependency_root.resolve(), args.wheel.resolve())
    c_lock = json.loads((root / "artifacts/starhelp_planner-0.4.0.lock.json").read_bytes())
    expected_path = args.expected_report.resolve()
    if not expected_path.is_relative_to(root) or expected_path.name not in c_lock["reports"] or digest(expected_path) != c_lock["reports"][expected_path.name]["sha256"]:
        raise SystemExit("expected results must be one of the fixed installed C replay reports")
    expected = json.loads(expected_path.read_bytes())
    locks_raw = (args.capture / "producer-locks.json").read_bytes()
    locks = json.loads(locks_raw)
    if expected["capture_lock_raw_sha256"] != hashlib.sha256(locks_raw).hexdigest():
        raise SystemExit("installed C evidence and B1 capture set differ")
    expected_cases = {item["name"]: item for item in expected["cases"]}
    candidate = verify_candidate(args.candidate, args.candidate_manifest_sha256) if args.candidate else None
    sys.path[:0] = [str(source / "src"), str(args.dependency_root.resolve()), str(args.wheel.resolve())]
    from starhelp_desktop.bundles import BundleValidator, Ed25519Keyring
    from starhelp_desktop.lifecycle import ProfileLifecycle
    from starhelp_desktop.models import ProfileAuthorization
    from starhelp_desktop.profiles import _snapshot_from_dict
    from starhelp_desktop.producer_request import build_producer_analysis_request
    from starhelp_desktop.planner import LocalPlannerProcess, PlannerUnavailable, PlannerCancelled
    from starhelp_desktop.analysis import ProducerAnalysisRunner
    from starhelp_desktop.reports import ReportLifecycle
    from starhelp_desktop.storage import EncryptedPrivateStore
    import starhelp_planner

    if not str(starhelp_planner.__file__).replace("\\", "/").startswith(str(args.wheel.resolve()).replace("\\", "/") + "/"):
        raise SystemExit("parent expected-result comparison must load the fixed C wheel")

    def read(name):
        if Path(name).name != name:
            raise ValueError("capture filename must stay in its directory")
        path = args.capture / name
        if digest(path) != locks["files"][name]:
            raise ValueError("captured raw input changed")
        return path.read_bytes()

    for name in locks["files"]:
        read(name)
    launcher = "import sys;from pathlib import Path;sys.path[:0]=[str(Path(sys.argv[1])/'src'),sys.argv[2]];from starhelp_desktop.planner_worker import main;raise SystemExit(main())"
    commands = {"fixed-B2-source-worker": (sys.executable, "-I", "-B", "-c", launcher, str(source), str(args.dependency_root.resolve()))}
    if candidate:
        commands["hash-pinned-Windows-worker"] = (str(args.candidate.resolve() / "planner-worker/StarHelpPlannerWorker.exe"),)
    checks, cases, rebuilds = [], [], []

    def check(name, passed, detail):
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    class RejectPersistence:
        calls = 0

        def protect(self, _data):
            self.calls += 1
            raise AssertionError("synthetic replay must not save an account")

        def unprotect(self, _data):
            self.calls += 1
            raise AssertionError("synthetic replay must not read an account")

    class RevokeAtCompletedWorker(ProfileLifecycle):
        """Test interposer: actual revoke at B's post-worker authorization check."""

        require_calls = 0

        def require_active(self, profile_id, generation=None):
            self.require_calls += 1
            if self.require_calls == 2:
                self.revoke(profile_id)
            return super().require_active(profile_id, generation)

    scratch_root = root / ".tmp"
    scratch_root.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="B2-worker-replay-", dir=scratch_root) as directory:
        scratch = Path(directory).resolve()
        os.environ.update({"TEMP": str(scratch), "TMP": str(scratch), "LOCALAPPDATA": str(scratch / "local"), "PYTHONDONTWRITEBYTECODE": "1"})
        protector = RejectPersistence()
        store = EncryptedPrivateStore(scratch / "private", protector)
        lifecycle = ProfileLifecycle(store, scratch / "tasks")

        def authorize(gate, wrapper):
            profile_id = UUID(wrapper["account_snapshot"]["profile_id"])
            generation = wrapper["authorization_generation"]
            if not gate.is_active(profile_id, generation):
                gate.authorize(ProfileAuthorization(profile_id=profile_id, active=True, generation=generation, source_id="fixture:B2-replay", scopes=frozenset({"analysis"}), confirmed_at=datetime(2026, 10, 21, tzinfo=UTC)))
            return profile_id, generation

        def run(transport, command, name, wrapper, *, expected_case=None, error=None, refused=False, gate=None):
            gate = gate or lifecycle
            profile_id, generation = authorize(gate, wrapper)
            before = deepcopy(wrapper)
            bridge = LocalPlannerProcess(command=command, timeout_seconds=30, required_capabilities=frozenset({"starhelp.producers.v0.1", "starhelp.local-profile.v0.2"}))
            observation = {"status": "not_executed"}
            passed = False
            try:
                execution = ProducerAnalysisRunner(bridge, ReportLifecycle(store, gate)).run(request=wrapper, profile_id=profile_id, authorization_generation=generation, lifecycle=gate)
                actual = execution.planner_result.result
                metadata = actual["adapter_metadata"]
                actual_error = (actual.get("error") or metadata.get("error") or {}).get("code")
                correlated = actual.get("request_id") == wrapper["request_id"] and actual.get("snapshot_revision") == wrapper["account_snapshot"]["snapshot_revision"] and actual.get("authorization_generation") == generation
                passed = not refused and correlated and actual.get("component_version") == "0.4.0" and execution.planner_result.planner_version == "0.2.0"
                if error:
                    passed &= actual.get("status") == "error" and actual_error == error and execution.temporary_report is None
                elif expected_case:
                    plans = [*actual.get("current_equipment_plans", []), *actual.get("rearrangement_plans", [])]
                    actual_allocations = [{"variant_id": plan["variant"]["id"], "plan_kind": plan["plan_kind"], "equipment": plan.get("equipment")} for plan in plans]
                    passed &= actual.get("status") == expected_case["status"] and actual_allocations == expected_case["available"] and actual.get("pending_confirmation_candidates", []) == expected_case["pending"]
                    passed &= (execution.temporary_report is not None) == (actual.get("status") == "plans_available")
                    if execution.temporary_report:
                        passed &= execution.temporary_report.public_release_id == locks["a_release_id"] and execution.temporary_report.snapshot_revision == wrapper["account_snapshot"]["snapshot_revision"] and execution.temporary_report.authorization_generation == generation
                        passed &= bool(execution.temporary_report.public_refs)
                direct = json.loads(json.dumps(starhelp_planner.analyze_producers(wrapper["producer_request"]), allow_nan=False))
                native = direct.get("analysis") or {}
                if not error:
                    passed &= all(actual.get(key, []) == native.get(key, []) for key in ("current_equipment_plans", "rearrangement_plans", "pending_confirmation_candidates", "rejected_variants", "citations"))
                observation = {"status": actual.get("status"), "error_code": actual_error, "correlation_tuple_matches": correlated, "temporary_report_created": execution.temporary_report is not None, "available_variant_ids": [plan["variant"]["id"] for plan in [*actual.get("current_equipment_plans", []), *actual.get("rearrangement_plans", [])]], "native_result_matches_fixed_installed_C": None if error else bool(passed), "component_version": actual.get("component_version")}
            except PlannerUnavailable as exc:
                passed = refused
                observation = {"status": "bridge_refused", "exception": type(exc).__name__, "message": str(exc)}
                if isinstance(gate, RevokeAtCompletedWorker):
                    passed &= isinstance(exc, PlannerCancelled) and gate.require_calls == 2 and not gate.is_active(profile_id, generation)
                    observation.update(test_interposer="actual B revoke at post-worker require_active checkpoint", require_active_calls=gate.require_calls, completed_worker_result_rejected=passed)
            unchanged = wrapper == before
            check(transport + "/" + name, passed and unchanged, "actual B bridge/worker, status/allocation/correlation/staging versus fixed installed C evidence")
            cases.append({"transport": transport, "name": name, "passed": bool(passed and unchanged), "input_unchanged": unchanged, "observation": observation})

        wrappers = {}
        for name, capture in locks["cases"].items():
            wrapper = json.loads(read(capture["wrapper"]))
            request = wrapper["producer_request"]
            keyring = {key: bytes.fromhex(value) for key, value in request["distribution_trust"]["public_keys"].items()}
            validated = BundleValidator().validate(request["public_bundle"]["raw_json"].encode("utf-8"), supported_capabilities=frozenset({"starhelp.knowledge-distribution.v1", "starhelp.local-profile.v0.2"}), signature_verifier=Ed25519Keyring(keyring))
            rebuilt = build_producer_analysis_request(validated_bundle=validated, task=deepcopy(request["task"]), snapshot=_snapshot_from_dict(json.loads(read(capture["snapshot"]))), authorization_generation=wrapper["authorization_generation"], distribution_trust_purpose=request["distribution_trust"]["purpose"], distribution_public_keys=keyring, bundle_producer_commit=request["public_bundle"]["producer_commit"], bundle_format_profile=request["public_bundle"]["format_profile"], snapshot_producer_commit=request["account_snapshot"]["producer_commit"], snapshot_format_profile=request["account_snapshot"]["format_profile"], evaluation_time=datetime.fromisoformat(request["evaluation_time"].replace("Z", "+00:00")), request_id=request["request_id"])
            equal = rebuilt == wrapper
            check(name + "/actual_B2_builder_bytes", equal and rebuilt["producer_request"]["account_snapshot"]["raw_json"].encode("utf-8") == read(capture["snapshot"]), "actual B2 builder emits the exact B1 snapshot bytes under the independently verified unchanged seam")
            rebuilds.append({"name": name, "wrapper_equal_to_B1_capture": equal, "snapshot_sha256": rebuilt["producer_request"]["account_snapshot"]["sha256"]})
            if not equal:
                raise SystemExit("B2 builder changed the fixed B1 request semantics/bytes")
            wrappers[name] = rebuilt
            for transport, command in commands.items():
                run(transport, command, name, rebuilt, expected_case=expected_cases[name])
        base = wrappers["stage-0-normal"]
        public = base["public_bundle"]
        view = public["objects"]["planner-view:" + locks["a_release_id"]]["bundle"]
        no_template = {item["name"]: item for item in expected["negative_cases"] if item["expected_code"] == "no_reviewed_template"}
        normal_wrappers = {wrapper["task"]["scope"]["stage_id"]: wrapper for name, wrapper in wrappers.items() if name.endswith("-normal")}
        for transport, command in commands.items():
            for stage_id, normal_wrapper in normal_wrappers.items():
                expected_name = "no-reviewed-template/" + stage_id
                if expected_name not in no_template or not no_template[expected_name]["passed"]:
                    raise SystemExit("no-template protocol case lacks fixed installed C evidence")
                unmatched = deepcopy(normal_wrapper)
                task = {**unmatched["task"], "public_goal": {"kind": "fixture:consumer-no-template"}}
                unmatched["task"] = deepcopy(task)
                unmatched["producer_request"]["task"] = deepcopy(task)
                run(transport, command, expected_name, unmatched, expected_case={"status": "no_reviewed_template", "available": [], "pending": []})
                cases[-1]["origin"] = "C-constructed protocol negative: outer/inner task goal changed together; original A/B raw bytes retained. B1/B2 builder separately refuses the undeclared goal before worker submission."
            withdrawn = deepcopy(base)
            withdrawn["producer_request"]["latest_known_validity"]["withdrawn_public_refs"] = [{"id": view["evidence"][0]["id"], "revision": view["evidence"][0]["revision"]}]
            run(transport, command, "withdrawn-required-evidence", withdrawn, error="withdrawn_public_object")
            tampered = deepcopy(base)
            tampered["producer_request"]["public_bundle"]["raw_json"] += " "
            run(transport, command, "raw-digest-tamper", tampered, error="producer_digest_mismatch")
            unknown_key = deepcopy(base)
            unknown_key["producer_request"]["distribution_trust"]["public_keys"] = {}
            run(transport, command, "unknown-signing-key", unknown_key, error="unknown_signing_key")
            bad_id = deepcopy(base)
            bad_id["request_id"] += ":wrong-outer"
            run(transport, command, "mismatched-request-id", bad_id, refused=True)
            bad_revision = deepcopy(base)
            bad_revision["account_snapshot"]["snapshot_revision"] += 1
            run(transport, command, "mismatched-snapshot-revision", bad_revision, refused=True)
            bad_generation = deepcopy(base)
            bad_generation["producer_request"]["authorization_context"]["generation"] += 1
            run(transport, command, "mismatched-authorization-generation", bad_generation, refused=True)
            late_gate = RevokeAtCompletedWorker(store, scratch / ("late-" + transport))
            run(transport, command, "post-worker-revocation-rejects-result", deepcopy(base), refused=True, gate=late_gate)
        if protector.calls or any(store.root.iterdir()):
            raise SystemExit("replay unexpectedly used private persistence")
    if check_source(args.b_repository, args.b_host_commit, "packages/starhelp-desktop", source) != host["b_host_source_proof"]:
        raise SystemExit("B2 source changed during worker replay")
    if candidate and verify_candidate(args.candidate, args.candidate_manifest_sha256) != candidate:
        raise SystemExit("candidate bytes changed during worker replay")
    result = {"synthetic_only": True, "b_host_commit": args.b_host_commit, "source_load_proof": host, "capture_lock_raw_sha256": hashlib.sha256(locks_raw).hexdigest(), "C_wheel_file": C_WHEEL_NAME, "C_wheel_sha256": C_WHEEL_SHA256, "expected_installed_report": {"file": expected_path.name, "sha256": digest(expected_path)}, "candidate": candidate, "builder_rebuilds": rebuilds, "cases": cases, "checks": checks, "account_persistence_calls": 0, "worker_request_replay_executed": True, "summary": {"checks_passed": sum(item["passed"] for item in checks), "checks_failed": sum(not item["passed"] for item in checks), "worker_cases": len(cases), "transports": list(commands)}, "not_exercised": ["production source/content/trust acceptance", "complete inventory/material positive calculations", "final-loadout panel positive calculations"], "candidate_build_provenance_attested": False, "full_M0_acceptance": False}
    report.parent.mkdir(parents=True, exist_ok=True)
    with report.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2, sort_keys=True)
        stream.write("\n")
    print(json.dumps(result["summary"]))
    if result["summary"]["checks_failed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
