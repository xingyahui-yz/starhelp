"""Consume immutable captures emitted by the actual fixed B1 implementation."""

from __future__ import annotations

import hashlib
import json
import unittest
from copy import deepcopy
from pathlib import Path

from starhelp_planner import analyze_producers
from starhelp_planner.adapters.b_snapshot import B_INTEROP_COMMIT, B_INTEROP_PROFILE, B_PROFILE, adapt_snapshot
from starhelp_planner.adapters.common import B_COMMIT, AdaptationError

ROOT = Path(__file__).parents[1] / "interop/b-103741e-legacy-a-v1"


class B1PinnedInteropTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.locks = json.loads((ROOT / "producer-locks.json").read_bytes())

    def wrapper(self, name="normal"):
        filename = self.locks["cases"]["stage-0-" + name]["wrapper"]
        raw = (ROOT / filename).read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), self.locks["files"][filename])
        return json.loads(raw)

    def test_actual_b1_tuple_preserves_original_bytes_and_missing_measurements(self):
        request = self.wrapper()["producer_request"]
        before = deepcopy(request)
        result = analyze_producers(request)
        self.assertEqual(result["status"], "plans_available", result.get("error"))
        self.assertEqual(len(result["analysis"]["current_equipment_plans"]), 2)
        proof = result["producer_provenance"]["account_snapshot"]
        self.assertEqual(proof["producer_commit"], B_INTEROP_COMMIT)
        self.assertEqual(proof["format_profile"], B_INTEROP_PROFILE)
        self.assertEqual(proof["sha256"], request["account_snapshot"]["sha256"])
        self.assertEqual(request, before)
        self.assertTrue(self.locks["source_verified_before_and_after"])
        self.assertEqual(len(self.locks["source_proof"]["file_sha256"]), 38)
        self.assertFalse(self.locks["equipment_positive_coverage_present"])

    def test_commit_and_profile_are_a_tuple_with_no_metadata_commit_alias(self):
        context = self.wrapper()["producer_request"]["authorization_context"]
        for commit, profile in ((B_INTEROP_COMMIT, B_PROFILE), (B_COMMIT, B_INTEROP_PROFILE), ("aef35e46bd145688bc257b542a2e03b31175d3a9", B_INTEROP_PROFILE)):
            envelope = self.wrapper()["producer_request"]["account_snapshot"]
            envelope.update(producer_commit=commit, format_profile=profile)
            with self.subTest(commit=commit, profile=profile), self.assertRaises(AdaptationError) as caught:
                adapt_snapshot(envelope, context, [])
            self.assertEqual(caught.exception.code, "unsupported_producer_version")

    def test_every_capture_is_locked_and_builder_rejections_did_not_reach_c(self):
        for filename, expected in self.locks["files"].items():
            self.assertEqual(hashlib.sha256((ROOT / filename).read_bytes()).hexdigest(), expected)
        for case in self.locks["cases"].values():
            self.assertTrue(case["builder_bytes_equal_independent_serializer"])
        self.assertEqual(len(self.locks["builder_rejections"]), 4)
        self.assertTrue(all(case["C_reached"] is False for case in self.locks["builder_rejections"].values()))

    def test_actual_b1_ownership_is_not_silently_promoted(self):
        request = self.wrapper("unknown_ownership")["producer_request"]
        normalized, _, _ = adapt_snapshot(request["account_snapshot"], request["authorization_context"], [])
        self.assertEqual(normalized["characters"][0]["ownership"], "unknown")
        self.assertEqual(normalized["coverage"], {"roster": "partial", "inventory": "partial", "materials": "unknown"})
        result = analyze_producers(request)
        self.assertTrue(result["analysis"]["pending_confirmation_candidates"])
        self.assertEqual(result["status"], "plans_available")  # Independent complete alternate remains available.
