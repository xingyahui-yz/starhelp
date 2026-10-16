"""Load immutable synthetic producer artifacts for the external replay tool."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from pathlib import Path


class CapturedInputs:
    def __init__(self, capture: Path, b_cases: Path):
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        from starhelp_planner.adapters.common import B_COMMIT

        self.capture, self.b_cases = capture.resolve(), b_cases.resolve()
        self.locks = json.loads((self.capture / "consumer-capture-locks.json").read_bytes())
        if self.locks.get("synthetic_only") is not True or self.locks.get("b_snapshot_commit") != B_COMMIT:
            raise ValueError("this replay accepts only the fixed synthetic capture")
        self.case_locks = json.loads((self.b_cases / "producer-locks.json").read_bytes())
        if self.case_locks.get("producer_commit") != B_COMMIT:
            raise ValueError("B case producer commit is not pinned")
        self.a_raw = self.read(self.capture, self.locks["a_artifact"], self.locks["a_raw_sha256"])
        self.b_raw = self.read(self.capture, self.locks["b_snapshot"], self.locks["files"][self.locks["b_snapshot"]])
        if self.case_locks.get("base_sha256") != hashlib.sha256(self.b_raw).hexdigest():
            raise ValueError("B cases were not serialized from this capture's model base")
        self.public = json.loads(self.a_raw)
        self.release = self.locks["release_id"]
        self.view = self.public["objects"][f"planner-view:{self.release}"]["bundle"]
        key_bytes = self.read(self.capture, self.locks["fixture_public_key"], self.locks["files"][self.locks["fixture_public_key"]])
        key = serialization.load_pem_public_key(key_bytes)
        if not isinstance(key, Ed25519PublicKey) or self.locks["fixture_key_id"] != "starhelp-fixture-ed25519-v1":
            raise ValueError("separate pinned fixture Ed25519 key is required")
        self.key_hex = key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw).hex()

    @staticmethod
    def read(root: Path, filename: str, expected: str) -> bytes:
        if Path(filename).name != filename:
            raise ValueError("capture filenames must stay inside their directory")
        raw = (root / filename).read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError("captured producer bytes changed")
        return raw

    def request(self, stage: dict, *, name: str, b_case: str | None = None) -> dict:
        from starhelp_planner import PRODUCER_ADAPTER_PROFILE
        from starhelp_planner.adapters.b_snapshot import B_PROFILE
        from starhelp_planner.adapters.common import B_COMMIT
        raw = self.b_raw
        if b_case:
            entry = self.case_locks["cases"][b_case]
            raw = self.read(self.b_cases, entry["file"], entry["sha256"])
        snapshot = json.loads(raw)
        template = next(item for item in self.view["templates"] if stage["stage_id"] in item["stage_ids"])
        return {
            "schema_id": "ProducerAnalysisRequest", "schema_version": "0.1", "adapter_profile": PRODUCER_ADAPTER_PROFILE,
            "request_id": f"fixture:replay:{name}",
            "public_bundle": {"producer": "starhelp_knowledge", "producer_commit": self.locks["a_producer_commit"], "format_profile": self.locks["distribution_profile"], "expected_release_id": self.release, "raw_json": self.a_raw.decode("utf-8"), "sha256": self.locks["a_raw_sha256"]},
            "account_snapshot": {"producer": "starhelp_desktop", "producer_commit": B_COMMIT, "format_profile": B_PROFILE, "raw_json": raw.decode("utf-8"), "sha256": hashlib.sha256(raw).hexdigest()},
            "authorization_context": {"profile_id": snapshot["profile_id"], "active": True, "generation": 7},
            "distribution_trust": {"purpose": "synthetic-test", "public_keys": {self.locks["fixture_key_id"]: self.key_hex}},
            "task": {"scope": deepcopy(stage["scope"]), "public_goal": deepcopy(template["public_goals"][0]), "fixed_character_ids": [], "excluded_character_ids": [], "locked_local_instance_ids": [], "allow_rearrangement": True},
            "evaluation_time": "2026-10-16T00:10:00Z",
            "latest_known_validity": {"withdrawn_public_refs": [], "checked_at": "2026-10-16T00:10:00Z", "online_confirmation_available": False},
        }


def result_summary(result: dict) -> dict:
    analysis = result.get("analysis") or {}
    plans = [*analysis.get("current_equipment_plans", []), *analysis.get("rearrangement_plans", [])]
    pending = analysis.get("pending_confirmation_candidates", [])
    return {
        "status": result["status"], "adapter_error": result.get("error", {}).get("code"), "native_error": analysis.get("error", {}).get("code"),
        "available_variants": [plan["variant"]["id"] for plan in plans],
        "pending_variants": [plan["variant"]["id"] for plan in pending],
        "conditions": [{"variant_id": plan["variant"]["id"], "results": plan["condition_results"]} for plan in [*plans, *pending]],
        "diagnostics": result.get("compatibility", {}).get("diagnostics", []),
    }
