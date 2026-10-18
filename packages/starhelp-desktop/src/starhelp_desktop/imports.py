from __future__ import annotations

import json
import re
import warnings
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from io import BytesIO
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .models import (
    EquipmentIdentity,
    EquipmentInstance,
    FieldFact,
    FieldStatus,
    ImportProposal,
    Ownership,
    SourceKind,
)


_CREDENTIAL_KEYS = {
    "password", "cookie", "cookies", "authorization", "token", "access_token",
    "refresh_token", "api_key", "apikey", "authkey", "session", "session_token",
    "uid", "raw_uid",
}
_FIELD_PATH = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._:/-]{0,199}$")
_UID_LIKE = re.compile(r"(?<!\d)\d{8,12}(?!\d)")
_MAX_IMPORT_BYTES = 16 * 1024 * 1024
_MAX_JSON_DEPTH = 64
_MAX_JSON_NODES = 250_000
_MAX_JSON_STRING_LENGTH = 1_000_000


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("structured import contains a duplicate JSON key")
        result[key] = value
    return result


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"structured import contains non-standard JSON number {value}")


def _validate_json_complexity(root: object) -> None:
    pending = [(root, 0)]
    nodes = 0
    while pending:
        value, depth = pending.pop()
        nodes += 1
        if nodes > _MAX_JSON_NODES:
            raise ValueError("structured import exceeds the JSON node limit")
        if depth > _MAX_JSON_DEPTH:
            raise ValueError("structured import exceeds the JSON nesting limit")
        if isinstance(value, dict):
            for key, item in value.items():
                if not isinstance(key, str) or len(key) > _MAX_JSON_STRING_LENGTH:
                    raise ValueError("structured import contains an invalid or oversized key")
                pending.append((item, depth + 1))
        elif isinstance(value, list):
            pending.extend((item, depth + 1) for item in value)
        elif isinstance(value, str) and len(value) > _MAX_JSON_STRING_LENGTH:
            raise ValueError("structured import contains an oversized string")


