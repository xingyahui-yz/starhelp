from __future__ import annotations

import sys
import unittest
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "tools"))
from interop_inputs import CapturedInputs
from starhelp_planner import analyze_producers

ROOT = Path(__file__).parents[1]


class ActualDistributionInteropTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = CapturedInputs(ROOT / "interop/a-b790a52", ROOT / "interop/b-b790a52-cases")
        cls.stage = cls.data.view["stages"][0]

    def request(self, name, b_case=None):
        return self.data.request(self.stage, name=name, b_case=b_case)

    def test_actual_signed_export_and_b_snapshot_retain_original_proof(self):
        request = self.request("actual-normal")
        before = deepcopy(request)
        result = analyze_producers(request)
        self.assertEqual(result["status"], "plans_available", result.get("error"))
        self.assertEqual(len(result["analysis"]["current_equipment_plans"]), 2)
        proof = result["producer_provenance"]["public_bundle"]
        self.assertTrue(proof["signature_verified"])
        self.assertEqual(proof["sha256"], self.data.locks["a_raw_sha256"])
        self.assertEqual(proof["index_release_id"], self.data.release)
        self.assertEqual(proof["approval_and_publication_source"]["producer_commit"], self.data.locks["a_producer_commit"])
        self.assertFalse(proof["internal_hashes_are_signatures"])
        self.assertEqual(result["producer_provenance"]["account_snapshot"]["snapshot_revision"], 4)
        self.assertEqual(request, before)

    def test_complete_alternative_and_no_match_use_unchanged_producer_input(self):
        request = self.request("actual-alternative")
        request["task"]["excluded_character_ids"] = ["fixture:character:a"]
        result = analyze_producers(request)
        self.assertEqual([plan["variant"]["id"] for plan in result["analysis"]["current_equipment_plans"]], ["fixture:variant:alternate"])
        team = result["analysis"]["current_equipment_plans"][0]["team"]
        self.assertEqual({slot["character_id"] for slot in team}, {"fixture:character:b", "fixture:character:c"})
        request = self.request("actual-no-match")
        request["task"]["public_goal"] = {"kind": "fixture:unmatched"}
        result = analyze_producers(request)
        self.assertEqual(result["status"], "no_reviewed_template")
        self.assertTrue(result["analysis"]["citations"])
        self.assertEqual(result["analysis"]["current_equipment_plans"], [])

    def test_actual_b_missing_fields_and_missing_units_are_not_satisfied(self):
        for case, reason in (("missing_fields", "missing_field"), ("confirmed_field_without_measurement", "missing_unit")):
            with self.subTest(case=case):
                result = analyze_producers(self.request("actual-missing", case))
                self.assertEqual(result["status"], "plans_available")  # Producer requirements are soft.
                main = next(plan for plan in result["analysis"]["current_equipment_plans"] if plan["variant"]["id"] == "fixture:variant:main")
                condition = main["condition_results"][0]
                self.assertEqual(condition["match_status"], "unknown")
                self.assertEqual(condition["reason_code"], reason)
                self.assertIsNone(condition["observed"])
                self.assertTrue(main["warnings"])

    def test_transport_release_and_signature_rejections_do_not_repair_inputs(self):
        for case, expected in (("tamper", "producer_digest_mismatch"), ("release", "producer_release_mismatch"), ("key", "unknown_signing_key")):
            with self.subTest(case=case):
                request = self.request("actual-negative")
                if case == "tamper":
                    request["public_bundle"]["raw_json"] += " "
                elif case == "release":
                    request["public_bundle"]["expected_release_id"] += "-other"
                else:
                    request["distribution_trust"]["public_keys"] = {}
                before = deepcopy(request)
                result = analyze_producers(request)
                self.assertEqual(result["error"]["code"], expected)
                self.assertEqual(request, before)

    def test_actual_b_unknown_ownership_and_latest_withdrawal_block_execution(self):
        for case, expected in (("unknown_ownership", "confirmation_required"), ("not_owned", "no_feasible_variant")):
            with self.subTest(case=case):
                request = self.request("actual-ownership", case)
                request["task"]["fixed_character_ids"] = ["fixture:character:a"]
                result = analyze_producers(request)
                self.assertEqual(result["status"], expected)
                self.assertFalse(result["analysis"]["current_equipment_plans"])
        request = self.request("actual-withdrawal")
        request["latest_known_validity"]["withdrawn_public_refs"] = [{"id": self.data.view["evidence"][0]["id"], "revision": 1}]
        result = analyze_producers(request)
        self.assertEqual(result["analysis"]["error"]["code"], "withdrawn_public_object")
        self.assertFalse(result["analysis"]["current_equipment_plans"])


class OfficialDeliveredDistributionInteropTests(ActualDistributionInteropTests):
    @classmethod
    def setUpClass(cls):
        cls.data = CapturedInputs(ROOT / "interop/a-00d4a58", ROOT / "interop/b-045965b-cases")
        cls.stage = cls.data.view["stages"][0]
