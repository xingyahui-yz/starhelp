import unittest

from abyss_ai.domain import ActionType, BattleState
from abyss_ai.policy import RuleEngine
from tests.helpers import CHARACTERS, make_plan, make_snapshot


class RuleEngineTests(unittest.TestCase):
    def test_matching_actor_and_skill_points_uses_skill(self) -> None:
        plan = make_plan(make_snapshot())
        state = BattleState("battle_turn", 0.99, CHARACTERS[0], 3)
        decision = RuleEngine().decide(plan, state)
        self.assertEqual(decision.action.type, ActionType.SKILL)

    def test_unknown_screen_only_waits(self) -> None:
        plan = make_plan(make_snapshot())
        decision = RuleEngine().decide(plan, BattleState("unknown", 0.99))
        self.assertEqual(decision.action.type, ActionType.WAIT)


if __name__ == "__main__":
    unittest.main()

