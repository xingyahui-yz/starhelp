import unittest
from dataclasses import replace
from datetime import UTC, datetime, timedelta

from abyss_ai.domain import Action, ActionType, ReadinessStatus
from abyss_ai.execution import ApprovalLedger, RecordingInputBackend, SafeActionExecutor
from abyss_ai.safety import ExecutionContext, SafetyKernel, SafetyViolation
from tests.helpers import make_approval, make_plan, make_readiness, make_snapshot


class SafetyKernelTests(unittest.TestCase):
    def setUp(self) -> None:
        self.snapshot = make_snapshot()
        self.plan = make_plan(self.snapshot)
        self.readiness = make_readiness(self.snapshot)
        self.approval = make_approval(self.plan)
        self.context = ExecutionContext(
            active_process="StarRail.exe",
            expected_process="StarRail.exe",
            screen="battle_turn",
            state_confidence=0.99,
            game_version_verified=True,
            user_present=True,
        )
        self.action = Action(ActionType.BASIC_ATTACK, target="main_enemy")
        self.kernel = SafetyKernel()

    def test_allows_fully_reviewed_action(self) -> None:
        decision = self.kernel.check(
            self.action, self.context, self.plan, self.readiness, self.approval
        )
        self.assertTrue(decision.allowed)

    def test_rejects_missing_human_approval(self) -> None:
        decision = self.kernel.check(self.action, self.context, self.plan, self.readiness, None)
        self.assertEqual(decision.code, "approval_missing")

    def test_rejects_not_ready_account(self) -> None:
        readiness = make_readiness(self.snapshot, ReadinessStatus.NOT_READY)
        decision = self.kernel.check(
            self.action, self.context, self.plan, readiness, self.approval
        )
        self.assertEqual(decision.code, "account_not_ready")

    def test_rejects_wrong_foreground_process(self) -> None:
        context = replace(self.context, active_process="notepad.exe")
        decision = self.kernel.check(
            self.action, context, self.plan, self.readiness, self.approval
        )
        self.assertEqual(decision.code, "focus_mismatch")

    def test_rejects_blocked_screen(self) -> None:
        context = replace(self.context, screen="payment")
        decision = self.kernel.check(
            self.action, context, self.plan, self.readiness, self.approval
        )
        self.assertEqual(decision.code, "screen_blocked")

    def test_rejects_unverified_game_version(self) -> None:
        context = replace(self.context, game_version_verified=False)
        decision = self.kernel.check(
            self.action, context, self.plan, self.readiness, self.approval
        )
        self.assertEqual(decision.code, "version_unverified")

    def test_rejects_emergency_stop(self) -> None:
        context = replace(self.context, emergency_stop_active=True)
        decision = self.kernel.check(
            self.action, context, self.plan, self.readiness, self.approval
        )
        self.assertEqual(decision.code, "emergency_stop")

    def test_rejects_expired_approval(self) -> None:
        now = datetime.now(UTC)
        approval = replace(
            self.approval,
            approved_at=now - timedelta(minutes=20),
            expires_at=now - timedelta(minutes=10),
        )
        decision = self.kernel.check(
            self.action, self.context, self.plan, self.readiness, approval, now=now
        )
        self.assertEqual(decision.code, "approval_expired")

    def test_rejects_plan_changed_after_review(self) -> None:
        changed = replace(self.plan, max_actions=self.plan.max_actions - 1)
        decision = self.kernel.check(
            self.action, self.context, changed, self.readiness, self.approval
        )
        self.assertEqual(decision.code, "plan_changed")

    def test_wait_is_always_safe_and_sends_no_game_input_requirement(self) -> None:
        unsafe_context = replace(
            self.context,
            active_process="notepad.exe",
            screen="payment",
            game_version_verified=False,
        )
        decision = self.kernel.check(
            Action(ActionType.WAIT), unsafe_context, self.plan, self.readiness, None
        )
        self.assertTrue(decision.allowed)

    def test_recording_backend_only_receives_authorized_action(self) -> None:
        backend = RecordingInputBackend()
        ledger = ApprovalLedger()
        executor = SafeActionExecutor(self.kernel, backend, ledger)
        executor.execute(
            self.action, self.context, self.plan, self.readiness, self.approval
        )
        self.assertEqual(backend.actions, [self.action])

        with self.assertRaises(SafetyViolation):
            executor.execute(self.action, replace(self.context, screen="shop"), self.plan, self.readiness, self.approval)
        self.assertEqual(backend.actions, [self.action])

        second_executor = SafeActionExecutor(self.kernel, RecordingInputBackend(), ledger)
        with self.assertRaisesRegex(SafetyViolation, "approval_used"):
            second_executor.execute(
                self.action, self.context, self.plan, self.readiness, self.approval
            )

    def test_non_input_action_is_not_forwarded_to_backend(self) -> None:
        backend = RecordingInputBackend()
        executor = SafeActionExecutor(self.kernel, backend)
        executor.execute(
            Action(ActionType.WAIT), self.context, self.plan, self.readiness, None
        )
        self.assertEqual(backend.actions, [])

    def test_action_limit_is_enforced(self) -> None:
        backend = RecordingInputBackend()
        plan = replace(self.plan, max_actions=1)
        approval = make_approval(plan)
        executor = SafeActionExecutor(self.kernel, backend)
        executor.execute(self.action, self.context, plan, self.readiness, approval)
        with self.assertRaisesRegex(SafetyViolation, "action_limit"):
            executor.execute(self.action, self.context, plan, self.readiness, approval)


if __name__ == "__main__":
    unittest.main()
