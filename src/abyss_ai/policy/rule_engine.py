from __future__ import annotations

from abyss_ai.domain import Action, ActionType, BattlePlan, BattleState, Decision


class RuleEngine:
    """Deterministic offline policy. It never emits raw keys or coordinates."""

    def decide(self, plan: BattlePlan, state: BattleState) -> Decision:
        if state.battle_finished:
            return Decision(Action(ActionType.ABORT, reason="battle finished"), 1.0, "战斗已结束")
        if state.screen != "battle_turn" or state.confidence < 0.90:
            return Decision(Action(ActionType.WAIT, reason="state uncertain"), 1.0, "等待可信战斗状态")

        for rule in sorted(plan.rules, key=lambda item: item.priority, reverse=True):
            if rule.actor is not None and rule.actor != state.active_character:
                continue
            if rule.min_skill_points is not None:
                if state.skill_points is None or state.skill_points < rule.min_skill_points:
                    continue
            return Decision(rule.action, state.confidence, f"命中规则 {rule.rule_id}")

        return Decision(Action(ActionType.WAIT, reason="no matching rule"), 1.0, "没有安全匹配规则")

