import unittest
from datetime import UTC, datetime

from abyss_ai.account_scan import ScanPage, ScanReconciler, ScanResult
from abyss_ai.replay import ReplayRecorder
from abyss_ai.research import SourceRecord, SourceRegistry, SourceTier


class AccountScanFrameworkTests(unittest.TestCase):
    def test_conflicting_ocr_pages_require_review(self) -> None:
        results = (
            ScanResult(ScanPage.CHARACTER_STATS, "hero", (("speed", "134", 0.99),), 0.99),
            ScanResult(ScanPage.RELICS, "hero", (("speed", "135", 0.96),), 0.99),
        )
        merged = ScanReconciler().reconcile(results)
        self.assertTrue(merged.needs_review)
        self.assertIn(("speed", "134", 0.99), merged.fields)

    def test_pages_from_different_characters_are_rejected(self) -> None:
        results = (
            ScanResult(ScanPage.CHARACTER_STATS, "hero-a", (), 0.99),
            ScanResult(ScanPage.RELICS, "hero-b", (), 0.99),
        )
        with self.assertRaisesRegex(ValueError, "one character"):
            ScanReconciler().reconcile(results)


class ResearchFrameworkTests(unittest.TestCase):
    def test_discovery_only_source_cannot_supply_facts(self) -> None:
        registry = SourceRegistry()
        registry.register(
            SourceRecord(
                "community-post",
                "https://example.invalid/post",
                SourceTier.DISCOVERY_ONLY,
                "4.4",
                datetime.now(UTC),
                "hash-1",
            )
        )
        self.assertEqual(registry.facts_for_version("4.4"), ())

    def test_changed_source_requires_explicit_review(self) -> None:
        registry = SourceRegistry()
        first = SourceRecord(
            "official",
            "https://example.invalid/official",
            SourceTier.OFFICIAL,
            "4.4",
            datetime.now(UTC),
            "hash-1",
        )
        registry.register(first)
        with self.assertRaisesRegex(ValueError, "explicit review"):
            registry.register(
                SourceRecord(
                    "official",
                    first.url,
                    first.tier,
                    first.game_version,
                    datetime.now(UTC),
                    "hash-2",
                )
            )


class ReplayFrameworkTests(unittest.TestCase):
    def test_sensitive_fields_are_rejected(self) -> None:
        recorder = ReplayRecorder()
        with self.assertRaisesRegex(ValueError, "sensitive"):
            recorder.record("observation", {"uid": "123456789"})

    def test_nested_sensitive_fields_are_rejected(self) -> None:
        recorder = ReplayRecorder()
        with self.assertRaisesRegex(ValueError, "sensitive"):
            recorder.record("observation", {"metadata": {"access_token": "secret"}})

    def test_safe_event_is_recorded(self) -> None:
        recorder = ReplayRecorder()
        recorder.record("decision", {"action": "wait", "confidence": 0.99})
        self.assertEqual(len(recorder.events()), 1)


if __name__ == "__main__":
    unittest.main()
