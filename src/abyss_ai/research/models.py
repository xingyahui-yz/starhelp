from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class SourceTier(StrEnum):
    OFFICIAL = "A"
    STRUCTURED = "B"
    GUIDE = "C"
    COMMUNITY = "D"
    DISCOVERY_ONLY = "E"


@dataclass(frozen=True, slots=True)
class SourceRecord:
    source_id: str
    url: str
    tier: SourceTier
    game_version: str
    fetched_at: datetime
    content_hash: str
    reviewed: bool = False

    @property
    def eligible_for_facts(self) -> bool:
        return self.tier in {SourceTier.OFFICIAL, SourceTier.STRUCTURED} or self.reviewed

