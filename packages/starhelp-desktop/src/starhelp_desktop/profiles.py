from __future__ import annotations

import re
import threading
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from .equipment import EquipmentIdentityService
from .imports import confirm_import
from .lifecycle import ProfileLifecycle
from .merge import MergeResult, merge_import
from .models import (
    AccountSnapshot,
    EquipmentIdentity,
    EquipmentInstance,
    FieldFact,
    FieldStatus,
    ImportProposal,
    Ownership,
    ProfileAuthorization,
    SourceKind,
    utc_now,
)
from .storage import EncryptedPrivateStore


@dataclass(frozen=True, slots=True)
class ProfileSummary:
    profile_id: UUID
    label: str
    provider_id: str
    server_label: str
    generation: int
    created_at: datetime
    auto_refresh: bool = False


def _fact_to_dict(fact: FieldFact) -> dict[str, Any]:
    return {
        "value": fact.value,
        "status": fact.status.value,
        "source_kind": fact.source_kind.value,
        "source_id": fact.source_id,
        "observed_at": fact.observed_at.isoformat(),
        "confirmed_at": fact.confirmed_at.isoformat() if fact.confirmed_at else None,
        "scope": fact.scope,
    }


def _fact_from_dict(data: dict[str, Any]) -> FieldFact:
    return FieldFact(
        value=data["value"],
        status=FieldStatus(data["status"]),
        source_kind=SourceKind(data["source_kind"]),
        source_id=str(data["source_id"]),
        observed_at=datetime.fromisoformat(data["observed_at"]),
        confirmed_at=datetime.fromisoformat(data["confirmed_at"]) if data.get("confirmed_at") else None,
        scope=data.get("scope"),
    )


def _snapshot_to_dict(snapshot: AccountSnapshot) -> dict[str, Any]:
    return {
        "schema_id": "AccountSnapshot",
        "schema_version": "0.1-draft",
        "profile_id": str(snapshot.profile_id),
        "snapshot_id": str(snapshot.snapshot_id),
        "revision": snapshot.revision,
        "generated_at": snapshot.generated_at.isoformat(),
        "fields": {path: _fact_to_dict(value) for path, value in snapshot.fields.items()},
        "ownership": {key: value.value for key, value in snapshot.ownership.items()},
        "coverage": sorted(snapshot.coverage),
        "equipment": [
            {
                "local_instance_id": str(item.local_instance_id),
                "public_type_id": item.public_type_id,
                "slot": item.slot,
                "identity": item.identity.value,
                "owner_character_id": item.owner_character_id,
                "facts": {path: _fact_to_dict(value) for path, value in item.facts.items()},
            }
            for item in snapshot.equipment
        ],
    }


def _snapshot_from_dict(data: dict[str, Any]) -> AccountSnapshot:
    if data.get("schema_id") != "AccountSnapshot" or data.get("schema_version") != "0.1-draft":
        raise ValueError("unsupported encrypted snapshot schema")
    equipment = tuple(
        EquipmentInstance(
            local_instance_id=UUID(item["local_instance_id"]),
            public_type_id=str(item["public_type_id"]),
            slot=str(item["slot"]),
            identity=EquipmentIdentity(item["identity"]),
            owner_character_id=item.get("owner_character_id"),
            facts={path: _fact_from_dict(value) for path, value in item.get("facts", {}).items()},
        )
        for item in data.get("equipment", [])
    )
    return AccountSnapshot(
        profile_id=UUID(data["profile_id"]),
        snapshot_id=UUID(data["snapshot_id"]),
        revision=int(data["revision"]),
        generated_at=datetime.fromisoformat(data["generated_at"]),
        fields={path: _fact_from_dict(value) for path, value in data.get("fields", {}).items()},
        ownership={key: Ownership(value) for key, value in data.get("ownership", {}).items()},
        equipment=equipment,
        coverage=frozenset(data.get("coverage", [])),
    )


