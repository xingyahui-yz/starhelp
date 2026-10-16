from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from .models import AccountSnapshot, FieldFact, FieldStatus, ImportProposal, Ownership, utc_now
from uuid import uuid4


@dataclass(frozen=True, slots=True)
class FieldConflict:
    field_path: str
    existing: FieldFact
    incoming: FieldFact


@dataclass(frozen=True, slots=True)
class MergeResult:
    snapshot: AccountSnapshot
    conflicts: tuple[FieldConflict, ...]
    retained_uncovered: frozenset[str]


def merge_import(
    current: AccountSnapshot,
    proposal: ImportProposal,
    *,
    confirmed_conflict_values: dict[str, str] | None = None,
) -> MergeResult:
    """Merge only fields explicitly covered by this import; never infer absence."""
    if not proposal.confirmed:
        raise PermissionError("import preview must be explicitly confirmed before merge")
    confirmed = confirmed_conflict_values or {}
    merged_fields = dict(current.fields)
    conflicts: list[FieldConflict] = []

    for path in proposal.coverage:
        incoming = proposal.fields.get(path)
        if incoming is None:
            # A source can assert that it checked a field and found no value.
            # Missing values are represented explicitly as a fact, never as deletion.
            continue
        old = current.fields.get(path)
        if old is None:
            merged_fields[path] = incoming
        elif old.value == incoming.value:
            merged_fields[path] = incoming
        elif old.source_kind == incoming.source_kind and old.source_id == incoming.source_id \
                and incoming.observed_at >= old.observed_at:
            # A later, player-confirmed observation from the same source is a refresh, not a
            # cross-source conflict. The source's actual coverage still gates this update.
            merged_fields[path] = incoming
        elif path in confirmed:
            choices = {"existing": old, "incoming": incoming}
            if confirmed[path] not in choices:
                raise ValueError(f"invalid conflict choice for {path}")
            chosen = choices[confirmed[path]]
            merged_fields[path] = FieldFact(
                value=chosen.value,
                status=FieldStatus.CONFIRMED,
                source_kind=chosen.source_kind,
                source_id=chosen.source_id,
                observed_at=chosen.observed_at,
                confirmed_at=datetime.now(UTC),
                scope=chosen.scope,
            )
        else:
            conflicts.append(FieldConflict(path, old, incoming))
            # Keep the last accepted value visible until the player resolves it.

    merged_ownership = dict(current.ownership)
    for character_id, incoming_state in proposal.ownership.items():
        key = f"ownership:{character_id}"
        if key not in proposal.coverage:
            continue
        old_state = current.ownership.get(character_id, Ownership.UNKNOWN)
        if old_state is Ownership.UNKNOWN or old_state is incoming_state:
            merged_ownership[character_id] = incoming_state
        elif incoming_state is not Ownership.UNKNOWN:
            if key in confirmed:
                choices = {"existing": old_state, "incoming": incoming_state}
                if confirmed[key] not in choices:
                    raise ValueError(f"invalid conflict choice for {key}")
                merged_ownership[character_id] = choices[confirmed[key]]
                continue
            old_fact = FieldFact(old_state.value, FieldStatus.CONFIRMED, proposal.source_kind,
                                 "existing-snapshot", current.generated_at)
            new_fact = FieldFact(incoming_state.value, FieldStatus.CONFIRMED,
                                 proposal.source_kind, proposal.source_id, proposal.observed_at)
            conflicts.append(FieldConflict(key, old_fact, new_fact))

    existing_equipment = {item.local_instance_id: item for item in current.equipment}
    # No matching by type/stats/hash: only a confirmed local identity can update an instance.
    for item in proposal.equipment:
        if item.local_instance_id in existing_equipment:
            existing_equipment[item.local_instance_id] = item
        else:
            existing_equipment[item.local_instance_id] = item

    retained = frozenset(current.coverage - proposal.coverage)
    snapshot = AccountSnapshot(
        profile_id=current.profile_id,
        snapshot_id=uuid4(),
        revision=current.revision + 1,
        generated_at=utc_now(),
        fields=merged_fields,
        ownership=merged_ownership,
        equipment=tuple(existing_equipment.values()),
        coverage=current.coverage | proposal.coverage,
    )
    return MergeResult(snapshot, tuple(conflicts), retained)
