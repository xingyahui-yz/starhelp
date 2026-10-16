from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any
from uuid import UUID, uuid4


def utc_now() -> datetime:
    return datetime.now(UTC)


class SourceKind(StrEnum):
    PUBLIC_PROFILE = "public_profile"
    STRUCTURED_IMPORT = "structured_import"
    OCR = "ocr"
    MANUAL = "manual"


class FieldStatus(StrEnum):
    CONFIRMED = "confirmed"
    NEEDS_REVIEW = "needs_review"
    CONFLICT = "conflict"
    STALE = "stale"


class Ownership(StrEnum):
    OWNED = "owned"
    NOT_OWNED = "not_owned"
    UNKNOWN = "unknown"


class EquipmentIdentity(StrEnum):
    SOURCE_CONFIRMED = "source_confirmed"
    PLAYER_CONFIRMED = "player_confirmed"
    AMBIGUOUS = "ambiguous"
    UNCONFIRMED = "unconfirmed"


@dataclass(frozen=True, slots=True)
class ProfileAuthorization:
    profile_id: UUID
    active: bool
    generation: int
    source_id: str
    scopes: frozenset[str]
    confirmed_at: datetime
    revoked_at: datetime | None = None

    def __post_init__(self) -> None:
        if self.generation < 1:
            raise ValueError("authorization generation must be positive")
        if self.active and self.revoked_at is not None:
            raise ValueError("active authorization cannot have a revoked timestamp")
        if not self.active and self.revoked_at is None:
            raise ValueError("inactive authorization must record revocation time")


@dataclass(frozen=True, slots=True)
class FieldFact:
    value: Any
    status: FieldStatus
    source_kind: SourceKind
    source_id: str
    observed_at: datetime
    confirmed_at: datetime | None = None
    scope: str | None = None

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None:
            raise ValueError("observed_at must be timezone aware")
        if self.confirmed_at is not None and self.confirmed_at.tzinfo is None:
            raise ValueError("confirmed_at must be timezone aware")


@dataclass(frozen=True, slots=True)
class EquipmentInstance:
    local_instance_id: UUID
    public_type_id: str
    slot: str
    identity: EquipmentIdentity
    owner_character_id: str | None
    facts: dict[str, FieldFact] = field(default_factory=dict)

    @property
    def may_be_reassigned(self) -> bool:
        return self.identity in {
            EquipmentIdentity.SOURCE_CONFIRMED,
            EquipmentIdentity.PLAYER_CONFIRMED,
        }


@dataclass(frozen=True, slots=True)
class AccountSnapshot:
    profile_id: UUID
    snapshot_id: UUID
    revision: int
    generated_at: datetime
    fields: dict[str, FieldFact] = field(default_factory=dict)
    ownership: dict[str, Ownership] = field(default_factory=dict)
    equipment: tuple[EquipmentInstance, ...] = ()
    coverage: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if self.revision < 0:
            raise ValueError("snapshot revision cannot be negative")
        if self.generated_at.tzinfo is None:
            raise ValueError("generated_at must be timezone aware")
        instance_ids = [item.local_instance_id for item in self.equipment]
        if len(instance_ids) != len(set(instance_ids)):
            raise ValueError("duplicate local equipment instance identity")


@dataclass(frozen=True, slots=True)
class ImportProposal:
    """A preview candidate; it is not persisted until the player confirms it."""

    proposal_id: UUID
    source_kind: SourceKind
    source_id: str
    observed_at: datetime
    fields: dict[str, FieldFact]
    ownership: dict[str, Ownership]
    equipment: tuple[EquipmentInstance, ...]
    coverage: frozenset[str]
    warnings: tuple[str, ...] = ()
    image_buffer: bytes | None = None
    confirmed: bool = False

    @classmethod
    def create(
        cls,
        *,
        source_kind: SourceKind,
        source_id: str,
        observed_at: datetime,
        fields: dict[str, FieldFact],
        ownership: dict[str, Ownership] | None = None,
        equipment: tuple[EquipmentInstance, ...] = (),
        coverage: frozenset[str] | None = None,
        warnings: tuple[str, ...] = (),
        image_buffer: bytes | None = None,
    ) -> ImportProposal:
        return cls(
            proposal_id=uuid4(),
            source_kind=source_kind,
            source_id=source_id,
            observed_at=observed_at,
            fields=fields,
            ownership=ownership or {},
            equipment=equipment,
            coverage=coverage if coverage is not None else frozenset(fields),
            warnings=warnings,
            image_buffer=image_buffer,
        )
