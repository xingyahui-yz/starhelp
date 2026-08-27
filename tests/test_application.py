import unittest

from abyss_ai.application import PlanningService
from abyss_ai.domain import ReadinessStatus
from tests.helpers import make_plan, make_readiness, make_snapshot


class PlanningServiceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = make_snapshot()
        self.plan = make_plan(self.snapshot)
        self.service = PlanningService()

    def test_ready_plan_still_requires_human_review(self) -> None:
        result = self.service.prepare(
            self.plan, self.snapshot, make_readiness(self.snapshot)
        )
        self.assertTrue(result.executable_candidate)
        self.assertTrue(result.requires_human_review)
        self.assertIsNotNone(result.plan_hash)

    def test_not_ready_plan_returns_cultivation_instead_of_execution(self) -> None:
        readiness = make_readiness(self.snapshot, ReadinessStatus.NOT_READY)
        result = self.service.prepare(self.plan, self.snapshot, readiness)
        self.assertFalse(result.executable_candidate)
        self.assertFalse(result.requires_human_review)
        self.assertIsNotNone(result.cultivation_plan)


if __name__ == "__main__":
    unittest.main()

