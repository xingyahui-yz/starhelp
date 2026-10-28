from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from .lifecycle import ProfileLifecycle
from .storage import EncryptedPrivateStore

PROGRESS_MODES = ("混沌回忆", "虚构叙事", "末日幻影")
PROGRESS_OUTCOMES = ("已达成", "未达成", "待确认")
MAX_PROGRESS_ENTRIES = 200


def _single_line(value: str, label: str, maximum: int, *, required: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be text")
    normalized = value.strip()
    if required and not normalized:
        raise ValueError(f"{label} is required")
    if len(normalized) > maximum or any(ord(char) < 32 for char in normalized):
        raise ValueError(f"{label} is too long or contains control characters")
    return normalized


@dataclass(frozen=True, slots=True)
class PlayerProgressEntry:
    entry_id: UUID
    profile_id: UUID
    authorization_generation: int
    mode_label: str
    period_label: str
    stage_label: str
    outcome: str
    note: str
    recorded_at: datetime

    def __post_init__(self) -> None:
        if self.authorization_generation < 1:
            raise ValueError("authorization generation must be positive")
        if self.mode_label not in PROGRESS_MODES:
            raise ValueError("unsupported progress mode label")
        if self.outcome not in PROGRESS_OUTCOMES:
            raise ValueError("unsupported player-reported outcome")
        if self.recorded_at.tzinfo is None:
            raise ValueError("progress timestamp must be timezone aware")
        _single_line(self.period_label, "period", 120)
        _single_line(self.stage_label, "stage", 120)
        _single_line(self.note, "note", 1000)
        if not self.period_label and not self.stage_label:
            raise ValueError("a period or stage label is required")

    @classmethod
    def create(
        cls,
        *,
        profile_id: UUID,
        authorization_generation: int,
        mode_label: str,
        period_label: str,
        stage_label: str,
        outcome: str,
        note: str = "",
    ) -> PlayerProgressEntry:
        return cls(
            entry_id=uuid4(),
            profile_id=profile_id,
            authorization_generation=authorization_generation,
            mode_label=mode_label,
            period_label=_single_line(period_label, "period", 120),
            stage_label=_single_line(stage_label, "stage", 120),
            outcome=outcome,
            note=_single_line(note, "note", 1000),
            recorded_at=datetime.now(UTC),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "entry_id": str(self.entry_id),
            "profile_id": str(self.profile_id),
            "authorization_generation": self.authorization_generation,
            "mode_label": self.mode_label,
            "period_label": self.period_label,
            "stage_label": self.stage_label,
            "outcome": self.outcome,
            "note": self.note,
            "recorded_at": self.recorded_at.isoformat(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> PlayerProgressEntry:
        if not isinstance(data, dict):
            raise ValueError("malformed player progress entry")
        if set(data) != {
            "entry_id", "profile_id", "authorization_generation", "mode_label",
            "period_label", "stage_label", "outcome", "note", "recorded_at",
        }:
            raise ValueError("unsupported player progress entry fields")
        generation = data["authorization_generation"]
        if not isinstance(generation, int) or isinstance(generation, bool) or generation < 1:
            raise ValueError("malformed player progress authorization generation")
        text_fields = (
            "entry_id", "profile_id", "mode_label", "period_label", "stage_label", "outcome",
            "note", "recorded_at",
        )
        if any(not isinstance(data[name], str) for name in text_fields):
            raise ValueError("malformed player progress entry text")
        return cls(
            entry_id=UUID(data["entry_id"]),
            profile_id=UUID(data["profile_id"]),
            authorization_generation=generation,
            mode_label=data["mode_label"],
            period_label=data["period_label"],
            stage_label=data["stage_label"],
            outcome=data["outcome"],
            note=data["note"],
            recorded_at=datetime.fromisoformat(data["recorded_at"]),
        )


class ProgressRepository:
    """Encrypted, profile-scoped player notes; these are not source coverage or planner input."""

    SCHEMA_ID = "LocalPlayerProgress"
    SCHEMA_VERSION = "0.1-draft"

    def __init__(self, store: EncryptedPrivateStore, lifecycle: ProfileLifecycle) -> None:
        self._store = store
        self._lifecycle = lifecycle

    def list_entries(self, profile_id: UUID, generation: int) -> tuple[PlayerProgressEntry, ...]:
        return self._lifecycle.run_authorized(
            profile_id, generation, lambda: self._load(profile_id, generation)
        )

    def add(self, entry: PlayerProgressEntry) -> PlayerProgressEntry:
        def save() -> PlayerProgressEntry:
            entries = self._load(entry.profile_id, entry.authorization_generation)
            if len(entries) >= MAX_PROGRESS_ENTRIES:
                raise ValueError("profile progress history is full; delete an old note first")
            entries = (*entries, entry)
            self._store.save(self._key(entry.profile_id), {
                "schema_id": self.SCHEMA_ID,
                "schema_version": self.SCHEMA_VERSION,
                "entries": [item.to_dict() for item in entries],
            })
            return entry

        return self._lifecycle.run_authorized(
            entry.profile_id, entry.authorization_generation, save
        )

    def delete(self, profile_id: UUID, generation: int, entry_id: UUID) -> None:
        def remove() -> None:
            entries = self._load(profile_id, generation)
            retained = tuple(item for item in entries if item.entry_id != entry_id)
            if len(retained) == len(entries):
                return
            if retained:
                self._store.save(self._key(profile_id), {
                    "schema_id": self.SCHEMA_ID,
                    "schema_version": self.SCHEMA_VERSION,
                    "entries": [item.to_dict() for item in retained],
                })
            else:
                self._store.delete_key(self._key(profile_id))

        self._lifecycle.run_authorized(profile_id, generation, remove)

    def _load(self, profile_id: UUID, generation: int) -> tuple[PlayerProgressEntry, ...]:
        try:
            data = self._store.load(self._key(profile_id))
        except FileNotFoundError:
            return ()
        if data.get("schema_id") != self.SCHEMA_ID or data.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("unsupported encrypted player progress schema")
        raw_entries = data.get("entries")
        if not isinstance(raw_entries, list) or len(raw_entries) > MAX_PROGRESS_ENTRIES:
            raise ValueError("encrypted player progress history is malformed")
        entries = tuple(PlayerProgressEntry.from_dict(item) for item in raw_entries)
        if any(
            item.profile_id != profile_id or item.authorization_generation != generation
            for item in entries
        ) or len({item.entry_id for item in entries}) != len(entries):
            raise ValueError("player progress history does not match the active profile")
        return entries

    @staticmethod
    def _key(profile_id: UUID) -> str:
        return f"profile-{profile_id.hex}-progress-notes"
