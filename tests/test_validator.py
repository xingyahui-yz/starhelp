import unittest
from dataclasses import replace

from abyss_ai.domain import ReadinessStatus
from abyss_ai.planner import PlanValidator
from tests.helpers import CHARACTERS, make_plan, make_readiness, make_snapshot


class PlanValidatorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = make_snapshot()
        self.plan = make_plan(self.snapshot)
        self.validator = PlanValidator()

    def test_valid_plan_has_no_issues(self) -> None:
        self.assertEqual(self.validator.validate(self.plan, self.snapshot, make_readiness(self.snapshot)), ())

    def test_not_ready_plan_is_rejected(self) -> None:
        issues = self.validator.validate(
            self.plan,
            self.snapshot,
            make_readiness(self.snapshot, ReadinessStatus.NOT_READY),
        )
        self.assertIn("not_ready", {issue.code for issue in issues})

    def test_duplicate_character_is_rejected(self) -> None:
        invalid = replace(
            self.plan,
            lower_team=(CHARACTERS[0], CHARACTERS[5], CHARACTERS[6], CHARACTERS[7]),
        )
        issues = self.validator.validate(invalid, self.snapshot, make_readiness(self.snapshot))
        self.assertIn("duplicate_team_member", {issue.code for issue in issues})


if __name__ == "__main__":
    unittest.main()