def reject_credentials(value: object, path: str = "$") -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            if str(key).lower() in _CREDENTIAL_KEYS:
                raise ValueError(f"credential-like field is not accepted at {path}.{key}")
            reject_credentials(item, f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            reject_credentials(item, f"{path}[{index}]")
    elif isinstance(value, str) and re.fullmatch(r"\d{8,12}", value):
        raise ValueError(f"UID-like value is not accepted at {path}")


class OcrEngine(Protocol):
    def recognize(self, image_bytes: bytes) -> OcrDraft: ...


@dataclass(frozen=True, slots=True)
class OcrTextLine:
    text: str
    confidence: float
    bounds: tuple[tuple[int, int], ...]


@dataclass(frozen=True, slots=True)
class OcrDraft:
    """Ephemeral OCR text and geometry. Contains no image bytes and is not a saved import."""

    lines: tuple[OcrTextLine, ...]
    recognized_at: datetime
    warnings: tuple[str, ...] = ()


class RapidOcrEngine:
    """Optional local RapidOCR adapter. Missing models fail closed without downloading."""

    MAX_IMAGE_BYTES = 16 * 1024 * 1024
    MAX_IMAGE_PIXELS = 30_000_000
    _UID_TEXT = re.compile(r"(?<!\d)\d{8,12}(?!\d)")

    def __init__(self) -> None:
        try:
            from rapidocr import RapidOCR
            import rapidocr
        except ImportError as exc:
            raise RuntimeError("OCR extra is not installed; use [ocr] or manual import") from exc
        model_root = Path(rapidocr.__file__).resolve().parent / "models"
        required_models = (
            "PP-OCRv6_det_small.onnx",
            "ch_ppocr_mobile_v2.0_cls_mobile.onnx",
            "PP-OCRv6_rec_small.onnx",
        )
        if not model_root.is_dir() or any(not (model_root / name).is_file() for name in required_models):
            raise RuntimeError("local OCR model files are missing; network model download is disabled")
        self._engine = RapidOCR(params={"Rec.lang_type": "ch"})

    def recognize(self, image_bytes: bytes) -> OcrDraft:
        if not image_bytes or len(image_bytes) > self.MAX_IMAGE_BYTES:
            raise ValueError("image is empty or exceeds the local OCR size limit")
        try:
            from PIL import Image
        except ImportError:
            raise RuntimeError("Pillow is required by the local OCR extra") from None
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(image_bytes)) as image:
                    if image.format not in {"PNG", "JPEG", "WEBP"}:
                        raise ValueError("only PNG, JPEG, and WEBP images are supported")
                    if image.width * image.height > self.MAX_IMAGE_PIXELS:
                        raise ValueError("image dimensions exceed the local OCR limit")
                    image.verify()
        except (OSError, ValueError, Image.DecompressionBombError,
                Image.DecompressionBombWarning) as exc:
            raise ValueError(f"image validation failed: {type(exc).__name__}") from None
        result = self._engine(image_bytes)
        texts = getattr(result, "txts", None)
        scores = getattr(result, "scores", None)
        boxes = getattr(result, "boxes", None)
        texts = () if texts is None else texts
        scores = () if scores is None else scores
        boxes = () if boxes is None else boxes
        lines: list[OcrTextLine] = []
        for index, text in enumerate(texts):
            score = float(scores[index]) if index < len(scores) else 0.0
            box_raw = boxes[index] if index < len(boxes) else ()
            bounds = tuple((int(point[0]), int(point[1])) for point in box_raw)
            # Never expose or retain an obvious raw UID string from OCR output.
            safe_text = self._UID_TEXT.sub("[UID 已隐藏]", str(text))
            lines.append(OcrTextLine(safe_text, max(0.0, min(score, 1.0)), bounds))
        return OcrDraft(
            tuple(lines), datetime.now(UTC),
            ("OCR 仅生成待复核文本；不得直接当作确认字段。原图仅在本次识别内存中使用。",),
        )


def read_ocr_image(path: Path) -> bytes:
    """Read a selected screenshot with a hard bound even if it grows after selection."""
    with path.open("rb") as stream:
        image_bytes = stream.read(RapidOcrEngine.MAX_IMAGE_BYTES + 1)
    if not image_bytes:
        raise ValueError("截图文件为空")
    if len(image_bytes) > RapidOcrEngine.MAX_IMAGE_BYTES:
        raise ValueError("截图超过 16 MiB 本机 OCR 限制")
    return image_bytes


def proposal_from_ocr_mapping(draft: OcrDraft, mapping: dict[str, int]) -> ImportProposal:
    """Map player-selected text rows to explicit field paths; no automatic semantic guess."""
    fields: dict[str, FieldFact] = {}
    for field_path, line_index in mapping.items():
        if not _FIELD_PATH.fullmatch(field_path) or "uid" in field_path.lower():
            raise ValueError("invalid or private OCR field path")
        if not 0 <= line_index < len(draft.lines):
            raise IndexError("OCR line selection is outside the preview")
        line = draft.lines[line_index]
        fields[field_path] = FieldFact(
            value=line.text,
            status=FieldStatus.NEEDS_REVIEW,
            source_kind=SourceKind.OCR,
            source_id="local-rapidocr",
            observed_at=draft.recognized_at,
            scope=f"ocr-confidence:{line.confidence:.3f}",
        )
    return ImportProposal.create(
        source_kind=SourceKind.OCR,
        source_id="local-rapidocr",
        observed_at=draft.recognized_at,
        fields=fields,
        coverage=frozenset(fields),
        warnings=draft.warnings + ("请逐字段核对 OCR 文本、来源和范围后再确认。",),
    )


@dataclass(frozen=True, slots=True)
class ImportPreview:
    proposal: ImportProposal
    source_name: str
    raw_field_count: int


