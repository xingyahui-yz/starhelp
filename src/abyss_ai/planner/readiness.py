from __future__ import annotations

from dataclasses import dataclass

from abyss_ai.domain import (
    AccountSnapshot,
    CultivationPlan,
    CultivationStep,
    ReadinessAssessment,
    ReadinessStatus,
)


@dataclass(frozen=True, slots=True)
class ReadinessThresholds:
    ready_team_score: float = 0.75
    marginal_team_score: float = 0.62
    minimum_survival: float = 0.65
    minimum_confidence: float = 0.90


class ReadinessAssessor:
    def __init__(self, thresholds: ReadinessThresholds | None = None) -> None:
        self.thresholds = thresholds or ReadinessThresholds()

    def assess(
        self,
        snapshot: AccountSnapshot,
        stage_id: str,
        *,
        upper_score: float,
        lower_score: float,
        survival_score: float,
        confidence: float,
        blocking_gaps: tuple[str, ...] = (),
    ) -> ReadinessAssessment:
        values = (upper_score, lower_score, survival_score, confidence)
        if any(not 0.0 <= value <= 1.0 for value in values):
            raise ValueError("readiness inputs must be between 0 and 1")

        weakest_team = min(upper_score, lower_score)
        if confidence < self.thresholds.minimum_confidence:
            status = ReadinessStatus.UNKNOWN
        elif blocking_gaps or survival_score < self.thresholds.minimum_survival:
            status = ReadinessStatus.NOT_READY
        elif weakest_team >= self.thresholds.ready_team_score:
            status = ReadinessStatus.READY
        elif weakest_team >= self.thresholds.marginal_team_score:
            status = ReadinessStatus.MARGINAL
        else:
            status = ReadinessStatus.NOT_READY

        return ReadinessAssessment(
            account_id=snapshot.account_id,
            snapshot_id=snapshot.snapshot_id,
            stage_id=stage_id,
            status=status,
            upper_score=upper_score,
            lower_score=lower_score,
            survival_score=survival_score,
            confidence=confidence,
            blocking_gaps=blocking_gaps,
        )

    def cultivation_plan(
        self,
        snapshot: AccountSnapshot,
        assessment: ReadinessAssessment,
    ) -> CultivationPlan:
        if assessment.account_id != snapshot.account_id or assessment.snapshot_id != snapshot.snapshot_id:
            raise ValueError("assessment does not match snapshot")
        if assessment.status in {ReadinessStatus.READY, ReadinessStatus.MARGINAL}:
            raise ValueError("cultivation plan is only required for not-ready or unknown accounts")

        steps: list[CultivationStep] = []
        for index, gap in enumerate(assessment.blocking_gaps, start=1):
            steps.append(
                CultivationStep(
                    priority=0,
                    character_id="account",
                    category="blocking_gap",
                    current_value="未满足",
                    target_value="满足最低通关条件",
                    expected_improvement="解除明确阻塞项",
                    reason=gap,
                    estimated_cost="需结合最新材料数据计算",
                )
            )
        if assessment.status is ReadinessStatus.UNKNOWN:
            steps.insert(
                0,
                CultivationStep(
                    priority=0,
                    character_id="account",
                    category="data_quality",
                    current_value=f"识别置信度 {assessment.confidence:.0%}",
                    target_value=f"至少 {self.thresholds.minimum_confidence:.0%}",
                    expected_improvement="获得可信的通关评估",
                    reason="账号扫描或关卡数据置信度不足",
                    estimated_cost="重新 OCR 扫描，无游戏资源消耗",
                ),
            )
        if not steps:
            weakest = "上半" if assessment.upper_score <= assessment.lower_score else "下半"
            steps.append(
                CultivationStep(
                    priority=0,
                    character_id="account",
                    category="team_strength",
                    current_value=f"{weakest}评分不足",
                    target_value=f"队伍评分至少 {self.thresholds.marginal_team_score:.0%}",
                    expected_improvement="达到最低理论可行区间",
                    reason="优先提升较弱一侧，避免资源投入到非短板",
                    estimated_cost="由角色构筑差距分析器细化",
                )
            )

        return CultivationPlan(
            account_id=snapshot.account_id,
            source_snapshot_id=snapshot.snapshot_id,
            target_stage_id=assessment.stage_id,
            steps=tuple(steps),
            reassessment_conditions=("完成任一 P0 项后重新 OCR 扫描",),
        )

