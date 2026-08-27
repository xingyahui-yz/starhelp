from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from abyss_ai.domain import (
    Action,
    ActionType,
    BattlePlan,
    ExecutionApproval,
    ReadinessAssessment,
    ReadinessStatus,
)
from abyss_ai.planner import hash_plan


class SafetyViolation(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ExecutionContext:
    active_process: str
    expected_process: str
    screen: str
    state_confidence: float
    game_version_verified: bool
    user_present: bool
    emergency_stop_active: bool = False


@dataclass(frozen=True, slots=True)
class SafetyDecision:
    allowed: bool
    code: str
    reason: str


class SafetyKernel:
    """Final deny-by-default authority for all semantic actions."""

    ALLOWED_SCREENS = frozenset(
        {
            "battle_turn",
            "ultimate_target_selection",
            "memory_of_chaos_team_setup",
        }
    )
    BLOCKED_SCREENS = frozenset(
        {
            "login",
            "payment",
            "shop",
            "warp",
            "resource_confirmation",
            "account_settings",
            "unknown",
        }
    )
    ALLOWED_ACTIONS = frozenset(ActionType)

    def check(
        self,
        action: Action,
        context: ExecutionContext,
        plan: BattlePlan,
        readiness: ReadinessAssessment,
        approval: ExecutionApproval | None,
        *,
        now: datetime | None = None,
    ) -> SafetyDecision:
        current_time = now or datetime.now(UTC)

        if action.type in {ActionType.WAIT, ActionType.ABORT}:
            return SafetyDecision(True, "safe_non_input", "等待和停止不发送游戏输入")
        if context.emergency_stop_active:
            return SafetyDecision(False, "emergency_stop", "紧急停止已触发")
        if not context.user_present:
            return SafetyDecision(False, "user_absent", "当前设计禁止无人值守执行")
        if not context.game_version_verified:
            return SafetyDecision(False, "version_unverified", "游戏版本尚未重新认证")
        if context.active_process != context.expected_process:
            return SafetyDecision(False, "focus_mismatch", "前台进程不是目标游戏")
        if context.screen in self.BLOCKED_SCREENS or context.screen not in self.ALLOWED_SCREENS:
            return SafetyDecision(False, "screen_blocked", "当前页面不允许输入")
        if context.state_confidence < 0.95:
            return SafetyDecision(False, "low_confidence", "状态置信度不足")
        if action.type not in self.ALLOWED_ACTIONS:
            return SafetyDecision(False, "action_blocked", "动作不在白名单")
        if readiness.status in {ReadinessStatus.NOT_READY, ReadinessStatus.UNKNOWN}:
            return SafetyDecision(False, "account_not_ready", "账号未达到最低执行标准")
        if (
            readiness.account_id != plan.account_id
            or readiness.snapshot_id != plan.snapshot_id
            or readiness.stage_id != plan.stage_id
        ):
            return SafetyDecision(False, "readiness_mismatch", "通关评估与方案不一致")
        if approval is None:
            return SafetyDecision(False, "approval_missing", "缺少人工审查授权")
        if approval.used:
            return SafetyDecision(False, "approval_used", "人工授权已经使用")
        if current_time < approval.approved_at or current_time >= approval.expires_at:
            return SafetyDecision(False, "approval_expired", "人工授权尚未生效或已经过期")
        if (
            approval.account_id != plan.account_id
            or approval.snapshot_id != plan.snapshot_id
            or approval.game_version != plan.game_version
            or approval.season_id != plan.season_id
            or approval.stage_id != plan.stage_id
        ):
            return SafetyDecision(False, "approval_context_mismatch", "人工授权上下文不匹配")
        if approval.plan_hash != hash_plan(plan):
            return SafetyDecision(False, "plan_changed", "人工审查后方案已经变化")

        return SafetyDecision(True, "authorized", "安全检查和人工授权均有效")

    def authorize_or_raise(
        self,
        action: Action,
        context: ExecutionContext,
        plan: BattlePlan,
        readiness: ReadinessAssessment,
        approval: ExecutionApproval | None,
        *,
        now: datetime | None = None,
    ) -> None:
        decision = self.check(action, context, plan, readiness, approval, now=now)
        if not decision.allowed:
            raise SafetyViolation(f"{decision.code}: {decision.reason}")

