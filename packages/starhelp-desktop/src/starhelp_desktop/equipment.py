from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from .models import AccountSnapshot, EquipmentIdentity, FieldFact, FieldStatus


class EquipmentMergeConflictError(ValueError):
    def __init__(self, conflicts: tuple[EquipmentMergeConflict, ...]) -> None:
        self.conflicts = conflicts
        fields = ", ".join(conflict.path for conflict in conflicts)
        super().__init__(f"equipment link has unresolved field conflicts: {fields}")


@dataclass(frozen=True, slots=True)
class EquipmentMergeConflict:
    path: str
    existing: object
    incoming: object


class EquipmentIdentityService:
    """Only explicit player actions establish local equipment-copy identity."""

    def confirm_instance(self, snapshot: AccountSnapshot, local_instance_id: UUID) -> AccountSnapshot:
        target = next((item for item in snapshot.equipment
                       if item.local_instance_id == local_instance_id), None)
        if target is None:
            raise KeyError("equipment instance was not found")
        if target.identity is EquipmentIdentity.SOURCE_CONFIRMED:
            return snapshot
        equipment = tuple(
            replace(item, identity=EquipmentIdentity.PLAYER_CONFIRMED)
            if item.local_instance_id == local_instance_id else item
            for item in snapshot.equipment
        )
        return replace(snapshot, snapshot_id=uuid4(), revision=snapshot.revision + 1,
                       generated_at=datetime.now(UTC), equipment=equipment)

    def link_import_to_existing(
        self,
        snapshot: AccountSnapshot,
        *,
        imported_instance_id: UUID,
        existing_instance_id: UUID,
        player_confirmed_same_copy: bool,
        conflict_choices: dict[str, str] | None = None,
    ) -> AccountSnapshot:
        if not player_confirmed_same_copy:
            raise PermissionError("player confirmation is required to link equipment copies")
        incoming = next((item for item in snapshot.equipment
                         if item.local_instance_id == imported_instance_id), None)
        existing = next((item for item in snapshot.equipment
                         if item.local_instance_id == existing_instance_id), None)
        if incoming is None or existing is None:
            raise KeyError("equipment instance was not found")
        if incoming.local_instance_id == existing.local_instance_id:
            raise ValueError("cannot link an item to itself")
        if incoming.public_type_id != existing.public_type_id:
            raise ValueError("equipment type mismatch")
        if incoming.slot != existing.slot:
            raise ValueError("equipment slot mismatch")
        conflicts: list[EquipmentMergeConflict] = []
        if (existing.owner_character_id is not None and incoming.owner_character_id is not None
                and existing.owner_character_id != incoming.owner_character_id):
            conflicts.append(EquipmentMergeConflict(
                "owner_character_id", existing.owner_character_id, incoming.owner_character_id
            ))
        for path in sorted(existing.facts.keys() & incoming.facts.keys()):
            if existing.facts[path].value != incoming.facts[path].value:
                conflicts.append(EquipmentMergeConflict(
                    path, existing.facts[path], incoming.facts[path]
                ))
        choices = conflict_choices or {}
        conflict_paths = {conflict.path for conflict in conflicts}
        if set(choices) - conflict_paths:
            raise ValueError("equipment conflict choices contain an unknown field")
        unresolved = tuple(conflict for conflict in conflicts if conflict.path not in choices)
        if unresolved:
            raise EquipmentMergeConflictError(unresolved)
        for conflict in conflicts:
            if choices[conflict.path] not in {"existing", "incoming"}:
                raise ValueError(f"invalid equipment conflict choice for {conflict.path}")

        merged_facts = dict(existing.facts)
        for path, incoming_fact in incoming.facts.items():
            old_fact = existing.facts.get(path)
            if old_fact is None or incoming_fact.observed_at > old_fact.observed_at:
                merged_facts[path] = incoming_fact
            if old_fact is not None and old_fact.value != incoming_fact.value:
                chosen = old_fact if choices[path] == "existing" else incoming_fact
                merged_facts[path] = FieldFact(
                    value=chosen.value,
                    status=FieldStatus.CONFIRMED,
                    source_kind=chosen.source_kind,
                    source_id=chosen.source_id,
                    observed_at=chosen.observed_at,
                    confirmed_at=datetime.now(UTC),
                    scope=chosen.scope,
                )
        owner = existing.owner_character_id or incoming.owner_character_id
        if "owner_character_id" in choices:
            owner = (existing.owner_character_id if choices["owner_character_id"] == "existing"
                     else incoming.owner_character_id)
        linked = replace(
            existing,
            identity=EquipmentIdentity.PLAYER_CONFIRMED,
            owner_character_id=owner,
            facts=merged_facts,
        )
        remaining = tuple(
            linked if item.local_instance_id == existing_instance_id
            else item for item in snapshot.equipment
            if item.local_instance_id != imported_instance_id
        )
        return replace(snapshot, snapshot_id=uuid4(), revision=snapshot.revision + 1,
                       generated_at=datetime.now(UTC), equipment=remaining)
