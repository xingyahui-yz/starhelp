from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Generic, TypeVar
from uuid import UUID

T = TypeVar("T")


class ActionType(StrEnum):
    BASIC_ATTACK = "basic_attack"
    SKILL = "skill"
    ULTIMATE = "ultimate"
    SELECT_TARGET_LEFT = "select_target_left"
    SELECT_TARGET_RIGHT = "select_target_right"
    CONFIRM_BATTLE = "confirm_battle"
    WAIT = "wait"
    ABORT = "abort"


class ReadinessStatus(StrEnum):
    READY = "ready"
    MARGINAL = "marginal"
    NOT_READY = "not_ready"
    UNKNOWN = "unknown"


class RelicSlot(StrEnum):
    HEAD = "head"
    HANDS = "hands"
    BODY = "body"
    FEET = "feet"
    PLANAR_SPHERE = "planar_sphere"
    LINK_ROPE = "link_rope"


@dataclass(frozen=True, slots=True)
class ScannedField(Generic[T]):
    value: T | None
    confidence: float
    source_region: str
    captured_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    needs_review: bool = False

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.value is None and not self.needs_review:
            raise ValueError("missing scanned value must require review")


@dataclass(frozen=True, slots=True)
class StatValue:
    name: str
    value: float
    unit: str = "flat"


@dataclass(frozen=True, slots=True)
class EquippedLightCone:
    account_id: UUID
    light_cone_id: str
    level: ScannedField[int]
    superimposition: ScannedField[int]


@dataclass(frozen=True, slots=True)
class EquippedRelic:
    account_id: UUID
    owner_character_id: str
    slot: RelicSlot
    set_id: ScannedField[str]
    level: ScannedField[int]
    main_stat: ScannedField[StatValue]
    sub_stats: tuple[ScannedField[StatValue], ...] = ()


@dataclass(frozen=True, slots=True)
class CharacterBuild:
    account_id: UUID
    character_id: str
    level: ScannedField[int]
    eidolon: ScannedField[int]
    traces: tuple[ScannedField[int], ...] = ()
    light_cone: EquippedLightCone | None = None
    relics: tuple[EquippedRelic, ...] = ()
    stats: tuple[ScannedField[StatValue], ...] = ()

    def __post_init__(self) -> None:
        if self.light_cone and self.light_cone.account_id != self.account_id:
            raise ValueError("light cone belongs to another account")
        slots: set[RelicSlot] = set()
        for relic in self.relics:
            if relic.account_id != self.account_id:
                raise ValueError("relic belongs to another account")
            if relic.owner_character_id != self.character_id:
                raise ValueError("relic owner does not match character")
            if relic.slot in slots:
                raise ValueError(f"duplicate relic slot: {relic.slot}")
            slots.add(relic.slot)

    @property
    def needs_review(self) -> bool:
        fields: list[ScannedField[object]] = [self.level, self.eidolon]
        fields.extend(self.traces)
        fields.extend(self.stats)
        if self.light_cone:
            fields.extend((self.light_cone.level, self.light_cone.superimposition))
        for relic in self.relics:
            fields.extend((relic.set_id, relic.level, relic.main_stat, *relic.sub_stats))
        return any(item.needs_review for item in fields)


@dataclass(frozen=True, slots=True)
class AccountProfile:
    account_id: UUID
    display_label: str
    uid_fingerprint: str | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    snapshot_id: UUID
    account_id: UUID
    game_version: str
    characters: tuple[CharacterBuild, ...]
    scanned_at: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        ids: set[str] = set()
        for character in self.characters:
            if character.account_id != self.account_id:
                raise ValueError("character belongs to another account")
            if character.character_id in ids:
                raise ValueError(f"duplicate character: {character.character_id}")
            ids.add(character.character_id)

    def character_ids(self) -> frozenset[str]:
        return frozenset(character.character_id for character in self.characters)


@dataclass(frozen=True, slots=True)
class Action:
    type: ActionType
    actor: str | None = None
    target: str | None = None
    reason: str = ""
    source_rule_id: str = ""


@dataclass(frozen=True, slots=True)
class BattleState:
    screen: str
    confidence: float
    active_character: str | None = None
    skill_points: int | None = None
    ultimate_ready: frozenset[str] = frozenset()
    selected_target: int | None = None
    enemy_count: int | None = None
    battle_finished: bool = False
    timestamp: datetime = field(default_factory=lambda: datetime.now(UTC))

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")
        if self.skill_points is not None and not 0 <= self.skill_points <= 7:
            raise ValueError("skill points are outside supported range")


@dataclass(frozen=True, slots=True)
class PolicyRule:
    rule_id: str
    priority: int
    actor: str | None
    min_skill_points: int | None
    action: Action


@dataclass(frozen=True, slots=True)
class BattlePlan:
    account_id: UUID
    snapshot_id: UUID
    game_version: str
    season_id: str
    stage_id: str
    upper_team: tuple[str, str, str, str]
    lower_team: tuple[str, str, str, str]
    rules: tuple[PolicyRule, ...]
    max_actions: int = 150
    max_attempts: int = 2


@dataclass(frozen=True, slots=True)
class ReadinessAssessment:
    account_id: UUID
    snapshot_id: UUID
    stage_id: str
    status: ReadinessStatus
    upper_score: float
    lower_score: float
    survival_score: float
    confidence: float
    blocking_gaps: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be between 0 and 1")


@dataclass(frozen=True, slots=True)
class CultivationStep:
    priority: int
    character_id: str
    category: str
    current_value: str
    target_value: str
    expected_improvement: str
    reason: str
    estimated_cost: str | None = None


@dataclass(frozen=True, slots=True)
class CultivationPlan:
    account_id: UUID
    source_snapshot_id: UUID
    target_stage_id: str
    steps: tuple[CultivationStep, ...]
    alternative_teams: tuple[tuple[str, str, str, str], ...] = ()
    reassessment_conditions: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class ExecutionApproval:
    approval_id: UUID
    plan_hash: str
    account_id: UUID
    snapshot_id: UUID
    game_version: str
    season_id: str
    stage_id: str
    approved_at: datetime
    expires_at: datetime
    used: bool = False


@dataclass(frozen=True, slots=True)
class Decision:
    action: Action
    confidence: float
    explanation: str
    alternatives: tuple[Action, ...] = ()

