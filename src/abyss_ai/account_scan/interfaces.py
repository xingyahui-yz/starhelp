from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


class ScanPage(StrEnum):
    CHARACTER_LIST = "character_list"
    CHARACTER_STATS = "character_stats"
    LIGHT_CONE = "light_cone"
    RELICS = "relics"
    TRACES = "traces"
    EIDOLONS = "eidolons"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class ScanFrame:
    frame_id: str
    captured_at: datetime
    width: int
    height: int
    pixels: bytes


@dataclass(frozen=True, slots=True)
class ScanResult:
    page: ScanPage
    character_id: str | None
    fields: tuple[tuple[str, str, float], ...]
    confidence: float
    account_fingerprint: str | None = None


class OcrEngine(Protocol):
    def scan(self, frame: ScanFrame) -> ScanResult: ...
