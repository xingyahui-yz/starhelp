from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

from abyss_ai.domain import (
    AccountSnapshot,
    Action,
    ActionType,
    BattlePlan,
    CharacterBuild,
    ExecutionApproval,
    PolicyRule,
    ReadinessAssessment,
    ReadinessStatus,
    ScannedField,
)
from abyss_ai.planner import hash_plan

CHARACTERS = tuple(f"character_{index}" for index in range(8))


def scanned(value, confidence: float = 0.99, *, needs_review: bool = False):
    return ScannedField(value, confidence, "fixture", needs_review=needs_review)


def make_snapshot(
    account_id: UUID | None = None,
    snapshot_id: UUID | None = None,
) -> AccountSnapshot:
    account = account_id or uuid4()
    return AccountSnapshot(
        snapshot_id=snapshot_id or uuid4(),
        account_id=account,
        game_version="4.4",
        characters=tuple(
            CharacterBuild(account, character_id, scanned(80), scanned(0))
            for character_id in CHARACTERS
        ),
    )


def make_plan(snapshot: AccountSnapshot) -> BattlePlan:
    return BattlePlan(
        account_id=snapshot.account_id,
        snapshot_id=snapshot.snapshot_id,
        game_version=snapshot.game_version,
        season_id="season-1",
        stage_id="moc-12",
        upper_team=CHARACTERS[:4],
        lower_team=CHARACTERS[4:],
        rules=(
            PolicyRule(
                "use-skill",
                100,
                CHARACTERS[0],
                1,
                Action(ActionType.SKILL, actor=CHARACTERS[0], target="main_enemy"),
            ),
            PolicyRule(
                "fallback-basic",
                10,
                None,
                None,
                Action(ActionType.BASIC_ATTACK, target="main_enemy"),
            ),
        ),
    )


def make_readiness(
    snapshot: AccountSnapshot,
    status: ReadinessStatus = ReadinessStatus.READY,
) -> ReadinessAssessment:
    return ReadinessAssessment(
        account_id=snapshot.account_id,
        snapshot_id=snapshot.snapshot_id,
        stage_id="moc-12",
        status=status,
        upper_score=0.8,
        lower_score=0.8,
        survival_score=0.8,
        confidence=0.98,
    )


def make_approval(plan: BattlePlan, *, used: bool = False) -> ExecutionApproval:
    now = datetime.now(UTC)
    return ExecutionApproval(
        approval_id=uuid4(),
        plan_hash=hash_plan(plan),
        account_id=plan.account_id,
        snapshot_id=plan.snapshot_id,
        game_version=plan.game_version,
        season_id=plan.season_id,
        stage_id=plan.stage_id,
        approved_at=now - timedelta(seconds=1),
        expires_at=now + timedelta(minutes=10),
        used=used,
    )