class StructuredImportAdapter:
    """Reads the component's explicit local import draft; it is preview-only."""

    SCHEMA_ID = "starhelp.account-import"
    SCHEMA_VERSION = "0.1-draft"

    def preview_file(self, path: Path) -> ImportPreview:
        # The file remains user-owned. It is read once and never copied by this adapter.
        with path.open("rb") as source:
            raw = source.read(_MAX_IMPORT_BYTES + 1)
        if len(raw) > _MAX_IMPORT_BYTES:
            raise ValueError("structured import exceeds the 16 MiB file limit")
        try:
            data = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, RecursionError) as exc:
            raise ValueError(f"structured import JSON is invalid: {type(exc).__name__}") from None
        return self.preview_object(data, source_name=path.name)

    def preview_object(self, data: object, *, source_name: str = "in-memory import") -> ImportPreview:
        _validate_json_complexity(data)
        if not isinstance(data, dict):
            raise ValueError("import root must be an object")
        reject_credentials(data)
        if data.get("schema_id") != self.SCHEMA_ID:
            raise ValueError("unsupported structured import schema")
        if data.get("schema_version") != self.SCHEMA_VERSION:
            raise ValueError("unsupported structured import version")
        observed_text = data.get("observed_at")
        if not isinstance(observed_text, str):
            raise ValueError("observed_at must be an ISO timestamp with a timezone")
        observed = datetime.fromisoformat(observed_text)
        if observed.tzinfo is None:
            raise ValueError("observed_at must include a timezone")
        observed = observed.astimezone(UTC)
        source_id = str(data.get("source_id", "local-file"))
        if _UID_LIKE.search(source_id):
            raise ValueError("source_id must not contain a raw UID")
        records = data.get("fields")
        if not isinstance(records, dict):
            raise ValueError("fields must be an object keyed by local field path")
        fields: dict[str, FieldFact] = {}
        for field_path, raw in records.items():
            if (not isinstance(field_path, str) or not _FIELD_PATH.fullmatch(field_path)
                    or "uid" in field_path.lower()):
                raise ValueError("invalid field path")
            if not isinstance(raw, dict) or "value" not in raw:
                raise ValueError(f"field {field_path} must contain an explicit value")
            fields[field_path] = FieldFact(
                value=raw["value"],
                status=FieldStatus.NEEDS_REVIEW,
                source_kind=SourceKind.STRUCTURED_IMPORT,
                source_id=source_id,
                observed_at=observed,
                scope=raw.get("scope"),
            )
        ownership: dict[str, Ownership] = {}
        ownership_raw = data.get("ownership", {})
        if not isinstance(ownership_raw, dict):
            raise ValueError("ownership must be an object")
        for character_id, state in ownership_raw.items():
            try:
                ownership[str(character_id)] = Ownership(str(state))
            except ValueError as exc:
                raise ValueError("ownership must be owned, not_owned, or unknown") from exc
        default_coverage = list(fields) + [f"ownership:{key}" for key in ownership]
        coverage_raw = data.get("coverage", default_coverage)
        if not isinstance(coverage_raw, list) or not all(isinstance(item, str) for item in coverage_raw):
            raise ValueError("coverage must be a list of field paths")
        if not set(fields).issubset(set(coverage_raw)):
            raise ValueError("every imported field must be included in coverage")
        if not {f"ownership:{key}" for key in ownership}.issubset(set(coverage_raw)):
            raise ValueError("every imported ownership fact must be included in coverage")
        equipment: list[EquipmentInstance] = []
        equipment_raw = data.get("equipment", [])
        if not isinstance(equipment_raw, list):
            raise ValueError("equipment must be a list")
        for item in equipment_raw:
            if not isinstance(item, dict) or not item.get("public_type_id") or not item.get("slot"):
                raise ValueError("each equipment record needs a type ID and slot")
            public_type_id = _validated_import_identifier(item["public_type_id"], "equipment type ID")
            slot = _validated_import_identifier(item["slot"], "equipment slot")
            owner_character_id = item.get("owner_character_id")
            if owner_character_id is not None:
                owner_character_id = _validated_import_identifier(
                    owner_character_id, "equipment owner character ID"
                )
            facts_raw = item.get("facts", {})
            if not isinstance(facts_raw, dict):
                raise ValueError("equipment facts must be an object keyed by local field path")
            facts: dict[str, FieldFact] = {}
            for field_path, raw in facts_raw.items():
                if (not isinstance(field_path, str) or not _FIELD_PATH.fullmatch(field_path)
                        or "uid" in field_path.lower()):
                    raise ValueError("invalid equipment field path")
                if not isinstance(raw, dict) or "value" not in raw:
                    raise ValueError(f"equipment field {field_path} must contain an explicit value")
                scope = raw.get("scope")
                if scope is not None and not isinstance(scope, str):
                    raise ValueError(f"equipment field {field_path} scope must be a string")
                facts[field_path] = FieldFact(
                    value=raw["value"],
                    status=FieldStatus.NEEDS_REVIEW,
                    source_kind=SourceKind.STRUCTURED_IMPORT,
                    source_id=source_id,
                    observed_at=observed,
                    scope=scope,
                )
            # A type ID describes a kind of item; it never establishes copy identity.
            equipment.append(
                EquipmentInstance(
                    local_instance_id=uuid4(),
                    public_type_id=public_type_id,
                    slot=slot,
                    identity=EquipmentIdentity.UNCONFIRMED,
                    owner_character_id=owner_character_id,
                    facts=facts,
                )
            )
        proposal = ImportProposal.create(
            source_kind=SourceKind.STRUCTURED_IMPORT,
            source_id=source_id,
            observed_at=observed,
            fields=fields,
            ownership=ownership,
            equipment=tuple(equipment),
            coverage=frozenset(coverage_raw),
            warnings=("导入内容尚未确认；装备实例身份需要单独确认。",),
        )
        return ImportPreview(
            proposal,
            source_name,
            len(fields) + sum(len(item.facts) for item in equipment),
        )


