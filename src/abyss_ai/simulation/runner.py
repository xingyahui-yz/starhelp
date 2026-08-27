from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid5

from abyss_ai.account_scan import FixtureOcrEngine, ScanFrame, ScanPage, ScanSession
from abyss_ai.application import PlanningService
from abyss_ai.domain import (
    AccountSnapshot,
    Action,
    ActionType,
    BattlePlan,
    BattleState,
    CultivationPlan,
    ExecutionApproval,
    PolicyRule,
    ReadinessAssessment,
    RelicSlot,
)
from abyss_ai.execution import RecordingInputBackend, SafeActionExecutor
from abyss_ai.planner import ReadinessAssessor
from abyss_ai.policy import RuleEngine
from abyss_ai.replay import ReplayRecorder
from abyss_ai.safety import ExecutionContext, SafetyKernel, SafetyViolation


@dataclass(frozen=True, slots=True)
class SimulationScenario:
    name: str
    account_fingerprint: str
    game_version: str
    stage_id: str
    scan_frames: tuple[ScanFrame, ...]
    battle_states: tuple[BattleState, ...]
    expected_result: str


@dataclass(frozen=True, slots=True)
class PreparedSimulation:
    scenario: SimulationScenario
    snapshot: AccountSnapshot | None
    readiness: ReadinessAssessment | None
    plan: BattlePlan | None
    cultivation_plan: CultivationPlan | None
    plan_hash: str | None
    review_items: tuple[str, ...]
    issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SimulationReport:
    scenario: str
    final_status: str
    readiness_status: str | None
    plan_hash: str | None
    approval_status: str
    recorded_actions: tuple[str, ...]
    stop_reason: str | None
    replay_events: int
    cultivation_steps: int
    real_input_backend: bool = False


def _field(value: object, confidence: float = 0.99) -> dict[str, object]:
    return {"value": value, "confidence": confidence}


def _frame(
    name: str,
    character_id: str,
    page: ScanPage,
    fingerprint: str,
    fields: dict[str, dict[str, object]],
    *,
    confidence: float = 0.99,
) -> ScanFrame:
    payload = {
        "page": page.value,
        "character_id": character_id,
        "account_fingerprint": fingerprint,
        "confidence": confidence,
        "fields": fields,
    }
    return ScanFrame(
        name,
        datetime(2026, 8, 27, tzinfo=UTC),
        1920,
        1080,
        json.dumps(payload, sort_keys=True).encode("utf-8"),
    )


def build_scenario(name: str) -> SimulationScenario:
    supported = {"ready", "not-ready", "low-confidence", "ocr-conflict", "unsafe-screen"}
    if name not in supported:
        raise ValueError(f"unknown simulation scenario: {name}")
    fingerprint = "fixture-account-a"
    frames: list[ScanFrame] = []
    low_confidence = name == "low-confidence"
    for index in range(8):
        character = f"character_{index}"
        frames.extend(
            (
                _frame(
                    f"{character}-stats",
                    character,
                    ScanPage.CHARACTER_STATS,
                    fingerprint,
                    {
                        "level": _field(80, 0.70 if low_confidence and index == 0 else 0.99),
                        "speed": _field(134),
                    },
                ),
                _frame(
                    f"{character}-cone",
                    character,
                    ScanPage.LIGHT_CONE,
                    fingerprint,
                    {
                        "light_cone_id": _field(f"cone_{index}"),
                        "light_cone_level": _field(80),
                        "superimposition": _field(1),
                    },
                ),
                _frame(
                    f"{character}-relics",
                    character,
                    ScanPage.RELICS,
                    fingerprint,
                    {
                        **{f"relic_{slot.value}_set": _field("fixture_set") for slot in RelicSlot},
                        **{f"relic_{slot.value}_level": _field(15) for slot in RelicSlot},
                    },
                ),
                _frame(
                    f"{character}-traces",
                    character,
                    ScanPage.TRACES,
                    fingerprint,
                    {"trace_basic": _field(6)},
                ),
                _frame(
                    f"{character}-eidolons",
                    character,
                    ScanPage.EIDOLONS,
                    fingerprint,
                    {"eidolon": _field(0)},
                ),
            )
        )
    if name == "ocr-conflict":
        frames.append(
            _frame(
                "character-0-conflicting-stats",
                "character_0",
                ScanPage.CHARACTER_STATS,
                fingerprint,
                {"level": _field(70), "speed": _field(134)},
            )
        )
    screen = "payment" if name == "unsafe-screen" else "battle_turn"
    states = (
        BattleState(screen, 0.99, "character_0", 3),
        BattleState("battle_turn", 0.99, "character_1", 2),
        BattleState("battle_turn", 0.99, battle_finished=True),
    )
    expected = {
        "ready": "completed",
        "not-ready": "cultivation_required",
        "low-confidence": "scan_review_required",
        "ocr-conflict": "scan_review_required",
        "unsafe-screen": "blocked",
    }[name]
    return SimulationScenario(name, fingerprint, "4.4", "moc-12", tuple(frames), states, expected)


