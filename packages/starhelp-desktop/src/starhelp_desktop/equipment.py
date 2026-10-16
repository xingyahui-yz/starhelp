from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from uuid import UUID, uuid4

from .models import AccountSnapshot, EquipmentIdentity


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
        # Merge only after the player's explicit same-copy decision. Retain source facts from the
        # incoming observation while preserving the already-confirmed local identity.
        linked = replace(
            existing,
            identity=EquipmentIdentity.PLAYER_CONFIRMED,
            owner_character_id=incoming.owner_character_id,
            facts={**existing.facts, **incoming.facts},
        )
        remaining = tuple(
            linked if item.local_instance_id == existing_instance_id
            else item for item in snapshot.equipment
            if item.local_instance_id != imported_instance_id
        )
        return replace(snapshot, snapshot_id=uuid4(), revision=snapshot.revision + 1,
                       generated_at=datetime.now(UTC), equipment=remaining)
