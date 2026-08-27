import unittest

from abyss_ai.domain import ReadinessStatus
from abyss_ai.planner import ReadinessAssessor
from tests.helpers import make_snapshot


class ReadinessTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = make_snapshot()
        self.assessor = ReadinessAssessor()

    def test_ready_when_both_halves_and_survival_pass(self) -> None:
        result = self.assessor.assess(
            self.snapshot,
            "moc-12",
            upper_score=0.8,
            lower_score=0.77,
            survival_score=0.8,
            confidence=0.98,
        )
        self.assertEqual(result.status, ReadinessStatus.READY)

    def test_unknown_when_scan_confidence_is_low(self) -> None:
        result = self.assessor.assess(
            self.snapshot,
            "moc-12",
            upper_score=0.8,
            lower_score=0.8,
            survival_score=0.8,
            confidence=0.7,
        )
        self.assertEqual(result.status, ReadinessStatus.UNKNOWN)
        plan = self.assessor.cultivation_plan(self.snapshot, result)
        self.assertEqual(plan.steps[0].category, "data_quality")

    def test_blocking_gap_generates_cultivation_step(self) -> None:
        result = self.assessor.assess(
            self.snapshot,
            "moc-12",
            upper_score=0.8,
            lower_score=0.8,
            survival_score=0.8,
            confidence=0.98,
            blocking_gaps=("下半生存位等级不足",),
        )
        self.assertEqual(result.status, ReadinessStatus.NOT_READY)
        plan = self.assessor.cultivation_plan(self.snapshot, result)
        self.assertIn("生存位", plan.steps[0].reason)


if __name__ == "__main__":
    unittest.main()

