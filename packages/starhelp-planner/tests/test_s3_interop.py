"""Actual new A/B1 captures; consumer negatives keep producer captures intact."""

from __future__ import annotations

import hashlib
import json
import unittest
from copy import deepcopy
from pathlib import Path

from starhelp_planner import analyze_producers, prepare_producer_request

ROOT = Path(__file__).parents[1]
B_CAPTURE = ROOT / "interop/b-103741e-s3-v1"
A_CAPTURE = ROOT / "interop/a-dcb1e3e-s3"


def available(result):
    analysis = result.get("analysis") or {}
    return [*analysis.get("current_equipment_plans", []), *analysis.get("rearrangement_plans", [])]


class S3CapturedInteropTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.locks = json.loads((B_CAPTURE / "producer-locks.json").read_bytes())

    def request(self, name, stage=0):
        case = self.locks["cases"][f"stage-{stage}-{name}"]
        raw = (B_CAPTURE / case["wrapper"]).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), self.locks["files"][case["wrapper"]])
        return json.loads(raw)["producer_request"]

    def test_new_a_source_package_artifact_and_finite_equipment_table(self):
        locks = json.loads((A_CAPTURE / "consumer-capture-locks.json").read_bytes())
        self.assertEqual(locks["a_producer_commit"], "dcb1e3ee220b85229bedc6c79d72ebe495825f37")
        self.assertEqual(locks["a_package_version"], "0.3.0")
        self.assertEqual(locks["official_delivery_artifact_commit"], "4610573ee9720f2b5e4760a9336263362446b800")
        self.assertEqual(len(locks["official_git_blob_bytes_match"]), 5)
        for name, expected in locks["files"].items():
            self.assertEqual(hashlib.sha256((A_CAPTURE / name).read_bytes()).hexdigest(), expected)
        public = json.loads((A_CAPTURE / locks["a_artifact"]).read_bytes())
        view = public["objects"]["planner-view:" + locks["release_id"]]["bundle"]
        table = json.loads((A_CAPTURE / "equipment-type-table.json").read_bytes())
        self.assertEqual(table["release_id"], locks["release_id"])
        entities = {item["id"]: item for item in view["entities"]}
        tuples = {(item["kind"], item["slot"], item["public_type_id"], item["entity_type"]) for item in table["items"]}
        self.assertEqual(len(tuples), 2)
        for variant in view["variants"]:
            for team in variant["teams"].values():
                for seat in team:
                    for requirement in seat["equipment_requirements"]:
                        ids = [requirement["public_type_id"]] if "public_type_id" in requirement else requirement["public_type_ids"]
                        for identifier in ids:
                            self.assertIn((requirement["kind"], requirement["slot"], identifier, entities[identifier]["entity_type"]), tuples)

    def test_each_mode_has_main_complete_alternate_and_consumer_no_template(self):
        for stage, mode in enumerate(("alpha", "beta", "gamma")):
            with self.subTest(mode=mode):
                request = self.request("normal", stage)
                before = deepcopy(request)
                result = analyze_producers(request)
                self.assertEqual(result["status"], "plans_available")
                self.assertEqual({plan["variant"]["id"] for plan in available(result)}, {f"fixture:s3:{mode}:variant:main", f"fixture:s3:{mode}:variant:alternate"})
                self.assertEqual(request, before)
                result = analyze_producers(self.request("complete_alternate", stage))
                self.assertEqual(result["status"], "plans_available")
                self.assertEqual([plan["variant"]["id"] for plan in available(result)], [f"fixture:s3:{mode}:variant:alternate"])
                self.assertEqual(len(available(result)[0]["team"]), 2)
                # This is a C consumer-task negative, not output accepted by B's selector.
                request["task"]["public_goal"] = {"kind": "fixture:consumer-no-reviewed-template"}
                result = analyze_producers(request)
                self.assertEqual(result["status"], "no_reviewed_template")
                self.assertEqual(available(result), [])

    def test_current_equipment_and_real_move_then_lock_are_observable(self):
        result = analyze_producers(self.request("main_current_equipment"))
        main = next(plan for plan in result["analysis"]["current_equipment_plans"] if plan["variant"]["variant_kind"] == "main")
        self.assertEqual(main["equipment"]["actions"], [])
        moving = self.request("player_confirmed_move")
        locked = self.request("locked_move")
        self.assertEqual(moving["account_snapshot"], locked["account_snapshot"])
        self.assertTrue(any(plan["equipment"]["actions"] for plan in available(analyze_producers(moving))))
        result = analyze_producers(locked)
        self.assertEqual(result["status"], "confirmation_required")
        self.assertEqual(available(result), [])
        self.assertTrue(all({"reason": "inventory_coverage_incomplete"} in plan["pending_reasons"] for plan in result["analysis"]["pending_confirmation_candidates"]))

    def test_distinct_type_copies_remain_unique_and_unreliable_identities_cannot_move(self):
        request = self.request("same_type_distinct_instance")
        result = analyze_producers(request)
        self.assertEqual(result["status"], "plans_available")
        locked = set(request["task"]["locked_local_instance_ids"])
        for plan in available(result):
            instances = [assignment["local_instance_id"] for assignment in plan["equipment"]["assignments"]]
            self.assertEqual(len(instances), len(set(instances)))
            self.assertTrue(plan["equipment"]["actions"])
            self.assertFalse(any(action["local_instance_id"] in locked for action in plan["equipment"]["actions"]))
        for name in ("ambiguous_move", "source_confirmed_move"):
            result = analyze_producers(self.request(name))
            self.assertEqual(result["status"], "confirmation_required")
            self.assertEqual(available(result), [])

    def test_ownership_and_disallow_rearrangement_are_hard_constraints(self):
        for stage in range(3):
            self.assertEqual(analyze_producers(self.request("not_owned", stage))["status"], "no_feasible_variant")
            self.assertEqual(analyze_producers(self.request("unknown_ownership", stage))["status"], "confirmation_required")
        request = self.request("player_confirmed_move")
        request["task"]["allow_rearrangement"] = False
        result = analyze_producers(request)
        self.assertEqual(result["status"], "confirmation_required")
        self.assertEqual(available(result), [])

    def test_scope_rejection_reports_actual_adapter_boundary(self):
        for key, value in (("extra", "unknown"), ("stage_revision", True)):
            request = self.request("normal")
            request["task"]["scope"][key] = value
            result = analyze_producers(request)
            self.assertEqual(result["error"]["code"], "invalid_producer_payload")
            self.assertIsNone(result["analysis"])

    def test_digest_and_missing_dependency_gates_are_separate(self):
        request = self.request("normal")
        request["public_bundle"]["raw_json"] += " "
        self.assertEqual(analyze_producers(request)["error"]["code"], "producer_digest_mismatch")
        request = self.request("normal")
        original = deepcopy(request)
        public = json.loads(request["public_bundle"]["raw_json"])
        signed_manifest = deepcopy(public["manifest"])
        del public["objects"]["native-release:" + self.locks["a_release_id"]]
        # Construct a separate negative transport. No producer member/signature
        # digest or captured file is repaired; this is explicitly not A output.
        raw = json.dumps(public, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode() + b"\n"
        request["public_bundle"].update(raw_json=raw.decode(), sha256=hashlib.sha256(raw).hexdigest())
        self.assertEqual(public["manifest"], signed_manifest)
        self.assertNotEqual(request["public_bundle"]["sha256"], original["public_bundle"]["sha256"])
        self.assertEqual(analyze_producers(request)["error"]["code"], "producer_dependency_missing")
        self.assertEqual(self.request("normal"), original)

    def test_b1_does_not_invent_material_or_final_panel_coverage(self):
        prepared = prepare_producer_request(self.request("normal"))
        self.assertEqual(prepared["status"], "ready")
        snapshot = prepared["native_request"]["account_snapshot"]
        self.assertEqual(snapshot["coverage"], {"roster": "partial", "inventory": "partial", "materials": "unknown"})
        self.assertNotIn("materials", snapshot)
        self.assertNotIn("loadout_views", snapshot)
