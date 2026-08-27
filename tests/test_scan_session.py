import json
import unittest
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from abyss_ai.account_scan import (
    FixtureOcrEngine,
    ReviewedCorrection,
    ScanFrame,
    ScanSession,
)
from abyss_ai.simulation import build_scenario


class FixtureOcrTests(unittest.TestCase):
    def test_rejects_wrong_resolution(self) -> None:
        frame = replace(build_scenario("ready").scan_frames[0], width=1280)
        with self.assertRaisesRegex(ValueError, "resolution"):
            FixtureOcrEngine().scan(frame)

    def test_rejects_out_of_range_field(self) -> None:
        scenario = build_scenario("ready")
        payload = json.loads(scenario.scan_frames[0].pixels)
        payload["fields"]["level"]["value"] = 99
        bad = replace(scenario.scan_frames[0], pixels=json.dumps(payload).encode())
        result = ScanSession(FixtureOcrEngine()).run(
            (bad, *scenario.scan_frames[1:]),
            account_id=uuid4(),
            expected_fingerprint=scenario.account_fingerprint,
            game_version=scenario.game_version,
        )
        self.assertFalse(result.planning_allowed)
        self.assertTrue(any("outside allowed range" in issue for issue in result.issues))

    def test_rejects_cross_account_frame(self) -> None:
        scenario = build_scenario("ready")
        payload = json.loads(scenario.scan_frames[0].pixels)
        payload["account_fingerprint"] = "another-account"
        bad = replace(scenario.scan_frames[0], pixels=json.dumps(payload).encode())
        result = ScanSession(FixtureOcrEngine()).run(
            (bad, *scenario.scan_frames[1:]),
            account_id=uuid4(),
            expected_fingerprint=scenario.account_fingerprint,
            game_version=scenario.game_version,
        )
        self.assertFalse(result.planning_allowed)
        self.assertTrue(any("fingerprint mismatch" in issue for issue in result.issues))

    def test_valid_scan_binds_equipment_to_account(self) -> None:
        scenario = build_scenario("ready")
        account_id = uuid4()
        result = ScanSession(FixtureOcrEngine()).run(
            scenario.scan_frames,
            account_id=account_id,
            expected_fingerprint=scenario.account_fingerprint,
            game_version=scenario.game_version,
        )
        self.assertTrue(result.planning_allowed)
        assert result.snapshot is not None
        self.assertEqual(len(result.snapshot.characters), 8)
        for character in result.snapshot.characters:
            self.assertEqual(character.account_id, account_id)
            assert character.light_cone is not None
            self.assertEqual(character.light_cone.account_id, account_id)
            self.assertEqual(len(character.relics), 6)

    def test_reviewed_correction_preserves_original_and_allows_snapshot(self) -> None:
        scenario = build_scenario("low-confidence")
        correction = ReviewedCorrection(
            "character_0.level",
            "80",
            "80",
            "人工核对角色详情页",
        )
        result = ScanSession(FixtureOcrEngine()).run(
            scenario.scan_frames,
            account_id=uuid4(),
            expected_fingerprint=scenario.account_fingerprint,
            game_version=scenario.game_version,
            corrections=(correction,),
        )
        self.assertTrue(result.planning_allowed)
        self.assertEqual(result.corrections[0].ocr_value, "80")
        self.assertEqual(result.corrections[0].reviewed_value, "80")

    def test_correction_must_reference_observed_ocr_value(self) -> None:
        scenario = build_scenario("low-confidence")
        correction = ReviewedCorrection("character_0.level", "70", "80", "人工核对")
        result = ScanSession(FixtureOcrEngine()).run(
            scenario.scan_frames,
            account_id=uuid4(),
            expected_fingerprint=scenario.account_fingerprint,
            game_version=scenario.game_version,
            corrections=(correction,),
        )
        self.assertFalse(result.planning_allowed)
        self.assertTrue(any("does not match" in issue for issue in result.issues))

    def test_invalid_fixture_json_is_rejected(self) -> None:
        frame = ScanFrame("bad", datetime.now(UTC), 1920, 1080, b"not-json")
        with self.assertRaisesRegex(ValueError, "UTF-8 JSON"):
            FixtureOcrEngine().scan(frame)


if __name__ == "__main__":
    unittest.main()
