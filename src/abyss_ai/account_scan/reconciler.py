from __future__ import annotations

from dataclasses import dataclass

from .interfaces import ScanPage, ScanResult


@dataclass(frozen=True, slots=True)
class ReconciledCharacterScan:
    character_id: str
    pages: tuple[ScanPage, ...]
    fields: tuple[tuple[str, str, float], ...]
    needs_review: bool


class ScanReconciler:
    """Merges OCR page results without silently accepting uncertain fields."""

    def __init__(self, minimum_confidence: float = 0.95) -> None:
        self.minimum_confidence = minimum_confidence

    def reconcile(self, results: tuple[ScanResult, ...]) -> ReconciledCharacterScan:
        if not results:
            raise ValueError("at least one scan result is required")
        character_ids = {result.character_id for result in results}
        if None in character_ids or len(character_ids) != 1:
            raise ValueError("scan pages do not identify one character")

        merged: dict[str, tuple[str, float]] = {}
        needs_review = False
        for result in results:
            if result.page is ScanPage.UNKNOWN or result.confidence < self.minimum_confidence:
                needs_review = True
            for name, value, confidence in result.fields:
                previous = merged.get(name)
                if previous is not None and previous[0] != value:
                    needs_review = True
                    if confidence <= previous[1]:
                        continue
                merged[name] = (value, confidence)
                if confidence < self.minimum_confidence:
                    needs_review = True

        character_id = next(iter(character_ids))
        assert character_id is not None
        fields = tuple((name, value, confidence) for name, (value, confidence) in sorted(merged.items()))
        return ReconciledCharacterScan(
            character_id,
            tuple(result.page for result in results),
            fields,
            needs_review,
        )

