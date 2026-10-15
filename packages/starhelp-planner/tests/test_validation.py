from __future__ import annotations

import json
import unittest
from copy import deepcopy

from starhelp_planner import analyze
from starhelp_planner.demo_data import synthetic_request
from starhelp_planner.validation import refresh_fixture_members


class BundleAndBoundaryTests(unittest.TestCase):
    def assert_bundle_issue(self, request, code):
        result = analyze(request)
        self.assertEqual(result["error"]["code"], "invalid_public_bundle")
        self.assertIn(code, [issue["code"] for issue in result["error"]["details"]["issues"]])
        self.assertEqual(result["current_equipment_plans"], [])

    def test_tampering_or_incomplete_manifest_is_rejected(self):
        for case in ("content", "orphan", "missing", "dependency", "untyped_dependency"):
            with self.subTest(case=case):
                request = synthetic_request()
                bundle = request["public_bundle"]
                if case == "content":
                    bundle["variants"][0]["title"] = "tampered"
                elif case == "orphan":
                    bundle["manifest"]["members"].append({"kind": "entity", "id": "absent", "revision": 1})
                elif case == "missing":
                    bundle["manifest"]["members"].pop()
                elif case == "dependency":
                    next(m for m in bundle["manifest"]["members"] if m["kind"] == "variant")["dependencies"] = []
                else:
                    bundle["manifest"]["members"][0]["dependencies"] = [{"kind": ["entity"], "id": {}, "revision": True}]
                self.assert_bundle_issue(request, "integrity_failed" if case == "content" else "missing_member")

    def test_nested_schema_capability_release_and_reference_type_are_checked(self):
        for changes, code in (
            ({"required_capabilities": ["unsupported"]}, "unsupported_capability"),
            ({"schema_version": "future"}, "unsupported_schema"),
            ({"index_release_id": "another-release"}, "release_mismatch"),
            ({"evidence_refs": [{"id": "fixture:char:a", "revision": 1}]}, "missing_member"),
            ({"local_instance_id": "private-item"}, "invalid_payload"),
        ):
            with self.subTest(code=code):
                request = synthetic_request()
                request["public_bundle"]["variants"][0].update(changes)
                refresh_fixture_members(request["public_bundle"])
                self.assert_bundle_issue(request, code)

    def test_revoked_nested_dependency_does_not_disable_independent_alternative(self):
        request = synthetic_request()
        bundle = request["public_bundle"]
        second = {**bundle["evidence"][0], "id": "fixture:evidence:nested"}
        bundle["evidence"].append(second)
        bundle["templates"][0]["variant_ids"] = [variant["id"] for variant in bundle["variants"]]
        bundle["variants"][0]["steps"] = [{"text": "synthetic step", "evidence_refs": [{"id": second["id"], "revision": 1}]}]
        refresh_fixture_members(bundle, rebuild=True)
        request["latest_known_validity"]["withdrawn_public_refs"] = [{"id": second["id"], "revision": 1}]
        result = analyze(request)
        self.assertEqual([p["variant"]["id"] for p in result["current_equipment_plans"]], ["fixture:variant:alternate"])
        self.assertTrue(any(r["variant_id"] == "fixture:variant:main" and r["code"] == "unavailable_public_dependency" for r in result["rejected_variants"]))

    def test_variant_and_entity_scope_cannot_bypass_template_scope(self):
        for collection, changes in (("variants", {"scope": {"game_version": "other"}}), ("entities", {"environment": "other"})):
            with self.subTest(collection=collection):
                request = synthetic_request()
                request["public_bundle"][collection][0].update(changes)
                refresh_fixture_members(request["public_bundle"])
                result = analyze(request)
                self.assertEqual([plan["variant"]["id"] for plan in result["current_equipment_plans"]], ["fixture:variant:alternate"])
                self.assertIn("fixture:variant:main", [entry["variant_id"] for entry in result["rejected_variants"]])

    def test_derived_availability_preserves_reference_kind(self):
        request = synthetic_request()
        bundle = request["public_bundle"]
        bundle["entities"].append({"id": "fixture:template:1", "revision": 1, "entity_type": "material", "environment": "other"})
        refresh_fixture_members(bundle, rebuild=True)
        result = analyze(request)
        self.assertEqual(len(result["current_equipment_plans"]), 2)
        self.assertIn({"kind": "entity", "id": "fixture:template:1", "revision": 1}, result["validity"]["unavailable_public_objects"])

    def test_goal_and_actual_rule_version_are_explicit(self):
        request = synthetic_request()
        request["local_rule_version"] = "0.2.0"
        result = analyze(request)
        self.assertEqual(result["local_rule_version"], result["planner_version"])
        request["local_rule_version"] = "caller-invented"
        self.assertEqual(analyze(request)["error"]["code"], "unsupported_rule_version")
        del request["local_rule_version"]
        request["task"]["public_goal"] = {"kind": "unsupported-goal"}
        result = analyze(request)
        self.assertEqual(result["status"], "no_reviewed_template")
        self.assertEqual(result["current_equipment_plans"], [])

    def test_invalid_shapes_and_non_json_inputs_fail_without_callbacks(self):
        class Unexpected(dict):
            def get(self, *args):
                raise AssertionError("custom input method invoked")
        inputs = [None, [], Unexpected(), {"request_id": object()}]
        for change in (lambda r: r["task"].update(fixed_character_ids="fixture:char:a"), lambda r: r["account_snapshot"].update(characters=["bad-row"]), lambda r: r["public_bundle"]["variants"][0].update(conditions=[None]), lambda r: r["public_bundle"]["stages"][0].update(resource_reuse={"equipment": "reusable"})):
            request = synthetic_request()
            change(request)
            inputs.append(request)
        for value in inputs:
            with self.subTest(value_type=type(value).__name__):
                result = analyze(value)
                self.assertEqual(result["error"]["code"], "invalid_payload")
                json.dumps(result, allow_nan=False)

    def test_result_and_input_are_isolated_and_repeatable(self):
        request = synthetic_request()
        before = deepcopy(request)
        result = analyze(request)
        self.assertEqual(request, before)
        self.assertEqual(result, analyze(deepcopy(request)))
        json.dumps(result, allow_nan=False)
        result["public_goal"]["kind"] = "mutated"
        result["current_equipment_plans"][0]["team"][0]["character_id"] = "mutated"
        self.assertEqual(request, before)

    def test_troubleshooting_target_is_rechecked_against_constraints(self):
        request = synthetic_request()
        request["feedback"] = {"fields": {"fixture:failure_kind": {"value": "fixture:survival", "state": "user_reported", "unit": "fixture:label", "measurement_context": {"phase": "fixture:reported", "assumptions": []}}}}
        request["task"]["excluded_character_ids"] = ["fixture:char:c"]
        self.assertEqual(analyze(request)["troubleshooting"]["status"], "unable_to_determine")
        request["task"]["excluded_character_ids"] = []
        request["account_snapshot"]["characters"][2]["ownership"] = "unknown"
        suggestion = analyze(request)["troubleshooting"]["suggestions"][0]
        self.assertEqual(suggestion["eligibility"], "confirmation_required")
        self.assertTrue(suggestion["pending_reasons"])

    def test_one_instance_cannot_fill_two_partition_requirements(self):
        request = synthetic_request()
        bundle = request["public_bundle"]
        bundle["variants"][0]["teams"]["fixture:lower"][0]["equipment_requirements"] = [{"kind": "relic", "slot": "body", "public_type_id": "fixture:relic:type"}]
        refresh_fixture_members(bundle)
        result = analyze(request)
        self.assertFalse(any(plan["variant"]["id"] == "fixture:variant:main" for plan in result["current_equipment_plans"] + result["rearrangement_plans"]))
        self.assertTrue(any(entry["variant_id"] == "fixture:variant:main" and entry["code"] == "equipment_conflict" for entry in result["rejected_variants"]))