class SimulationRunner:
    ACCOUNT_NAMESPACE = UUID("00f98d72-e08c-43c9-a0aa-a8a9a9cb28a2")

    def __init__(self) -> None:
        self.scan_session = ScanSession(FixtureOcrEngine())
        self.assessor = ReadinessAssessor()
        self.planning = PlanningService(assessor=self.assessor)

    def prepare(self, scenario: SimulationScenario) -> PreparedSimulation:
        account_id = uuid5(self.ACCOUNT_NAMESPACE, scenario.account_fingerprint)
        scan = self.scan_session.run(
            scenario.scan_frames,
            account_id=account_id,
            expected_fingerprint=scenario.account_fingerprint,
            game_version=scenario.game_version,
        )
        if not scan.planning_allowed or scan.snapshot is None:
            return PreparedSimulation(
                scenario,
                None,
                None,
                None,
                None,
                None,
                tuple(item.field_path for item in scan.review_items),
                scan.issues,
            )
        snapshot = scan.snapshot
        if scenario.name == "not-ready":
            scores = (0.55, 0.50, 0.52, 0.98, ("下半生存能力低于最低线",))
        else:
            scores = (0.82, 0.80, 0.78, 0.98, ())
        readiness = self.assessor.assess(
            snapshot,
            scenario.stage_id,
            upper_score=scores[0],
            lower_score=scores[1],
            survival_score=scores[2],
            confidence=scores[3],
            blocking_gaps=scores[4],
        )
        ids = tuple(character.character_id for character in snapshot.characters)
        plan = BattlePlan(
            snapshot.account_id,
            snapshot.snapshot_id,
            snapshot.game_version,
            "fixture-season",
            scenario.stage_id,
            ids[:4],
            ids[4:8],
            (
                PolicyRule(
                    "fixture-skill",
                    100,
                    ids[0],
                    1,
                    Action(ActionType.SKILL, actor=ids[0], target="main_enemy"),
                ),
                PolicyRule(
                    "fixture-basic",
                    10,
                    None,
                    None,
                    Action(ActionType.BASIC_ATTACK, target="main_enemy"),
                ),
            ),
            max_actions=10,
            max_attempts=1,
        )
        preparation = self.planning.prepare(plan, snapshot, readiness)
        return PreparedSimulation(
            scenario,
            snapshot,
            readiness,
            plan if preparation.executable_candidate else None,
            preparation.cultivation_plan,
            preparation.plan_hash,
            (),
            tuple(issue.message for issue in preparation.issues),
        )

    def issue_simulation_approval(self, prepared: PreparedSimulation) -> ExecutionApproval:
        if prepared.plan is None or prepared.plan_hash is None:
            raise ValueError("simulation is not eligible for approval")
        now = datetime.now(UTC)
        plan = prepared.plan
        return ExecutionApproval(
            uuid5(plan.snapshot_id, "simulation-approval"),
            prepared.plan_hash,
            plan.account_id,
            plan.snapshot_id,
            plan.game_version,
            plan.season_id,
            plan.stage_id,
            now - timedelta(seconds=1),
            now + timedelta(minutes=10),
        )

    def run(
        self,
        scenario: SimulationScenario,
        approval: ExecutionApproval | None = None,
    ) -> SimulationReport:
        replay = ReplayRecorder()
        replay.record("scan_started", {"scenario": scenario.name, "frames": len(scenario.scan_frames)})
        prepared = self.prepare(scenario)
        if prepared.snapshot is None:
            replay.record(
                "scan_blocked",
                {"reviews": len(prepared.review_items), "issues": len(prepared.issues)},
            )
            return self._report(
                prepared,
                "scan_review_required",
                "not_eligible",
                (),
                "scan_requires_review",
                replay,
            )
        assert prepared.readiness is not None
        replay.record("readiness", {"status": prepared.readiness.status.value})
        if prepared.plan is None:
            replay.record("planning_blocked", {"reason": "cultivation_required"})
            return self._report(
                prepared,
                "cultivation_required",
                "not_eligible",
                (),
                "account_not_ready",
                replay,
            )
        replay.record("plan_validated", {"plan_hash": prepared.plan_hash or ""})
        if approval is None:
            replay.record("review_required", {"plan_hash": prepared.plan_hash or ""})
            return self._report(prepared, "review_required", "missing", (), "human_review_required", replay)

        backend = RecordingInputBackend()
        safety = SafetyKernel()
        executor = SafeActionExecutor(safety, backend)
        policy = RuleEngine()
        previous: BattleState | None = None
        for state in scenario.battle_states:
            replay.record("observation", {"screen": state.screen, "confidence": state.confidence})
            if state.battle_finished:
                replay.record("finished", {"result": "completed"})
                return self._report(prepared, "completed", "accepted", backend.actions, None, replay)
            if previous is not None and self._state_signature(previous) == self._state_signature(state):
                replay.record("blocked", {"reason": "state_transition_missing"})
                return self._report(
                    prepared,
                    "blocked",
                    "accepted",
                    backend.actions,
                    "state_transition_missing",
                    replay,
                )
            context = ExecutionContext(
                "StarRail.exe",
                "StarRail.exe",
                state.screen,
                state.confidence,
                True,
                True,
            )
            observation_check = safety.check(
                Action(ActionType.BASIC_ATTACK),
                context,
                prepared.plan,
                prepared.readiness,
                approval,
            )
            if not observation_check.allowed:
                reason = f"{observation_check.code}: {observation_check.reason}"
                replay.record("blocked", {"reason": reason})
                return self._report(
                    prepared, "blocked", "rejected", backend.actions, reason, replay
                )
            decision = policy.decide(prepared.plan, state)
            try:
                executor.execute(
                    decision.action,
                    context,
                    prepared.plan,
                    prepared.readiness,
                    approval,
                )
            except SafetyViolation as error:
                replay.record("blocked", {"reason": str(error)})
                return self._report(prepared, "blocked", "rejected", backend.actions, str(error), replay)
            replay.record(
                "action",
                {"type": decision.action.type.value, "rule": decision.action.source_rule_id},
            )
            previous = state
        replay.record("blocked", {"reason": "state_stream_ended"})
        return self._report(prepared, "blocked", "accepted", backend.actions, "state_stream_ended", replay)

    @staticmethod
    def _state_signature(state: BattleState) -> tuple[object, ...]:
        return (state.screen, state.active_character, state.skill_points, state.battle_finished)

    @staticmethod
    def _report(
        prepared: PreparedSimulation,
        status: str,
        approval_status: str,
        actions: tuple[Action, ...] | list[Action],
        reason: str | None,
        replay: ReplayRecorder,
    ) -> SimulationReport:
        return SimulationReport(
            prepared.scenario.name,
            status,
            prepared.readiness.status.value if prepared.readiness else None,
            prepared.plan_hash,
            approval_status,
            tuple(action.type.value for action in actions),
            reason,
            len(replay.events()),
            len(prepared.cultivation_plan.steps) if prepared.cultivation_plan else 0,
        )
