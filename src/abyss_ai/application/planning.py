from __future__ import annotations

from dataclasses import dataclass

from abyss_ai.domain import (
    AccountSnapshot,
    BattlePlan,
    CultivationPlan,
    ReadinessAssessment,
    ReadinessStatus,
)
from abyss_ai.planner import PlanValidator, ReadinessAssessor, ValidationIssue, hash_plan


@dataclass(frozen=True, slots=True)
class PlanPreparation:
    executable_candidate: bool
    requires_human_review: bool
    plan_hash: str | None
    issues: tuple[ValidationIssue, ...]
    cultivation_plan: CultivationPlan | None


class PlanningService:
    """Application boundary between account assessment and mandatory human review."""

    def __init__(
        self,
        validator: PlanValidator | None = None,
        assessor: ReadinessAssessor | None = None,
    ) -> None:
        self.validator = validator or PlanValidator()
        self.assessor = assessor or ReadinessAssessor()

    def prepare(
        self,
        plan: BattlePlan,
        snapshot: AccountSnapshot,
        readiness: ReadinessAssessment,
    ) -> PlanPreparation:
        issues = self.validator.validate(plan, snapshot, readiness)
        if readiness.status in {ReadinessStatus.NOT_READY, ReadinessStatus.UNKNOWN}:
            cultivation = self.assessor.cultivation_plan(snapshot, readiness)
            return PlanPreparation(False, False, None, issues, cultivation)
        if issues:
            return PlanPreparation(False, False, None, issues, None)
        return PlanPreparation(True, True, hash_plan(plan), (), None)

