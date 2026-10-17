"""Replay fixed synthetic producer bytes through B's delivered bridge and worker.

This is supplemental desktop-host evidence. It does not change the fixed B
snapshot producer or the round-2 acceptance report.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID


B_HOST_COMMIT = "86fafdddb9183c42408d8c6e71d8ce5de65c4ff3"
C_WHEEL_SHA256 = "f7b6c5c221e2491c9399ed76656945175961ac94188b11ad2fe4d4160d0aa0ca"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def verify_candidate(root: Path, expected_manifest_sha256: str) -> dict:
    """Pin delivered binaries by their manifest, without asserting build provenance."""
    root = root.resolve()
    manifest = root / "candidate-manifest.sha256"
    if not re.fullmatch(r"[0-9a-f]{64}", expected_manifest_sha256) or digest(manifest) != expected_manifest_sha256:
        raise ValueError("candidate manifest differs from the caller's pinned digest")
    entries = {}
    for line in manifest.read_text(encoding="utf-8-sig").splitlines():
        match = re.fullmatch(r"([0-9a-f]{64}) \*(.+)", line)
        if not match:
            raise ValueError("invalid candidate manifest entry")
        relative = match[2].replace("\\", "/")
        path = (root / relative).resolve()
        if relative in entries or not path.is_relative_to(root) or not path.is_file():
            raise ValueError("candidate manifest path is invalid")
        if digest(path) != match[1]:
            raise ValueError("candidate file digest differs from its manifest")
        entries[relative] = match[1]
    actual = {
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path != manifest
    }
    if actual != set(entries):
        raise ValueError("candidate manifest does not match the delivered file set")
    worker = "planner-worker/StarHelpPlannerWorker.exe"
    if worker not in entries:
        raise ValueError("candidate has no planner worker")
    return {
        "manifest_sha256": digest(manifest),
        "verified_files": len(entries),
        "worker_sha256": entries[worker],
        "build_source_commit_attested": False,
        "publisher_trust_established": False,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--b-repository", required=True, type=Path)
    parser.add_argument("--b-source", required=True, type=Path)
    parser.add_argument("--dependency-root", required=True, type=Path)
    parser.add_argument("--capture-dir", required=True, type=Path)
    parser.add_argument("--b-cases", required=True, type=Path)
    parser.add_argument("--wheel", required=True, type=Path)
    parser.add_argument("--candidate", type=Path)
    parser.add_argument("--candidate-manifest-sha256")
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if bool(args.candidate) != bool(args.candidate_manifest_sha256):
        parser.error("candidate path and its pinned manifest digest must be supplied together")
    component = Path(__file__).resolve().parents[1]
    source, wheel = args.b_source.resolve(), args.wheel.resolve()
    if not source.is_relative_to(component) or not args.report.resolve().is_relative_to(component):
        raise SystemExit("source copy and report must stay inside C's package")
    if digest(wheel) != C_WHEEL_SHA256:
        raise SystemExit("C wheel is not the delivered 0.3.0 artifact")
    sys.path[:0] = [
        str(Path(__file__).resolve().parent), str(wheel),
        str(source / "src"), str(args.dependency_root.resolve()),
    ]
    from check_producer_source import check_source
    from interop_inputs import CapturedInputs, result_summary
    import starhelp_planner
    from starhelp_desktop.bundles import (
        BundleValidator, Ed25519Keyring, PublicBundleCache, PublicBundleSynchronizer,
    )
    from starhelp_desktop.lifecycle import ProfileLifecycle
    from starhelp_desktop.models import ProfileAuthorization
    from starhelp_desktop.planner import LocalPlannerProcess, PlannerUnavailable
    from starhelp_desktop.storage import EncryptedPrivateStore

    if not str(starhelp_planner.__file__).startswith(str(wheel)):
        raise SystemExit("C must load from the delivered wheel, not its source checkout")
    proof = check_source(args.b_repository, B_HOST_COMMIT, "packages/starhelp-desktop", source)
    vendor = source / "packaging/vendor" / wheel.name
    if vendor.read_bytes() != wheel.read_bytes():
        raise SystemExit("B's vendored C wheel differs from C's delivery")
    data = CapturedInputs(args.capture_dir, args.b_cases)
    stage = data.view["stages"][0]
    raw_snapshot = json.loads(data.b_raw)
    profile_id, generation = UUID(raw_snapshot["profile_id"]), 7
    candidate = verify_candidate(args.candidate, args.candidate_manifest_sha256) if args.candidate else None
    cases = []

    class RejectPersistence:
        calls = 0

        def protect(self, _data):
            self.calls += 1
            raise AssertionError("this replay must not save an account")

        def unprotect(self, _data):
            self.calls += 1
            raise AssertionError("this replay must not load an account")

    task_temp = component / ".tmp"
    task_temp.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="b-bridge-replay-", dir=task_temp) as directory:
        scratch = Path(directory).resolve()
        if not scratch.is_relative_to(task_temp.resolve()):
            raise SystemExit("unexpected replay scratch directory")
        os.environ.update({
            "PYTHONPATH": os.pathsep.join([str(source / "src"), str(args.dependency_root.resolve())]),
            "PYTHONDONTWRITEBYTECODE": "1", "LOCALAPPDATA": str(scratch / "local"),
            "TEMP": str(scratch), "TMP": str(scratch),
        })
        verifier = Ed25519Keyring({data.locks["fixture_key_id"]: bytes.fromhex(data.key_hex)})
        capabilities = frozenset({"starhelp.knowledge-distribution.v1", "starhelp.local-profile.v0.2"})
        validated = BundleValidator().validate(
            data.a_raw, supported_capabilities=capabilities, signature_verifier=verifier,
        )
        cache = PublicBundleCache(scratch / "public-cache")
        cache.activate(validated)
        cached = PublicBundleSynchronizer(
            cache, signature_verifier=verifier, supported_capabilities=capabilities,
        ).load_current()
        if cached is None or cached.payload_json != data.a_raw:
            raise SystemExit("B cache did not preserve the original signed public bytes")
        protector = RejectPersistence()
        store = EncryptedPrivateStore(scratch / "private", protector)
        lifecycle = ProfileLifecycle(store, scratch / "tasks")
        lifecycle.authorize(ProfileAuthorization(
            profile_id=profile_id, active=True, generation=generation,
            source_id="synthetic-fixture", scopes=frozenset({"analysis"}),
            confirmed_at=datetime(2026, 10, 16, tzinfo=UTC),
        ))
        commands = {"fixed-source-worker": (sys.executable, "-B", "-m", "starhelp_desktop.planner_worker")}
        if candidate:
            commands["delivered-windows-worker"] = (
                str(args.candidate.resolve() / "planner-worker/StarHelpPlannerWorker.exe"),
            )

        def run(transport, command, name, request, status, error=None, wrapper_change=None):
            snapshot = json.loads(request["account_snapshot"]["raw_json"])
            wrapper = {
                "contract_version": "0.1-draft", "schema_id": "AnalysisRequest",
                "schema_version": "0.1-draft", "request_id": request["request_id"],
                "authorization_generation": generation, "public_bundle": cached.payload(),
                "account_snapshot": {
                    "profile_id": str(profile_id), "snapshot_revision": snapshot["revision"],
                    "authorization_generation": generation, "authorization_state": "active",
                },
                "task": request["task"], "producer_request": request,
            }
            if wrapper_change:
                wrapper_change(wrapper)
            original = deepcopy(wrapper)
            bridge = LocalPlannerProcess(
                command=command, timeout_seconds=30,
                required_capabilities=frozenset({"starhelp.producers.v0.1", "starhelp.local-profile.v0.2"}),
            )
            summary = None
            bridge_error = None
            diagnostic = None
            try:
                result = bridge.analyze(
                    request=wrapper, profile_id=profile_id,
                    authorization_generation=generation, lifecycle=lifecycle,
                )
                analysis = result.result
                metadata = analysis["adapter_metadata"]
                summary = result_summary({**metadata, "analysis": analysis})
                passed = result.planner_version == "0.2.0" and analysis.get("component_version") == "0.3.0"
                passed &= analysis.get("status") == status
                if status == "plans_available":
                    passed &= bool(summary["available_variants"]) and bool(analysis.get("citations"))
                if name == "normal":
                    passed &= set(summary["available_variants"]) == {"fixture:variant:main", "fixture:variant:alternate"}
                if name == "complete-alternative":
                    passed &= summary["available_variants"] == ["fixture:variant:alternate"]
                if name == "no-match":
                    passed &= not summary["available_variants"] and bool(analysis.get("citations"))
                if name == "missing-fields":
                    conditions = [condition for plan in summary["conditions"] for condition in plan["results"]]
                    passed &= bool(conditions) and all(condition["match_status"] == "unknown" for condition in conditions)
                if error:
                    passed &= error in {summary["adapter_error"], summary["native_error"]}
                observation = "result"
            except PlannerUnavailable as exc:
                passed = status == "bridge_refused"
                observation = "bridge_refused"
                bridge_error = str(exc)
                if name == "withdrawn-evidence":
                    # Diagnose the rejected response separately. This cannot turn
                    # a failing end-to-end bridge case into a passing one.
                    completed = subprocess.run(
                        command, input=json.dumps(wrapper, ensure_ascii=False).encode("utf-8"),
                        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=30,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
                    )
                    envelope = json.loads(completed.stdout) if completed.returncode == 0 else {}
                    response = envelope.get("result", {})
                    diagnostic = {
                        "worker_exit_code": completed.returncode,
                        "worker_status": response.get("status"),
                        "native_error": (response.get("error") or {}).get("code"),
                        "request_id_matches": response.get("request_id") == wrapper["request_id"],
                        "snapshot_revision_present": "snapshot_revision" in response,
                        "authorization_generation_present": "authorization_generation" in response,
                        "available_plan_count": len(response.get("current_equipment_plans", [])) + len(response.get("rearrangement_plans", [])),
                    }
            unchanged = original == wrapper
            cases.append({
                "transport": transport, "name": name,
                "outcome": "passed" if passed and unchanged else "failed",
                "inputs_unchanged": unchanged, "observation": observation, "result": summary,
                "bridge_error": bridge_error, "rejected_worker_response_diagnostic": diagnostic,
            })

        for transport, command in commands.items():
            request = lambda name, **options: data.request(stage, name="b-bridge-" + name, **options)
            run(transport, command, "normal", request("normal"), "plans_available")
            alternate = request("alternate")
            alternate["task"]["fixed_character_ids"] = ["fixture:character:c"]
            run(transport, command, "complete-alternative", alternate, "plans_available")
            no_match = request("no-match")
            no_match["task"]["public_goal"] = {"kind": "fixture:consumer-no-matching-goal"}
            run(transport, command, "no-match", no_match, "no_reviewed_template")
            run(transport, command, "missing-fields", request("missing-fields", b_case="missing_fields"), "plans_available")
            withdrawn = request("withdrawn")
            withdrawn["latest_known_validity"]["withdrawn_public_refs"] = [
                {key: data.view["evidence"][0][key] for key in ("id", "revision")}
            ]
            run(transport, command, "withdrawn-evidence", withdrawn, "error", "withdrawn_public_object")
            tampered = request("tamper")
            tampered["public_bundle"]["raw_json"] += " "  # Retain the original expected hash.
            run(transport, command, "transport-tamper", tampered, "error", "producer_digest_mismatch")
            run(transport, command, "mismatched-request-id", request("id-mismatch"), "bridge_refused",
                wrapper_change=lambda wrapper: wrapper.update(request_id="fixture:different-request"))
            run(transport, command, "mismatched-snapshot-revision", request("revision-mismatch"), "bridge_refused",
                wrapper_change=lambda wrapper: wrapper["account_snapshot"].update(snapshot_revision=999))
            wrong_generation = request("generation-mismatch")
            wrong_generation["authorization_context"]["generation"] = generation + 1
            run(transport, command, "mismatched-authorization-generation", wrong_generation, "bridge_refused")
        if protector.calls or any(store.root.iterdir()):
            raise SystemExit("replay unexpectedly used account persistence")
    after = check_source(args.b_repository, B_HOST_COMMIT, "packages/starhelp-desktop", source)
    if proof != after:
        raise SystemExit("B's extracted source changed during replay")
    if candidate and verify_candidate(args.candidate, args.candidate_manifest_sha256) != candidate:
        raise SystemExit("B's delivered candidate changed during replay")
    report = {
        "synthetic_only": True, "b_host_commit": B_HOST_COMMIT,
        "b_host_source_proof": proof, "b_host_source_unchanged": True,
        "b_snapshot_producer_commit": data.locks["b_snapshot_commit"],
        "b_snapshot_raw_sha256": hashlib.sha256(data.b_raw).hexdigest(),
        "a_producer_commit": data.locks["a_producer_commit"],
        "a_delivery_artifact_commit": data.locks["official_delivery_artifact_commit"],
        "a_raw_sha256": data.locks["a_raw_sha256"],
        "c_wheel_sha256": C_WHEEL_SHA256, "c_component_version": "0.3.0",
        "c_native_rule_version": "0.2.0", "b_vendor_wheel_bytes_match": True,
        "b_cache_retains_original_bytes": True, "account_persistence_calls": 0,
        "candidate": candidate, "cases": cases,
        "full_round2_acceptance": False, "m0_or_production_acceptance": False,
        "remaining": ["three-mode samples", "nontrivial equipment lock/ambiguity samples",
                      "B must preserve validated correlation context for native error responses",
                      "agreed M0 semantics and real source/content approval", "production TaskPage request construction"],
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")
    failed = sum(case["outcome"] == "failed" for case in cases)
    print(json.dumps({"passed": len(cases) - failed, "failed": failed, "transports": len(commands), "source_unchanged": True}))
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
