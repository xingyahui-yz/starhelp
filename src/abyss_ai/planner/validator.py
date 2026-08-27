from __future__ import annotations

from dataclasses import dataclass

from abyss_ai.domain import (
    AccountSnapshot,
    ActionType,
    BattlePlan,
    ReadinessAssessment,
    ReadinessStatus,
)


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    code: str
    message: str


class PlanValidationError(ValueError):
    def __init__(self, issues: tuple[ValidationIssue, ...]) -> None:
        self.issues = issues
        super().__init__("; ".join(f"{item.code}: {item.message}" for item in issues))


class PlanValidator:
    """Machine validation. Human review is still mandatory after this passes."""

    def validate(
        self,
        plan: BattlePlan,
        snapshot: AccountSnapshot,
        readiness: ReadinessAssessment,
    ) -> tuple[ValidationIssue, ...]:
        issues: list[ValidationIssue] = []

        if plan.account_id != snapshot.account_id or plan.snapshot_id != snapshot.snapshot_id:
            issues.append(ValidationIssue("snapshot_mismatch", "plan does not match account snapshot"))
        if plan.game_version != snapshot.game_version:
            issues.append(ValidationIssue("game_version_mismatch", "plan and snapshot versions differ"))
        if (
            readiness.account_id != plan.account_id
            or readiness.snapshot_id != plan.snapshot_id
            or readiness.stage_id != plan.stage_id
        ):
            issues.append(ValidationIssue("readiness_mismatch", "assessment does not match plan"))
        if readiness.status in {ReadinessStatus.NOT_READY, ReadinessStatus.UNKNOWN}:
            issues.append(ValidationIssue("not_ready", "account is not eligible for execution"))

        all_team_members = plan.upper_team + plan.lower_team
        if len(set(all_team_members)) != 8:
            issues.append(ValidationIssue("duplicate_team_member", "upper and lower teams must be unique"))
        missing = set(all_team_members) - snapshot.character_ids()
        if missing:
            issues.append(
                ValidationIssue("missing_character", f"snapshot does not contain: {sorted(missing)}")
            )
        if not plan.rules:
            issues.append(ValidationIssue("missing_rules", "plan must contain at least one rule"))
        if plan.max_actions <= 0 or plan.max_actions > 150:
            issues.append(ValidationIssue("invalid_action_limit", "max_actions must be 1..150"))
        if plan.max_attempts <= 0 or plan.max_attempts > 2:
            issues.append(ValidationIssue("invalid_attempt_limit", "max_attempts must be 1..2"))

        team = set(all_team_members)
        for rule in plan.rules:
            if rule.action.type not in ActionType:
                issues.append(ValidationIssue("invalid_action", f"invalid action in {rule.rule_id}"))
            if rule.actor and rule.actor not in team:
                issues.append(ValidationIssue("invalid_actor", f"unknown actor in {rule.rule_id}"))
            if rule.action.actor and rule.action.actor not in team:
                issues.append(ValidationIssue("invalid_action_actor", f"unknown actor in {rule.rule_id}"))

        return tuple(issues)

    def validate_or_raise(
        self,
        plan: BattlePlan,
        snapshot: AccountSnapshot,
        readiness: ReadinessAssessment,
    ) -> None:
        issues = self.validate(plan, snapshot, readiness)
        if issues:
            raise PlanValidationError(issues)

