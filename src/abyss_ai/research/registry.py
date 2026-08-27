from __future__ import annotations

from .models import SourceRecord


class SourceRegistry:
    def __init__(self) -> None:
        self._sources: dict[str, SourceRecord] = {}

    def register(self, source: SourceRecord) -> None:
        existing = self._sources.get(source.source_id)
        if existing and existing.content_hash != source.content_hash:
            raise ValueError("source content changed; explicit review is required")
        self._sources[source.source_id] = source

    def get(self, source_id: str) -> SourceRecord:
        return self._sources[source_id]

    def facts_for_version(self, game_version: str) -> tuple[SourceRecord, ...]:
        return tuple(
            source
            for source in self._sources.values()
            if source.game_version == game_version and source.eligible_for_facts
        )

