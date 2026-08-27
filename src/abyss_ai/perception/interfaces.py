from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from abyss_ai.domain import BattleState


@dataclass(frozen=True, slots=True)
class Frame:
    frame_id: str
    captured_at: datetime
    window_process: str
    width: int
    height: int
    pixels: bytes


@dataclass(frozen=True, slots=True)
class Observation:
    state: BattleState
    evidence: tuple[str, ...]


class CaptureBackend(Protocol):
    def capture_game_window(self) -> Frame: ...


class PerceptionEngine(Protocol):
    def observe(self, frame: Frame) -> Observation: ...

