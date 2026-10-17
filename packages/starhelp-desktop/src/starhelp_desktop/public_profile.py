from __future__ import annotations

import json
import math
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import UTC, datetime
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


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate JSON object key")
        result[key] = value
    return result


def _reject_json_constant(_value: str) -> None:
    raise ValueError("non-finite JSON constant")


def _finite_number(value: object) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    try:
        return math.isfinite(value)
    except OverflowError:
        return False


def _finite_integer(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and _finite_number(value)


def _public_text(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    result = value.strip()
    if not result or len(result) > 160 or any(ord(char) < 32 for char in result):
        return None
    return result


def _public_identifier(value: object) -> str | None:
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    return _public_text(str(value))


class UserConfirmation(Protocol):
    def confirmed(self) -> bool: ...


class ProfileRequestError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message)
        self.status_code = status_code


class _RejectRedirects(urllib.request.HTTPRedirectHandler):
    """A UID request must stay on the service the player selected."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


@dataclass(frozen=True, slots=True)
class PublicProfileSelection:
    uid: str
    server_label: str
    provider_id: str
    confirmed_by_user: bool


class MihomoPublicProfileClient:
    """Direct, consent-gated Mihomo request. It never logs the UID or raw response."""

    BASE_URL = "https://api.mihomo.me/sr_info_parsed"
    PROVIDER_ID = "mihomo-public-profile"
    _UID_RE = re.compile(r"^\d{8,12}$")

    def __init__(self, *, timeout_seconds: float = 15.0, language: str = "cn") -> None:
        if not 1 <= timeout_seconds <= 60:
            raise ValueError("timeout must be between 1 and 60 seconds")
        if language not in {"cn", "en", "cht", "de", "es", "fr", "id", "jp", "kr", "pt", "ru", "th", "vi"}:
            raise ValueError("unsupported response language")
        self._timeout = timeout_seconds
        self._language = language

    @staticmethod
    def _decode_response(raw: bytes) -> dict[str, object]:
        try:
            payload = json.loads(
                raw.decode("utf-8"),
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError, RecursionError):
            raise ProfileRequestError("public profile response was not valid JSON") from None
        if not isinstance(payload, dict):
            raise ProfileRequestError("public profile response has an unsupported shape")
        return payload

    def fetch(self, selection: PublicProfileSelection) -> ImportProposal:
        if not selection.confirmed_by_user:
            raise PermissionError("player confirmation is required before a UID request")
        if selection.provider_id != self.PROVIDER_ID:
            raise ValueError("selected provider does not match this adapter")
        if not self._UID_RE.fullmatch(selection.uid):
            raise ValueError("UID format is invalid")
        if not selection.server_label.strip():
            raise ValueError("server/region must be explicitly selected")

        url = f"{self.BASE_URL}/{urllib.parse.quote(selection.uid, safe='')}?lang={self._language}&version=v2"
        request = urllib.request.Request(
            url,
            headers={"Accept": "application/json", "User-Agent": "StarHelp-Desktop/0.1"},
            method="GET",
        )
        try:
            opener = urllib.request.build_opener(_RejectRedirects())
            with opener.open(request, timeout=self._timeout) as response:
                if response.status != 200:
                    raise ProfileRequestError("public profile service returned an error", status_code=response.status)
                raw = response.read(4 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as exc:
            raise ProfileRequestError("public profile service rejected the request", status_code=exc.code) from None
        except (urllib.error.URLError, TimeoutError, OSError):
            raise ProfileRequestError("public profile service is unavailable") from None
        if len(raw) > 4 * 1024 * 1024:
            raise ProfileRequestError("public profile response exceeded the size limit")
        return self.to_preview(self._decode_response(raw))

    def to_preview(self, payload: object) -> ImportProposal:
        """Normalize only a small allowlist; absent showcase fields never mean not-owned."""
        if not isinstance(payload, dict):
            raise ProfileRequestError("public profile response has an unsupported shape")
        characters = payload.get("characters")
        if not isinstance(characters, list):
            raise ProfileRequestError("public profile response lacks the documented character list")

        observed = datetime.now(UTC)
        fields: dict[str, FieldFact] = {}
        ownership: dict[str, Ownership] = {}
        equipment: list[EquipmentInstance] = []
        covered: set[str] = set()
        warnings = [
            "角色列表是公开展示档案；未展示角色和物品的所有权保持未知。服务返回的总数不构成逐项清单。",
            "物品身份尚未被来源证明；同一类型 ID、词条或属性不作副本身份依据。",
        ]
        for character in characters:
            if not isinstance(character, dict):
                continue
            character_id = _public_identifier(character.get("id"))
            if character_id is None:
                continue
            ownership[character_id] = Ownership.OWNED
            ownership_path = f"ownership:{character_id}"
            covered.add(ownership_path)
            for public_key, local_name in (("level", "level"), ("rank", "eidolon")):
                value = character.get(public_key)
                if _finite_integer(value):
                    path = f"character:{character_id}.{local_name}"
                    fields[path] = FieldFact(
                        value=value, status=FieldStatus.NEEDS_REVIEW,
                        source_kind=SourceKind.PUBLIC_PROFILE, source_id=self.PROVIDER_ID,
                        observed_at=observed, scope="displayed-character",
                    )
                    covered.add(path)
            attributes = character.get("attributes", [])
            if not isinstance(attributes, list):
                attributes = []
            for attribute in attributes:
                if not isinstance(attribute, dict):
                    continue
                field_name = _public_text(attribute.get("field"))
                value = attribute.get("value")
                if field_name is not None and _finite_number(value):
                    path = f"character:{character_id}.stat:{field_name}"
                    fields[path] = FieldFact(
                        value=value, status=FieldStatus.NEEDS_REVIEW,
                        source_kind=SourceKind.PUBLIC_PROFILE, source_id=self.PROVIDER_ID,
                        observed_at=observed, scope="showcase-base-attributes",
                    )
                    covered.add(path)
            skills = character.get("skills", [])
            if not isinstance(skills, list):
                skills = []
            for skill in skills:
                if not isinstance(skill, dict):
                    continue
                skill_id, level = skill.get("id"), skill.get("level")
                public_skill_id = _public_identifier(skill_id)
                if public_skill_id is not None and _finite_integer(level):
                    path = f"character:{character_id}.skill:{public_skill_id}"
                    fields[path] = FieldFact(
                        value=level, status=FieldStatus.NEEDS_REVIEW,
                        source_kind=SourceKind.PUBLIC_PROFILE, source_id=self.PROVIDER_ID,
                        observed_at=observed, scope="showcase-display",
                    )
                    covered.add(path)
            equipment.extend(self._equipment_for(character, character_id, observed))

        if not characters:
            warnings.append("服务返回空展示列表；这不能证明账号没有角色。")
        return ImportProposal.create(
            source_kind=SourceKind.PUBLIC_PROFILE,
            source_id=self.PROVIDER_ID,
            observed_at=observed,
            fields=fields,
            ownership=ownership,
            equipment=tuple(equipment),
            coverage=frozenset(covered),
            warnings=tuple(warnings),
        )

    def _equipment_for(
        self, character: dict[str, object], character_id: str, observed: datetime
    ) -> list[EquipmentInstance]:
        result: list[EquipmentInstance] = []
        candidates: list[tuple[str, object]] = []
        light_cone = character.get("light_cone")
        if isinstance(light_cone, dict):
            candidates.append(("light_cone", light_cone))
        relics = character.get("relics")
        if isinstance(relics, list):
            candidates.extend(("relic", item) for item in relics)
        for slot, raw in candidates:
            if not isinstance(raw, dict):
                continue
            type_id = _public_identifier(raw.get("id") or raw.get("type_id"))
            if type_id is None:
                continue
            # Do not interpret an API item/type ID, identical stats, or a hash as a copy ID.
            result.append(
                EquipmentInstance(
                    local_instance_id=uuid4(),
                    public_type_id=type_id,
                    slot=(self._relic_slot(raw) if slot == "relic" else slot),
                    identity=EquipmentIdentity.AMBIGUOUS,
                    owner_character_id=character_id,
                    facts=self._equipment_facts(raw, slot, observed),
                )
            )
        return result

    def _equipment_facts(
        self, item: dict[str, object], slot: str, observed: datetime
    ) -> dict[str, FieldFact]:
        facts: dict[str, FieldFact] = {}
        for key in ("level", "rank", "promotion", "rarity", "set_id"):
            value = item.get(key)
            valid_value = (
                _finite_integer(value)
                if key != "set_id"
                else _public_identifier(value) is not None
            )
            if valid_value:
                facts[key] = FieldFact(
                    value=value, status=FieldStatus.NEEDS_REVIEW,
                    source_kind=SourceKind.PUBLIC_PROFILE, source_id=self.PROVIDER_ID,
                    observed_at=observed, scope=f"showcase-equipped-{slot}",
                )
        attributes = item.get("attributes")
        if isinstance(attributes, list):
            for index, attribute in enumerate(attributes):
                if not isinstance(attribute, dict):
                    continue
                self._append_affix_facts(
                    facts, f"attribute:{index}", attribute, observed, slot
                )
        main_affix = item.get("main_affix")
        if isinstance(main_affix, dict):
            self._append_affix_facts(facts, "main_affix", main_affix, observed, slot)
        sub_affixes = item.get("sub_affix")
        if isinstance(sub_affixes, list):
            for index, affix in enumerate(sub_affixes):
                if isinstance(affix, dict):
                    self._append_affix_facts(facts, f"sub_affix:{index}", affix, observed, slot)
        return facts

    @staticmethod
    def _relic_slot(item: dict[str, object]) -> str:
        slot_type = item.get("type")
        if not _finite_integer(slot_type):
            return "relic:unknown"
        return f"relic:{slot_type}"

    def _append_affix_facts(
        self,
        facts: dict[str, FieldFact],
        prefix: str,
        affix: dict[str, object],
        observed: datetime,
        slot: str,
    ) -> None:
        if any(
            key in affix and _public_text(affix[key]) is None
            for key in ("field", "type")
        ):
            return
        for key in ("field", "type", "value", "percent", "count", "step"):
            value = affix.get(key)
            valid_value = (
                _public_text(value) is not None
                if key in {"field", "type"}
                else isinstance(value, bool)
                if key == "percent"
                else _finite_number(value)
            )
            if valid_value:
                facts[f"{prefix}.{key}"] = FieldFact(
                    value=value, status=FieldStatus.NEEDS_REVIEW,
                    source_kind=SourceKind.PUBLIC_PROFILE, source_id=self.PROVIDER_ID,
                    observed_at=observed, scope=f"showcase-equipped-{slot}",
                )
