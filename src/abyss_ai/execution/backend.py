from __future__ import annotations

from typing import Protocol

from abyss_ai.domain import Action


class InputBackend(Protocol):
    def send(self, action: Action) -> None: ...


class RecordingInputBackend:
    """Safe Phase 0–1 backend. It records semantics and never sends OS input."""

    def __init__(self) -> None:
        self.actions: list[Action] = []

    def send(self, action: Action) -> None:
        self.actions.append(action)