class ProfileRepository:
    """Stores authorization metadata and the single current snapshot as DPAPI objects."""

    CATALOG_KEY = "profile-catalog"

    def __init__(self, store: EncryptedPrivateStore, lifecycle: ProfileLifecycle) -> None:
        self._store = store
        self._lifecycle = lifecycle
        self._lock = threading.RLock()
        self._catalog: dict[UUID, ProfileSummary] = {}
        self._load_catalog()

    def _load_catalog(self) -> None:
        try:
            raw = self._store.load(self.CATALOG_KEY)
        except FileNotFoundError:
            return
        for item in raw.get("profiles", []):
            summary = ProfileSummary(
                profile_id=UUID(item["profile_id"]),
                label=str(item["label"]),
                provider_id=str(item["provider_id"]),
                server_label=str(item["server_label"]),
                generation=int(item["generation"]),
                created_at=datetime.fromisoformat(item["created_at"]),
                auto_refresh=bool(item.get("auto_refresh", False)),
            )
            self._catalog[summary.profile_id] = summary
            self._lifecycle.authorize(ProfileAuthorization(
                profile_id=summary.profile_id,
                active=True,
                generation=summary.generation,
                source_id=summary.provider_id,
                scopes=frozenset({"local_snapshot", "analysis", "reports"}),
                confirmed_at=summary.created_at,
            ))

    def list_profiles(self) -> tuple[ProfileSummary, ...]:
        return tuple(sorted(self._catalog.values(), key=lambda item: item.created_at))

    def create_from_confirmed_import(
        self,
        *,
        label: str,
        provider_id: str,
        server_label: str,
        proposal: ImportProposal,
    ) -> ProfileSummary:
        if not proposal.confirmed:
            raise PermissionError("the import preview has not been confirmed")
        summary = self.begin_profile(label=label, provider_id=provider_id, server_label=server_label)
        try:
            self.save_confirmed_import(summary.profile_id, summary.generation, proposal)
        except Exception:
            self.revoke(summary.profile_id)
            raise
        return summary

    def begin_profile(self, *, label: str, provider_id: str, server_label: str) -> ProfileSummary:
        """Persist per-profile authorization before starting an asynchronous source request."""
        if not label.strip() or not server_label.strip():
            raise ValueError("profile label and server/region are required")
        profile_id = uuid4()
        summary = ProfileSummary(
            profile_id=profile_id,
            label=label.strip(),
            provider_id=provider_id,
            server_label=server_label.strip(),
            generation=1,
            created_at=utc_now(),
        )
        self._catalog[profile_id] = summary
        try:
            self._save_catalog()
            self._lifecycle.authorize(ProfileAuthorization(
                profile_id=profile_id,
                active=True,
                generation=summary.generation,
                source_id=provider_id,
                scopes=frozenset({"profile_read", "local_snapshot", "analysis", "reports"}),
                confirmed_at=summary.created_at,
            ))
        except Exception:
            self._catalog.pop(profile_id, None)
            self._store.delete_profile(profile_id)
            self._save_catalog()
            raise
        return summary

    def preview_merge(self, profile_id: UUID, generation: int, proposal: ImportProposal) -> MergeResult:
        self._lifecycle.require_active(profile_id, generation)
        if not proposal.confirmed:
            raise PermissionError("the import preview has not been confirmed")
        try:
            current = self.load_snapshot(profile_id, generation)
        except FileNotFoundError:
            current = AccountSnapshot(
                profile_id=profile_id, snapshot_id=uuid4(), revision=0, generated_at=utc_now(),
            )
        return merge_import(current, proposal)

    def save_confirmed_import(
        self,
        profile_id: UUID,
        generation: int,
        proposal: ImportProposal,
        *,
        conflict_choices: dict[str, str] | None = None,
    ) -> MergeResult:
        with self._lock:
            result = self.preview_merge(profile_id, generation, proposal)
            if result.conflicts and not conflict_choices:
                raise ValueError("import has unresolved field conflicts")
            if result.conflicts:
                # Re-run from the still-current snapshot with explicit player choices.
                try:
                    current = self.load_snapshot(profile_id, generation)
                except FileNotFoundError:
                    current = AccountSnapshot(
                        profile_id=profile_id, snapshot_id=uuid4(), revision=0,
                        generated_at=utc_now(),
                    )
                result = merge_import(current, proposal, confirmed_conflict_values=conflict_choices)
            self._store.save(self._snapshot_key(profile_id), _snapshot_to_dict(result.snapshot))
            return result

    def load_snapshot(self, profile_id: UUID, generation: int) -> AccountSnapshot:
        self._lifecycle.require_active(profile_id, generation)
        data = self._store.load(self._snapshot_key(profile_id))
        snapshot = _snapshot_from_dict(data)
        if snapshot.profile_id != profile_id:
            raise ValueError("snapshot belongs to a different profile")
        return snapshot

    def confirm_equipment_instance(
        self, profile_id: UUID, generation: int, local_instance_id: UUID
    ) -> AccountSnapshot:
        """Persist one player's explicit equipment-instance identity decision."""
        with self._lock:
            snapshot = self.load_snapshot(profile_id, generation)
            confirmed = EquipmentIdentityService().confirm_instance(snapshot, local_instance_id)
            if confirmed is not snapshot:
                self._store.save(self._snapshot_key(profile_id), _snapshot_to_dict(confirmed))
            return confirmed

    def set_auto_refresh(
        self,
        profile_id: UUID,
        enabled: bool,
        *,
        separately_confirmed: bool,
        uid: str | None = None,
    ) -> None:
        if enabled and not separately_confirmed:
            raise PermissionError("auto-refresh requires separate per-profile confirmation")
        with self._lock:
            summary = self._catalog[profile_id]
            self._lifecycle.require_active(profile_id, summary.generation)
            if enabled:
                if summary.provider_id != "mihomo-public-profile":
                    raise ValueError("automatic refresh is supported only for Mihomo profiles")
                if uid is None or re.fullmatch(r"\d{8,12}", uid) is None:
                    raise ValueError("a valid UID is required for automatic refresh")
                last_attempt_at = None
                if summary.auto_refresh:
                    try:
                        previous = self._store.load(self._refresh_key(profile_id))
                    except FileNotFoundError:
                        previous = {}
                    if previous.get("uid") == uid:
                        previous_attempt = previous.get("last_attempt_at")
                        if isinstance(previous_attempt, str):
                            try:
                                parsed_attempt = datetime.fromisoformat(previous_attempt)
                            except ValueError:
                                parsed_attempt = None
                            if parsed_attempt is not None and parsed_attempt.tzinfo is not None:
                                last_attempt_at = previous_attempt
                self._store.save(self._refresh_key(profile_id), {
                    "schema_id": "ProfileRefreshAuthorization",
                    "schema_version": "0.1-draft",
                    "uid": uid,
                    "last_attempt_at": last_attempt_at,
                })
            updated = ProfileSummary(
                profile_id=summary.profile_id,
                label=summary.label,
                provider_id=summary.provider_id,
                server_label=summary.server_label,
                generation=summary.generation,
                created_at=summary.created_at,
                auto_refresh=enabled,
            )
            self._catalog[profile_id] = updated
            try:
                self._save_catalog()
            except Exception:
                self._catalog[profile_id] = summary
                if enabled:
                    self._store.delete_key(self._refresh_key(profile_id))
                raise
            if not enabled:
                self._store.delete_key(self._refresh_key(profile_id))

    def auto_refresh_config(self, profile_id: UUID, generation: int) -> dict[str, str | None] | None:
        self._lifecycle.require_active(profile_id, generation)
        summary = self._catalog.get(profile_id)
        if summary is None or not summary.auto_refresh:
            return None
        try:
            config = self._store.load(self._refresh_key(profile_id))
        except FileNotFoundError:
            return None
        if (config.get("schema_id") != "ProfileRefreshAuthorization"
                or config.get("schema_version") != "0.1-draft"):
            raise ValueError("unsupported automatic refresh authorization")
        uid = config.get("uid")
        last_attempt_at = config.get("last_attempt_at")
        if not isinstance(uid, str) or re.fullmatch(r"\d{8,12}", uid) is None:
            raise ValueError("stored automatic refresh UID is invalid")
        if last_attempt_at is not None and not isinstance(last_attempt_at, str):
            raise ValueError("stored automatic refresh timestamp is invalid")
        return {"uid": uid, "last_attempt_at": last_attempt_at}

    def record_auto_refresh_attempt(
        self, profile_id: UUID, generation: int, attempted_at: datetime
    ) -> None:
        with self._lock:
            config = self.auto_refresh_config(profile_id, generation)
            if config is None:
                raise PermissionError("automatic refresh is not enabled for this profile")
            raw = self._store.load(self._refresh_key(profile_id))
            raw["last_attempt_at"] = attempted_at.isoformat()
            self._store.save(self._refresh_key(profile_id), raw)

    def revoke(self, profile_id: UUID) -> None:
        # Disable in memory first, then durably remove the catalog reference before erasing blobs.
        # If catalog persistence fails, the profile stays disabled for this process and the error
        # reaches the caller; data is not deleted until a restart can no longer re-authorize it.
        with self._lock:
            self._lifecycle.invalidate(profile_id)
            self._catalog.pop(profile_id, None)
            self._save_catalog()
            self._lifecycle.erase_private_data(profile_id)

    def _save_catalog(self) -> None:
        profiles = [
            {
                "profile_id": str(item.profile_id),
                "label": item.label,
                "provider_id": item.provider_id,
                "server_label": item.server_label,
                "generation": item.generation,
                "created_at": item.created_at.isoformat(),
                "auto_refresh": item.auto_refresh,
            }
            for item in self._catalog.values()
        ]
        self._store.save(self.CATALOG_KEY, {"schema_id": "ProfileCatalog", "profiles": profiles})

    @staticmethod
    def _snapshot_key(profile_id: UUID) -> str:
        return f"profile-{profile_id.hex}-snapshot"

    @staticmethod
    def _refresh_key(profile_id: UUID) -> str:
        return f"profile-{profile_id.hex}-refresh"
