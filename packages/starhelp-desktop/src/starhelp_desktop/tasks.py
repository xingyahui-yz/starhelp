from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4

from .lifecycle import ProfileLifecycle
from .storage import EncryptedPrivateStore


class TaskState(StrEnum):
    WAITING_FOR_PLANNER = "waiting_for_planner"


def _identifier_list(value: str, label: str) -> tuple[str, ...]:
    if not value.strip():
        return ()
    items = tuple(part.strip() for part in value.split(","))
    if any(not item for item in items):
        raise ValueError(f"{label} contains an empty identifier")
    if any(len(item) > 160 or any(ord(char) < 32 for char in item) for item in items):
        raise ValueError(f"{label} contains an invalid identifier")
    if len(items) != len(set(items)):
        raise ValueError(f"{label} contains a duplicate identifier")
    if len(items) > 64:
        raise ValueError(f"{label} exceeds the 64-identifier limit")
    return items


def _validate_identifiers(items: tuple[str, ...], label: str) -> None:
    if len(items) > 64 or len(items) != len(set(items)):
        raise ValueError(f"{label} is duplicated or exceeds the 64-identifier limit")
    if any(not item or item != item.strip() or len(item) > 160 or
           any(ord(char) < 32 for char in item) for item in items):
        raise ValueError(f"{label} contains an invalid identifier")


@dataclass(frozen=True, slots=True)
class AnalysisTaskDraft:
    """Encrypted local task selection. It is not a planner result or public API contract."""

    task_id: UUID
    profile_id: UUID
    authorization_generation: int
    mode_label: str
    cycle_id: str
    stage_id: str
    goal_label: str
    fixed_character_ids: tuple[str, ...]
    excluded_character_ids: tuple[str, ...]
    locked_equipment_instance_ids: tuple[str, ...]
    created_at: datetime
    state: TaskState = TaskState.WAITING_FOR_PLANNER
    progress: int = 0

    def __post_init__(self) -> None:
        if self.authorization_generation < 1:
            raise ValueError("authorization generation must be positive")
        if self.created_at.tzinfo is None:
            raise ValueError("task time must be timezone aware")
        for label, value in (("mode", self.mode_label), ("cycle", self.cycle_id),
                             ("stage", self.stage_id), ("goal", self.goal_label)):
            if not value.strip() or len(value) > 160 or any(ord(char) < 32 for char in value):
                raise ValueError(f"{label} is required and must be a single-line value")
        overlap = set(self.fixed_character_ids) & set(self.excluded_character_ids)
        if overlap:
            raise ValueError("a character cannot be both fixed and excluded")
        _validate_identifiers(self.fixed_character_ids, "fixed characters")
        _validate_identifiers(self.excluded_character_ids, "excluded characters")
        _validate_identifiers(self.locked_equipment_instance_ids, "locked equipment")
        if not 0 <= self.progress <= 100:
            raise ValueError("task progress must be between 0 and 100")

    @classmethod
    def create(
        cls,
        *,
        profile_id: UUID,
        authorization_generation: int,
        mode_label: str,
        cycle_id: str,
        stage_id: str,
        goal_label: str,
        fixed_character_ids: str = "",
        excluded_character_ids: str = "",
        locked_equipment_instance_ids: str = "",
    ) -> AnalysisTaskDraft:
        fixed = _identifier_list(fixed_character_ids, "fixed characters")
        excluded = _identifier_list(excluded_character_ids, "excluded characters")
        locked = _identifier_list(locked_equipment_instance_ids, "locked equipment")
        return cls(
            task_id=uuid4(),
            profile_id=profile_id,
            authorization_generation=authorization_generation,
            mode_label=mode_label.strip(),
            cycle_id=cycle_id.strip(),
            stage_id=stage_id.strip(),
            goal_label=goal_label.strip(),
            fixed_character_ids=fixed,
            excluded_character_ids=excluded,
            locked_equipment_instance_ids=locked,
            created_at=datetime.now(UTC),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": str(self.task_id),
            "profile_id": str(self.profile_id),
            "authorization_generation": self.authorization_generation,
            "mode_label": self.mode_label,
            "cycle_id": self.cycle_id,
            "stage_id": self.stage_id,
            "goal_label": self.goal_label,
            "fixed_character_ids": list(self.fixed_character_ids),
            "excluded_character_ids": list(self.excluded_character_ids),
            "locked_equipment_instance_ids": list(self.locked_equipment_instance_ids),
            "created_at": self.created_at.isoformat(),
            "state": self.state.value,
            "progress": self.progress,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> AnalysisTaskDraft:
        return cls(
            task_id=UUID(data["task_id"]),
            profile_id=UUID(data["profile_id"]),
            authorization_generation=int(data["authorization_generation"]),
            mode_label=str(data["mode_label"]),
            cycle_id=str(data["cycle_id"]),
            stage_id=str(data["stage_id"]),
            goal_label=str(data["goal_label"]),
            fixed_character_ids=tuple(str(item) for item in data.get("fixed_character_ids", [])),
            excluded_character_ids=tuple(str(item) for item in data.get("excluded_character_ids", [])),
            locked_equipment_instance_ids=tuple(
                str(item) for item in data.get("locked_equipment_instance_ids", [])
            ),
            created_at=datetime.fromisoformat(data["created_at"]),
            state=TaskState(data["state"]),
            progress=int(data["progress"]),
        )


class TaskRepository:
    """Stores each profile's remembered task under its encrypted, revocable key prefix."""

    SCHEMA_ID = "LocalAnalysisTaskPreference"
    SCHEMA_VERSION = "0.1-draft"

    def __init__(self, store: EncryptedPrivateStore, lifecycle: ProfileLifecycle) -> None:
        self._store = store
        self._lifecycle = lifecycle

    def save_last(self, task: AnalysisTaskDraft) -> None:
        self._lifecycle.require_active(task.profile_id, task.authorization_generation)
        self._store.save(self._key(task.profile_id), {
            "schema_id": self.SCHEMA_ID,
            "schema_version": self.SCHEMA_VERSION,
            "task": task.to_dict(),
        })

    def load_last(self, profile_id: UUID, generation: int) -> AnalysisTaskDraft | None:
        self._lifecycle.require_active(profile_id, generation)
        try:
            data = self._store.load(self._key(profile_id))
        except FileNotFoundError:
            return None
        if data.get("schema_id") != self.SCHEMA_ID or data.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("unsupported encrypted task preference schema")
        task = AnalysisTaskDraft.from_dict(data["task"])
        if task.profile_id != profile_id or task.authorization_generation != generation:
            raise ValueError("remembered task does not match the active profile generation")
        return task

    @staticmethod
    def _key(profile_id: UUID) -> str:
        return f"profile-{profile_id.hex}-last-task"
