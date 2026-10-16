from __future__ import annotations

import hashlib
import json
import unittest
from copy import deepcopy
from pathlib import Path

from starhelp_planner.adapters import analyze_producers
from starhelp_planner.adapters.b_snapshot import B_PROFILE, adapt_snapshot
from starhelp_planner.adapters.common import ADAPTER_PROFILE, A_BASELINE, B_COMMIT, AdaptationError

BASELINE = Path(__file__).parents[1] / "interop" / "baseline"


def original_envelope(producer, commit, profile, path, expected):
    return {"producer": producer, "producer_commit": commit, "format_profile": profile, "raw_json": path.read_bytes().decode("utf-8"), "sha256": expected}


def baseline_request():
    locks = json.loads((BASELINE / "producer-locks.json").read_text(encoding="utf-8"))
    return {
        "schema_id": "ProducerAnalysisRequest", "schema_version": "0.1", "adapter_profile": ADAPTER_PROFILE,
        "request_id": "fixture:baseline-rejection",
        "public_bundle": original_envelope("starhelp_knowledge", A_BASELINE, "starhelp.knowledge.native.313508f", BASELINE / locks["a"]["file"], locks["a"]["raw_sha256"]),
        "account_snapshot": original_envelope("starhelp_desktop", B_COMMIT, B_PROFILE, BASELINE / locks["b"]["file"], locks["b"]["raw_sha256"]),
        "authorization_context": json.loads((BASELINE / "caller-context.json").read_text(encoding="utf-8")),
    }


class ProducerBaselineTests(unittest.TestCase):
    def test_actual_baseline_export_is_verified_then_refused_for_missing_semantics(self):
        request = baseline_request()
        before = deepcopy(request)
        result = analyze_producers(request)
        self.assertEqual(result["error"]["code"], "producer_semantics_missing")
        proof = result["error"]["details"]["original_proof"]
        self.assertTrue(proof["original_digest_and_closure_verified"])
        self.assertEqual(proof["sha256"], request["public_bundle"]["sha256"])
        self.assertIn("required stage seats", result["error"]["details"]["missing"])
        self.assertIsNone(result["analysis"])
        self.assertEqual(request, before)

    def test_original_bytes_cannot_be_repaired_or_relabelled_implicitly(self):
        request = baseline_request()
        request["public_bundle"]["raw_json"] += " "  # Transport bytes changed; pinned digest unchanged.
        self.assertEqual(analyze_producers(request)["error"]["code"], "producer_digest_mismatch")
        request = baseline_request()
        request["public_bundle"]["producer_commit"] = "unknown"
        self.assertEqual(analyze_producers(request)["error"]["code"], "unsupported_producer_version")

    def test_actual_b_serializer_output_keeps_missing_measurement_metadata_unknown(self):
        request = baseline_request()
        normalized, proof, diagnostics = adapt_snapshot(request["account_snapshot"], request["authorization_context"], [])
        field = normalized["characters"][0]["fields"]["stat:speed"]
        self.assertEqual(field["state"], "confirmed")
        self.assertNotIn("unit", field)
        self.assertNotIn("measurement_context", field)
        self.assertEqual(field["producer_scope"], "synthetic-panel-with-unspecified-unit")
        self.assertEqual(normalized["coverage"], {"roster": "partial", "inventory": "partial", "materials": "unknown"})
        self.assertTrue(diagnostics)
        self.assertEqual(proof["producer_commit"], B_COMMIT)

    def test_snapshot_does_not_imply_authorization_or_change_generation(self):
        request = baseline_request()
        with self.assertRaises(AdaptationError) as caught:
            adapt_snapshot(request["account_snapshot"], {}, [])
        self.assertEqual(caught.exception.code, "authorization_context_required")
        self.assertEqual(hashlib.sha256(request["account_snapshot"]["raw_json"].encode("utf-8")).hexdigest(), request["account_snapshot"]["sha256"])

    def b_case(self, name):
        root = BASELINE.parent / "b-baseline-cases"
        lock = json.loads((root / "producer-locks.json").read_bytes())["cases"][name]
        return original_envelope("starhelp_desktop", B_COMMIT, B_PROFILE, root / lock["file"], lock["sha256"])

    def test_actual_b_identities_are_preserved_or_downgraded_without_upgrade(self):
        context = baseline_request()["authorization_context"]
        public_types = [{"id": "fixture:relic:type", "entity_type": "relic"}]
        for name, expected in (("ambiguous_equipment", "ambiguous"), ("source_confirmed_equipment", "unconfirmed"), ("player_confirmed_equipment", "player_confirmed")):
            with self.subTest(name=name):
                envelope = self.b_case(name)
                before = deepcopy(envelope)
                normalized, _, diagnostics = adapt_snapshot(envelope, context, public_types)
                item = normalized["equipment_instances"][0]
                self.assertEqual(item["identity_state"], expected)
                self.assertEqual(item["slot"], "relic:1")
                self.assertEqual(item["kind"], "relic")
                self.assertEqual(envelope, before)
                if name == "source_confirmed_equipment":
                    self.assertIn("source_confirmed_is_not_source_verified", [entry["reason"] for entry in diagnostics])

    def test_actual_b_ownership_and_absent_fields_remain_explicit(self):
        context = baseline_request()["authorization_context"]
        for name, expected in (("normal", "owned"), ("unknown_ownership", "unknown"), ("not_owned", "not_owned")):
            with self.subTest(name=name):
                normalized, _, _ = adapt_snapshot(self.b_case(name), context, [])
                self.assertEqual(normalized["characters"][0]["ownership"], expected)
        normalized, _, _ = adapt_snapshot(self.b_case("missing_fields"), context, [])
        self.assertTrue(all(character["fields"] == {} for character in normalized["characters"]))

    def test_actual_b_zero_revision_is_refused_without_renumbering(self):
        envelope = self.b_case("zero_revision")
        with self.assertRaises(AdaptationError) as caught:
            adapt_snapshot(envelope, baseline_request()["authorization_context"], [])
        self.assertEqual(caught.exception.code, "unsupported_snapshot_revision")
        self.assertEqual(json.loads(envelope["raw_json"])["revision"], 0)
