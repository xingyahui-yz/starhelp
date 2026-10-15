from __future__ import annotations

import unittest
from copy import deepcopy

from test_planner import analyze
from starhelp_planner.conditions import final_equipment, loadout_fingerprint
from starhelp_planner.demo_data import synthetic_request


class MeasurementSemanticsTests(unittest.TestCase):
    def test_missing_or_mismatched_measurements_never_pass(self):
        cases = [
            ({"value": None}, "missing_field"),
            ({"state": "conflict"}, "conflicting_field"),
            ({"unit": "percent"}, "unit_mismatch"),
            ({"unit": None}, "missing_unit"),
            ({"measurement_context": None}, "missing_measurement_context"),
            ({"measurement_context": {"phase": "in_battle", "assumptions": []}}, "measurement_context_mismatch"),
            ({"measurement_context": {"phase": "fixture:pre_battle", "assumptions": ["buff"]}}, "measurement_context_mismatch"),
            ({"state": "user_reported"}, "unconfirmed_field"),
            ({"valid_until": "2026-10-15T01:00:00Z"}, "stale_field"),
        ]
        for changes, reason in cases:
            with self.subTest(reason=reason):
                request = synthetic_request()
                request["account_snapshot"]["characters"][0]["fields"]["fixture:stat:speed"].update(changes)
                result = analyze(request)
                candidate = next(p for p in result["pending_confirmation_candidates"] if p["variant"]["id"] == "fixture:variant:main")
                self.assertEqual(candidate["condition_results"][0]["match_status"], "unknown")
                self.assertEqual(candidate["condition_results"][0]["reason_code"], reason)

    def test_rearrangement_does_not_reuse_old_character_panel(self):
        request = synthetic_request()
        request["account_snapshot"]["equipment_instances"][0]["equipped_by"] = "fixture:char:b"
        result = analyze(request)
        self.assertFalse(any(p["variant"]["id"] == "fixture:variant:main" for p in result["rearrangement_plans"]))
        candidate = next(p for p in result["pending_confirmation_candidates"] if p["variant"]["id"] == "fixture:variant:main")
        self.assertEqual(candidate["candidate_plan_kind"], "rearrangement")
        self.assertEqual(candidate["condition_results"][0]["reason_code"], "loadout_changed_without_confirmed_panel")

    def test_confirmed_panel_for_exact_final_loadout_can_be_used(self):
        request = synthetic_request()
        snapshot = request["account_snapshot"]
        snapshot["equipment_instances"][0]["equipped_by"] = "fixture:char:b"
        allocation = {"actions": [{"local_instance_id": "fixture:gear:1", "to_character_id": "fixture:char:a"}]}
        fingerprint = loadout_fingerprint(final_equipment(snapshot["equipment_instances"], allocation), "fixture:char:a")
        snapshot["loadout_views"] = [{"character_id": "fixture:char:a", "loadout_fingerprint": fingerprint, "fields": deepcopy(snapshot["characters"][0]["fields"])}]
        result = analyze(request)
        self.assertTrue(any(p["variant"]["id"] == "fixture:variant:main" for p in result["rearrangement_plans"]))

    def test_allocator_checks_item_conditions_on_every_mapping(self):
        request = synthetic_request()
        condition = request["public_bundle"]["variants"][0]["conditions"][0]
        condition.update(subject={"kind": "equipment_slot", "slot_id": "fixture:upper:1", "equipment_kind": "relic", "equipment_slot": "body"}, attribute="fixture:item:stat", measurement_context={"phase": "item", "assumptions": []})
        gear = request["account_snapshot"]["equipment_instances"][0]
        gear["fields"] = {"fixture:item:stat": {"value": 50, "state": "confirmed", "unit": "fixture:flat", "measurement_context": {"phase": "item", "assumptions": []}}}
        better = deepcopy(gear)
        better.update(local_instance_id="fixture:gear:better", equipped_by=None)
        better["fields"]["fixture:item:stat"]["value"] = 150
        request["account_snapshot"]["equipment_instances"].append(better)
        result = analyze(request)
        plan = next(p for p in result["rearrangement_plans"] if p["variant"]["id"] == "fixture:variant:main")
        self.assertEqual(plan["condition_results"][0]["observed"], 150)
        self.assertTrue(any(a["local_instance_id"] == "fixture:gear:better" for a in plan["equipment"]["assignments"]))

    def test_bounded_search_does_not_claim_all_allocations_failed(self):
        request = synthetic_request()
        condition = request["public_bundle"]["variants"][0]["conditions"][0]
        condition.update(subject={"kind": "equipment_slot", "slot_id": "fixture:upper:1", "equipment_kind": "relic", "equipment_slot": "body"}, attribute="fixture:item:stat", measurement_context={"phase": "item", "assumptions": []})
        original = request["account_snapshot"]["equipment_instances"][0]
        items = []
        for index in range(257):
            item = deepcopy(original)
            item.update(local_instance_id=f"fixture:gear:{index:04d}", equipped_by=None)
            item["fields"] = {"fixture:item:stat": {"value": 150 if index == 256 else 50, "state": "confirmed", "unit": "fixture:flat", "measurement_context": {"phase": "item", "assumptions": []}}}
            items.append(item)
        request["account_snapshot"]["equipment_instances"] = items
        result = analyze(request)
        candidate = next(plan for plan in result["pending_confirmation_candidates"] if plan["variant"]["id"] == "fixture:variant:main")
        self.assertEqual(candidate["candidate_plan_kind"], "rearrangement")
        self.assertIsNone(candidate["equipment"])
        self.assertIn({"reason": "allocation_search_incomplete"}, candidate["pending_reasons"])
        self.assertFalse(any(rejection["variant_id"] == "fixture:variant:main" and rejection["code"] == "hard_condition_failed" for rejection in result["rejected_variants"]))