def _validated_import_identifier(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > 160
        or any(ord(char) < 32 for char in value)
        or _UID_LIKE.search(value)
    ):
        raise ValueError(f"{label} is invalid or contains a UID-like value")
    return value


class ManualImportAdapter:
    def preview(self, values: dict[str, object]) -> ImportProposal:
        now = datetime.now(UTC)
        fields: dict[str, FieldFact] = {}
        for path, value in values.items():
            if not _FIELD_PATH.fullmatch(path):
                raise ValueError(f"invalid field path: {path}")
            fields[path] = FieldFact(
                value=value,
                status=FieldStatus.NEEDS_REVIEW,
                source_kind=SourceKind.MANUAL,
                source_id="manual-entry",
                observed_at=now,
            )
        return ImportProposal.create(
            source_kind=SourceKind.MANUAL,
            source_id="manual-entry",
            observed_at=now,
            fields=fields,
            coverage=frozenset(fields),
        )


def confirm_ocr_preview(proposal: ImportProposal) -> ImportProposal:
    if proposal.source_kind is not SourceKind.OCR:
        raise ValueError("proposal is not an OCR preview")
    # Drop the software's in-memory image reference after the user confirms fields.
    return confirm_import(proposal)


def confirm_import(proposal: ImportProposal) -> ImportProposal:
    """Record the player's explicit acceptance of the previewed facts."""
    now = datetime.now(UTC)
    confirmed_fields = {
        path: replace(fact, status=FieldStatus.CONFIRMED, confirmed_at=now)
        for path, fact in proposal.fields.items()
    }
    return replace(proposal, fields=confirmed_fields, image_buffer=None, confirmed=True)
