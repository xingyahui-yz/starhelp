from __future__ import annotations

import unittest
from copy import deepcopy

from test_planner import analyze
from starhelp_planner.demo_data import synthetic_request
from starhelp_planner.validation import refresh_fixture_members


def main_plan(request):
    result = analyze(request)
    return next(plan for plan in result["current_equipment_plans"] if plan["variant"]["id"] == "fixture:variant:main")


class CultivationTests(unittest.TestCase):
    def test_cost_uses_every_transition_of_the_requested_range(self):
        request = synthetic_request()
        requirement = request["public_bundle"]["variants"][0]["cultivation_requirements"][0]
        requirement["cost_rule"]["transitions"][0]["materials"][0]["amount"] = 7
        plan = main_plan(request)
        self.assertEqual(plan["cultivation"][0]["gap"], 5)
        self.assertEqual(plan["cultivation"][0]["cost"]["materials"][0]["amount"], 15)
        self.assertEqual(plan["cultivation_cost"]["materials"][0]["net_shortage"], 10)

    def test_invalid_cost_rules_never_produce_a_calculated_cost(self):
        changes = [
            (lambda req: req.update(cost_rule={"applicable": True}), "missing_versioned_cost_rule"),
            (lambda req: req["cost_rule"]["scope"].update(game_version="other"), "cost_rule_scope_mismatch"),
            (lambda req: req["cost_rule"].update(subject_entity_id="fixture:char:b"), "cost_rule_subject_mismatch"),
            (lambda req: req["cost_rule"]["transitions"].pop(), "cost_range_not_covered"),
            (lambda req: req["cost_rule"]["transitions"][0]["materials"][0].update(amount=-1), "invalid_material_cost"),
            (lambda req: req["cost_rule"]["transitions"][0]["materials"][0].update(amount=True), "invalid_material_cost"),
            (lambda req: req["cost_rule"]["transitions"].append(deepcopy(req["cost_rule"]["transitions"][0])), "invalid_cost_transition"),
            (lambda req: req.update(target_value=True), "invalid_progression_range"),
        ]
        for change, reason in changes:
            with self.subTest(reason=reason):
                request = synthetic_request()
                change(request["public_bundle"]["variants"][0]["cultivation_requirements"][0])
                plan = main_plan(request)
                self.assertEqual(plan["cultivation"][0]["cost"], {"status": "not_calculated", "reason": reason})
                self.assertEqual(plan["cultivation_cost"]["net_status"], "not_calculated")

    def test_zero_gap_has_zero_cost_without_inventory_deduction(self):
        request = synthetic_request()
        request["public_bundle"]["variants"][0]["cultivation_requirements"][0]["target_value"] = 9
        request["account_snapshot"]["coverage"]["materials"] = "partial"
        plan = main_plan(request)
        self.assertEqual(plan["cultivation"][0]["gap"], 0)
        self.assertEqual(plan["cultivation_cost"]["net_status"], "calculated")
        self.assertEqual(plan["cultivation_cost"]["materials"], [])

    def test_material_uncertainty_retains_gross_cost_but_no_net_shortage(self):
        for changes in ({"state": "conflict"}, {"valid_until": "2026-10-15T00:30:00Z"}, {"count": -1}, {"count": True}, {"unit": "other"}):
            with self.subTest(changes=changes):
                request = synthetic_request()
                request["account_snapshot"]["materials"][0].update(changes)
                cost = main_plan(request)["cultivation_cost"]
                self.assertEqual(cost["status"], "calculated")
                self.assertEqual(cost["materials"][0]["amount"], 10)
                self.assertEqual(cost["net_status"], "not_calculated")
                self.assertIsNone(cost["materials"][0]["net_shortage"])

    def test_four_categories_aggregate_inventory_once(self):
        request = synthetic_request()
        bundle, snapshot = request["public_bundle"], request["account_snapshot"]
        base = bundle["variants"][0]["cultivation_requirements"][0]
        trace = deepcopy(base)
        trace.update(requirement_id="fixture:cultivation:trace", category="trace", current_field="fixture:trace:basic")
        trace["cost_rule"].update(id="fixture:cost:trace", category="trace", attribute="fixture:trace:basic")
        bundle["manifest"]["attribute_definitions"]["fixture:trace:basic"] = deepcopy(bundle["manifest"]["attribute_definitions"]["fixture:level"])
        snapshot["characters"][0]["fields"]["fixture:trace:basic"] = deepcopy(snapshot["characters"][0]["fields"]["fixture:level"])
        requirements = [base, trace]
        bundle["entities"].append({"id": "fixture:cone:type", "revision": 1, "entity_type": "light_cone"})
        cone = {**deepcopy(snapshot["equipment_instances"][0]), "local_instance_id": "fixture:cone:1", "public_type_id": "fixture:cone:type", "kind": "light_cone", "slot": "main"}
        snapshot["equipment_instances"].append(cone)
        for item in snapshot["equipment_instances"]:
            item["fields"] = {"fixture:level": deepcopy(snapshot["characters"][0]["fields"]["fixture:level"])}
            req = deepcopy(base)
            req.update(requirement_id=f"fixture:cultivation:{item['kind']}", category=item["kind"], subject={"kind": "equipment_slot", "slot_id": "fixture:upper:1", "equipment_kind": item["kind"], "equipment_slot": item["slot"]})
            req["cost_rule"].update(id=f"fixture:cost:{item['kind']}", category=item["kind"], subject_entity_id=item["public_type_id"])
            requirements.append(req)
        bundle["variants"][0]["cultivation_requirements"] = requirements
        refresh_fixture_members(bundle, rebuild=True)
        plan = main_plan(request)
        self.assertEqual({step["category"] for step in plan["cultivation"]}, {"character", "trace", "relic", "light_cone"})
        self.assertTrue(all(step["gap"] == 5 for step in plan["cultivation"]))
        self.assertEqual(plan["cultivation_cost"]["materials"], [{"material_id": "fixture:material:1", "amount": 40, "available": 5, "net_shortage": 35}])

    def test_unknown_current_progression_does_not_become_zero(self):
        request = synthetic_request()
        request["account_snapshot"]["characters"][0]["fields"]["fixture:level"]["state"] = "stale"
        step = main_plan(request)["cultivation"][0]
        self.assertIsNone(step["current"])
        self.assertIsNone(step["gap"])
        self.assertEqual(step["cost"]["reason"], "stale_field")
