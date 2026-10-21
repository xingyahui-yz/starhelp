"""Frozen interop boundary corrections using C-native synthetic unit fixtures.

These are not A publication proofs or B serializer captures. Producer replay has
separate immutable inputs and reports.
"""

from __future__ import annotations

import unittest
from copy import deepcopy

from starhelp_planner import analyze
from starhelp_planner.demo_data import synthetic_request
from starhelp_planner.validation import SCOPE_KEYS, refresh_fixture_members


class FrozenBoundaryTests(unittest.TestCase):
    def assert_invalid(self, request):
        before = deepcopy(request)
        result = analyze(request)
        self.assertEqual(result["error"]["code"], "invalid_payload")
        self.assertEqual(result["current_equipment_plans"], [])
        self.assertEqual(result["rearrangement_plans"], [])
        self.assertEqual(request, before)

    def requirement_request(self, requirement):
        request = synthetic_request()
        request["public_bundle"]["variants"][0]["teams"]["fixture:upper"][0]["equipment_requirements"] = [requirement]
        return request

    def allocation_request(self):
        request = synthetic_request()
        request["task"]["fixed_character_ids"] = ["fixture:char:a"]
        request["account_snapshot"]["coverage"]["inventory"] = "partial"
        request["public_bundle"]["variants"][0]["conditions"] = []
        request["account_snapshot"]["equipment_instances"][0]["equipped_by"] = "fixture:char:b"
        refresh_fixture_members(request["public_bundle"])
        return request

    def test_task_scope_requires_exact_six_keys(self):
        for key in SCOPE_KEYS:
            request = synthetic_request()
            del request["task"]["scope"][key]
            with self.subTest(missing=key):
                self.assert_invalid(request)
        for scope in (None, [], {}, {**synthetic_request()["task"]["scope"], "ignored": "value"}):
            request = synthetic_request()
            request["task"]["scope"] = scope
            with self.subTest(scope=scope):
                self.assert_invalid(request)

    def test_scope_types_exclude_boolean_revision_and_do_not_coerce(self):
        for key in SCOPE_KEYS:
            values = (None, True, False, 0, -1, 1.0, "1", [], {}) if key == "stage_revision" else (None, "", 1, True, [], {})
            for value in values:
                request = synthetic_request()
                request["task"]["scope"][key] = value
                with self.subTest(key=key, value=value):
                    self.assert_invalid(request)

    def test_public_scope_types_cannot_use_python_boolean_integer_equality(self):
        for collection in ("stages", "templates"):
            request = synthetic_request()
            request["public_bundle"][collection][0]["scope"]["stage_revision"] = True
            refresh_fixture_members(request["public_bundle"])
            result = analyze(request)
            self.assertEqual(result["error"]["code"], "invalid_public_bundle")
            self.assertIn("invalid_payload", [issue["code"] for issue in result["error"]["details"]["issues"]])

    def test_scope_strings_and_slots_are_opaque(self):
        request = synthetic_request()
        request["task"]["scope"]["stage_id"] += " "
        self.assertEqual(analyze(request)["error"]["code"], "scope_mismatch")
        request = self.allocation_request()
        request["account_snapshot"]["equipment_instances"][0]["slot"] = "relic:body"
        result = analyze(request)
        self.assertEqual(result["status"], "confirmation_required")
        self.assertEqual(result["rearrangement_plans"], [])

    def test_public_goal_requires_full_json_object_and_exact_value_types(self):
        for goal in ({"kind": "fixture:goal:clear", "extra": 1}, {"kind": "fixture:goal:clear", "target": True}):
            request = synthetic_request()
            if "target" in goal:
                request["public_bundle"]["templates"][0]["public_goals"][0]["target"] = 1
                refresh_fixture_members(request["public_bundle"])
            request["task"]["public_goal"] = goal
            result = analyze(request)
            self.assertEqual(result["status"], "no_reviewed_template")
            self.assertEqual(result["current_equipment_plans"], [])

    def test_every_team_slot_requires_explicit_equipment_array(self):
        request = synthetic_request()
        slot = request["public_bundle"]["variants"][1]["teams"]["fixture:lower"][0]
        del slot["equipment_requirements"]
        self.assert_invalid(request)

    def test_requirement_keys_kinds_and_slots_are_closed(self):
        base = {"kind": "relic", "slot": "body"}
        for requirement in ({**base, "minimum_level": 1}, {"slot": "body"}, {"kind": "relic"}, {**base, "kind": "weapon"}, {**base, "slot": ""}, {**base, "slot": 1}):
            with self.subTest(requirement=requirement):
                self.assert_invalid(self.requirement_request(requirement))

    def test_type_restrictions_are_one_of_and_never_fallback_to_unrestricted(self):
        base = {"kind": "relic", "slot": "body"}
        changes = [{"public_type_id": value} for value in (None, "", [], 1, True)]
        changes += [{"public_type_ids": value} for value in (None, "fixture:relic:type", [], [None], [""], [1], ["fixture:relic:type", "fixture:relic:type"])]
        changes += [{"public_type_id": "fixture:relic:type", "public_type_ids": ["fixture:relic:type"]}]
        for change in changes:
            with self.subTest(change=change):
                self.assert_invalid(self.requirement_request({**base, **change}))

    def test_exact_list_and_explicit_unrestricted_requirements_are_valid(self):
        base = {"kind": "relic", "slot": "body"}
        for change in ({}, {"public_type_id": "fixture:relic:type"}, {"public_type_ids": ["fixture:relic:type"]}, {"evidence_refs": [{"id": "fixture:evidence:1", "revision": 1}]}):
            request = self.requirement_request({**base, **change})
            refresh_fixture_members(request["public_bundle"])
            result = analyze(request)
            self.assertIsNone(result.get("error"))
            self.assertIn("fixture:variant:main", [plan["variant"]["id"] for plan in result["current_equipment_plans"]])

    def test_duplicate_seats_and_unrevisioned_evidence_are_rejected(self):
        for evidence in (None, ["fixture:evidence:1"], [{"id": "fixture:evidence:1"}], [{"id": "fixture:evidence:1", "revision": True}], [{"id": "", "revision": 1}]):
            with self.subTest(evidence=evidence):
                self.assert_invalid(self.requirement_request({"kind": "relic", "slot": "body", "evidence_refs": evidence}))
        request = synthetic_request()
        requirements = request["public_bundle"]["variants"][0]["teams"]["fixture:upper"][0]["equipment_requirements"]
        requirements.append(deepcopy(requirements[0]))
        self.assert_invalid(request)

    def test_same_release_reference_kind_and_dependency_gates_are_distinct(self):
        request = synthetic_request()
        entity = next(item for item in request["public_bundle"]["entities"] if item["id"] == "fixture:relic:type")
        entity["entity_type"] = "light_cone"
        refresh_fixture_members(request["public_bundle"])
        result = analyze(request)
        self.assertIsNone(result.get("error"))
        self.assertIn("invalid_variant", [item["code"] for item in result["rejected_variants"]])
        self.assertNotIn("fixture:variant:main", [plan["variant"]["id"] for plan in result["current_equipment_plans"]])
        request = self.requirement_request({"kind": "relic", "slot": "body", "public_type_id": "fixture:missing"})
        refresh_fixture_members(request["public_bundle"])
        result = analyze(request)
        self.assertEqual(result["error"]["code"], "invalid_public_bundle")
        codes = [item["code"] for item in result["error"]["details"]["issues"]]
        self.assertIn("missing_member", codes)
        self.assertNotIn("integrity_failed", codes)

    def test_player_confirmed_move_and_lock_change_actual_observed_allocation(self):
        request = self.allocation_request()
        result = analyze(request)
        self.assertEqual(result["rearrangement_plans"][0]["equipment"]["actions"], [{"local_instance_id": "fixture:gear:1", "from_character_id": "fixture:char:b", "to_character_id": "fixture:char:a"}])
        request["task"]["locked_local_instance_ids"] = ["fixture:gear:1"]
        result = analyze(request)
        self.assertEqual(result["status"], "confirmation_required")
        self.assertEqual(result["rearrangement_plans"], [])
        self.assertEqual(result["current_equipment_plans"], [])
        self.assertIsNone(result["pending_confirmation_candidates"][0]["equipment"])

    def test_ambiguous_and_unconfirmed_identity_never_propose_cross_character_moves(self):
        for identity in ("ambiguous", "unconfirmed"):
            request = self.allocation_request()
            request["account_snapshot"]["equipment_instances"][0]["identity_state"] = identity
            result = analyze(request)
            self.assertEqual(result["status"], "confirmation_required")
            self.assertEqual(result["rearrangement_plans"], [])

    def test_same_type_distinct_instances_remain_distinct_and_duplicates_conflict(self):
        request = self.allocation_request()
        items = request["account_snapshot"]["equipment_instances"]
        items.append({**items[0], "local_instance_id": "fixture:gear:2", "equipped_by": "fixture:char:c"})
        request["task"]["locked_local_instance_ids"] = ["fixture:gear:1"]
        result = analyze(request)
        self.assertEqual(result["rearrangement_plans"][0]["equipment"]["actions"][0]["local_instance_id"], "fixture:gear:2")
        items[1]["local_instance_id"] = items[0]["local_instance_id"]
        self.assertEqual(analyze(request)["error"]["code"], "snapshot_conflict")
