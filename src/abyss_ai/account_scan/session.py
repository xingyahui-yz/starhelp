from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from uuid import UUID, uuid5

from abyss_ai.domain import (
    AccountSnapshot,
    CharacterBuild,
    EquippedLightCone,
    EquippedRelic,
    RelicSlot,
    ScannedField,
    StatValue,
)

from .interfaces import OcrEngine, ScanFrame, ScanPage, ScanResult
from .reconciler import ScanReconciler


@dataclass(frozen=True, slots=True)
class ReviewedCorrection:
    field_path: str
    ocr_value: str
    reviewed_value: str
    reason: str
    reviewed_at: datetime = field(default_factory=lambda: datetime.now(UTC))


@dataclass(frozen=True, slots=True)
class ScanReviewItem:
    field_path: str
    observed_values: tuple[str, ...]
    reason: str


@dataclass(frozen=True, slots=True)
class ScanSessionResult:
    snapshot: AccountSnapshot | None
    review_items: tuple[ScanReviewItem, ...]
    issues: tuple[str, ...]
    corrections: tuple[ReviewedCorrection, ...]
    planning_allowed: bool


class FixtureOcrEngine:
    """Deterministic parser for synthetic JSON frames; never reads the desktop."""

    SUPPORTED_SIZE = (1920, 1080)

    def scan(self, frame: ScanFrame) -> ScanResult:
        if (frame.width, frame.height) != self.SUPPORTED_SIZE:
            raise ValueError("unsupported fixture resolution")
        try:
            payload = json.loads(frame.pixels.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise ValueError("fixture frame must contain UTF-8 JSON") from error
        if not isinstance(payload, dict):
            raise ValueError("fixture payload must be an object")
        try:
            page = ScanPage(str(payload["page"]))
            character_id = str(payload["character_id"])
            fingerprint = str(payload["account_fingerprint"])
            confidence = float(payload["confidence"])
            raw_fields = payload["fields"]
        except (KeyError, TypeError, ValueError) as error:
            raise ValueError("invalid fixture payload") from error
        if page is ScanPage.UNKNOWN or not character_id or not fingerprint:
            raise ValueError("fixture identity or page is invalid")
        if not 0.0 <= confidence <= 1.0 or not isinstance(raw_fields, dict):
            raise ValueError("fixture confidence or fields are invalid")
        fields: list[tuple[str, str, float]] = []
        for name, raw in raw_fields.items():
            if not isinstance(raw, dict) or "value" not in raw or "confidence" not in raw:
                raise ValueError("fixture field must contain value and confidence")
            field_confidence = float(raw["confidence"])
            if not 0.0 <= field_confidence <= 1.0:
                raise ValueError("fixture field confidence is invalid")
            fields.append((str(name), str(raw["value"]), field_confidence))
        return ScanResult(page, character_id, tuple(fields), confidence, fingerprint)


class ScanSession:
    REQUIRED_PAGES = frozenset(
        {
            ScanPage.CHARACTER_STATS,
            ScanPage.LIGHT_CONE,
            ScanPage.RELICS,
            ScanPage.TRACES,
            ScanPage.EIDOLONS,
        }
    )
    RELIC_SLOTS = tuple(RelicSlot)

    def __init__(self, engine: OcrEngine, minimum_confidence: float = 0.95) -> None:
        self.engine = engine
        self.minimum_confidence = minimum_confidence
        self.reconciler = ScanReconciler(minimum_confidence)

    def run(
        self,
        frames: tuple[ScanFrame, ...],
        *,
        account_id: UUID,
        expected_fingerprint: str,
        game_version: str,
        corrections: tuple[ReviewedCorrection, ...] = (),
    ) -> ScanSessionResult:
        issues: list[str] = []
        reviews: list[ScanReviewItem] = []
        grouped: dict[str, list[ScanResult]] = {}
        for frame in frames:
            try:
                result = self.engine.scan(frame)
            except ValueError as error:
                issues.append(f"{frame.frame_id}: {error}")
                continue
            if result.account_fingerprint != expected_fingerprint:
                issues.append(f"{frame.frame_id}: account fingerprint mismatch")
                continue
            if result.character_id is None:
                issues.append(f"{frame.frame_id}: missing character identity")
                continue
            grouped.setdefault(result.character_id, []).append(result)

        correction_map = {item.field_path: item for item in corrections}
        if len(correction_map) != len(corrections):
            issues.append("duplicate correction field path")
        used_corrections: set[str] = set()
        characters: list[CharacterBuild] = []
        for character_id, page_results in sorted(grouped.items()):
            pages = {item.page for item in page_results}
            missing = self.REQUIRED_PAGES - pages
            if missing:
                issues.append(f"{character_id}: missing pages {','.join(sorted(p.value for p in missing))}")
                continue
            observed: dict[str, list[tuple[str, float]]] = {}
            for result in page_results:
                for name, value, confidence in result.fields:
                    observed.setdefault(name, []).append((value, confidence))
            for name, values in observed.items():
                unique = tuple(sorted({value for value, _ in values}))
                path = f"{character_id}.{name}"
                low = any(confidence < self.minimum_confidence for _, confidence in values)
                if len(unique) > 1 or low:
                    reason = "conflicting OCR values" if len(unique) > 1 else "low OCR confidence"
                    correction = correction_map.get(path)
                    if correction is None:
                        reviews.append(ScanReviewItem(path, unique, reason))
                    elif not correction.reason.strip() or correction.ocr_value not in unique:
                        issues.append(f"{path}: correction does not match observed OCR value")
                    else:
                        used_corrections.add(path)
            try:
                reconciled = self.reconciler.reconcile(tuple(page_results))
                values = {name: (value, confidence) for name, value, confidence in reconciled.fields}
                for path, correction in correction_map.items():
                    prefix = f"{character_id}."
                    if path.startswith(prefix):
                        name = path[len(prefix) :]
                        if name in values and path in used_corrections:
                            values[name] = (correction.reviewed_value, 1.0)
                characters.append(self._build_character(account_id, character_id, values))
            except ValueError as error:
                issues.append(f"{character_id}: {error}")

        unused_corrections = set(correction_map) - used_corrections
        if unused_corrections:
            issues.append(f"unused corrections: {','.join(sorted(unused_corrections))}")
        if reviews or issues or len(characters) != 8:
            if len(characters) != 8:
                issues.append(f"expected 8 characters, got {len(characters)}")
            return ScanSessionResult(None, tuple(reviews), tuple(dict.fromkeys(issues)), corrections, False)

        digest = hashlib.sha256()
        digest.update(str(account_id).encode())
        digest.update(game_version.encode())
        for frame in frames:
            digest.update(frame.pixels)
        for correction in corrections:
            digest.update(f"{correction.field_path}:{correction.reviewed_value}".encode())
        snapshot = AccountSnapshot(
            snapshot_id=uuid5(account_id, digest.hexdigest()),
            account_id=account_id,
            game_version=game_version,
            characters=tuple(characters),
        )
        return ScanSessionResult(snapshot, (), (), corrections, True)

    def _build_character(
        self, account_id: UUID, character_id: str, values: dict[str, tuple[str, float]]
    ) -> CharacterBuild:
        def integer(name: str, minimum: int, maximum: int) -> ScannedField[int]:
            if name not in values:
                raise ValueError(f"missing field {name}")
            raw, confidence = values[name]
            try:
                value = int(raw)
            except ValueError as error:
                raise ValueError(f"field {name} is not an integer") from error
            if not minimum <= value <= maximum:
                raise ValueError(f"field {name} is outside allowed range")
            return ScannedField(value, confidence, f"fixture:{character_id}.{name}")

        level = integer("level", 1, 80)
        eidolon = integer("eidolon", 0, 6)
        light_cone = EquippedLightCone(
            account_id,
            values.get("light_cone_id", ("fixture_light_cone", 0.99))[0],
            integer("light_cone_level", 1, 80),
            integer("superimposition", 1, 5),
        )
        relics: list[EquippedRelic] = []
        for slot in self.RELIC_SLOTS:
            set_name = f"relic_{slot.value}_set"
            level_name = f"relic_{slot.value}_level"
            if set_name not in values:
                raise ValueError(f"missing field {set_name}")
            set_value, set_confidence = values[set_name]
            relics.append(
                EquippedRelic(
                    account_id,
                    character_id,
                    slot,
                    ScannedField(set_value, set_confidence, f"fixture:{character_id}.{set_name}"),
                    integer(level_name, 0, 15),
                    ScannedField(
                        StatValue("fixture_main", 1.0),
                        0.99,
                        f"fixture:{character_id}.{slot.value}.main",
                    ),
                )
            )
        speed_raw, speed_confidence = values.get("speed", ("100", 0.99))
        try:
            speed = float(speed_raw)
        except ValueError as error:
            raise ValueError("field speed is not numeric") from error
        if not 50 <= speed <= 250:
            raise ValueError("field speed is outside allowed range")
        return CharacterBuild(
            account_id,
            character_id,
            level,
            eidolon,
            traces=(integer("trace_basic", 1, 10),),
            light_cone=light_cone,
            relics=tuple(relics),
            stats=(ScannedField(StatValue("speed", speed), speed_confidence, "fixture:speed"),),
        )
