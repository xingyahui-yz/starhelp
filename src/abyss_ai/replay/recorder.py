from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime


@dataclass(frozen=True, slots=True)
class ReplayEvent:
    event_type: str
    payload: tuple[tuple[str, str], ...]
    timestamp: datetime


class ReplayRecorder:
    """In-memory, privacy-preserving event recorder for deterministic tests."""

    FORBIDDEN_KEYS = frozenset(
        {
            "uid",
            "cookie",
            "cookies",
            "authorization",
            "api_key",
            "password",
            "access_token",
            "refresh_token",
            "token",
        }
    )

    def __init__(self) -> None:
        self._events: list[ReplayEvent] = []

    def record(self, event_type: str, payload: dict[str, object]) -> None:
        forbidden: set[str] = set()

        def inspect(value: object) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if key.lower() in self.FORBIDDEN_KEYS:
                        forbidden.add(key.lower())
                    inspect(item)
            elif isinstance(value, (list, tuple)):
                for item in value:
                    inspect(item)

        inspect(payload)
        if forbidden:
            raise ValueError(f"sensitive replay fields are forbidden: {sorted(forbidden)}")
        normalised = tuple(sorted((key, str(value)) for key, value in payload.items()))
        self._events.append(ReplayEvent(event_type, normalised, datetime.now(UTC)))

    def events(self) -> tuple[ReplayEvent, ...]:
        return tuple(self._events)
