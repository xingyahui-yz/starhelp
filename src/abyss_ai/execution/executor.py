from __future__ import annotations

from uuid import UUID

from abyss_ai.domain import (
    Action,
    ActionType,
    BattlePlan,
    ExecutionApproval,
    ReadinessAssessment,
)
from abyss_ai.execution.backend import InputBackend
from abyss_ai.safety import ExecutionContext, SafetyKernel, SafetyViolation


class ApprovalLedger:
    """Process-local ledger. A persistent implementation can replace it later."""

    def __init__(self) -> None:
        self._consumed: set[UUID] = set()

    def is_consumed(self, approval_id: UUID) -> bool:
        return approval_id in self._consumed

    def consume(self, approval_id: UUID) -> None:
        if self.is_consumed(approval_id):
            raise SafetyViolation("approval_used: 人工授权已经用于启动其他执行会话")
        self._consumed.add(approval_id)


class SafeActionExecutor:
    def __init__(
        self,
        safety: SafetyKernel,
        backend: InputBackend,
        ledger: ApprovalLedger | None = None,
    ) -> None:
        self.safety = safety
        self.backend = backend
        self.ledger = ledger or ApprovalLedger()
        self._active_approval_id: UUID | None = None
        self._action_count = 0

    def execute(
        self,
        action: Action,
        context: ExecutionContext,
        plan: BattlePlan,
        readiness: ReadinessAssessment,
        approval: ExecutionApproval | None,
    ) -> None:
        if action.type in {ActionType.WAIT, ActionType.ABORT}:
            return
        if approval is None:
            self.safety.authorize_or_raise(action, context, plan, readiness, None)
            return
        if self._active_approval_id is None and self.ledger.is_consumed(approval.approval_id):
            raise SafetyViolation("approval_used: 人工授权已经用于启动其他执行会话")
        if self._active_approval_id not in {None, approval.approval_id}:
            raise SafetyViolation("approval_changed: 执行会话中不得切换人工授权")
        if self._action_count >= plan.max_actions:
            raise SafetyViolation("action_limit: 已达到方案最大动作数")

        self.safety.authorize_or_raise(action, context, plan, readiness, approval)

        if self._active_approval_id is None:
            self.ledger.consume(approval.approval_id)
            self._active_approval_id = approval.approval_id
        self.backend.send(action)
        self._action_count += 1
