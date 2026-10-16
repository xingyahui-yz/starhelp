from __future__ import annotations

import shutil
import threading
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID

from .models import ProfileAuthorization, utc_now
from .storage import EncryptedPrivateStore


@dataclass(slots=True)
class _Task:
    profile_id: UUID
    generation: int
    cancel: threading.Event


class ProfileLifecycle:
    """In-memory authorization gate plus immediate private-data revocation."""

    def __init__(self, store: EncryptedPrivateStore, temp_root: Path) -> None:
        self._store = store
        self._temp_root = temp_root.resolve()
        self._temp_root.mkdir(parents=True, exist_ok=True)
        self._authorizations: dict[UUID, ProfileAuthorization] = {}
        self._tasks: dict[UUID, list[_Task]] = {}
        self._lock = threading.RLock()

    def authorize(self, authorization: ProfileAuthorization) -> None:
        if not authorization.active:
            raise ValueError("cannot register inactive authorization")
        with self._lock:
            current = self._authorizations.get(authorization.profile_id)
            if current and authorization.generation <= current.generation:
                raise ValueError("authorization generation must increase")
            self._authorizations[authorization.profile_id] = authorization

    def is_active(self, profile_id: UUID, generation: int | None = None) -> bool:
        with self._lock:
            authorization = self._authorizations.get(profile_id)
            return bool(
                authorization
                and authorization.active
                and (generation is None or authorization.generation == generation)
            )

    def require_active(self, profile_id: UUID, generation: int | None = None) -> None:
        if not self.is_active(profile_id, generation):
            raise PermissionError("profile is not authorized for this operation")

    def register_task(self, profile_id: UUID, generation: int) -> threading.Event:
        with self._lock:
            self.require_active(profile_id, generation)
            task = _Task(profile_id, generation, threading.Event())
            self._tasks.setdefault(profile_id, []).append(task)
            return task.cancel

    def accepts_result(self, profile_id: UUID, generation: int) -> bool:
        return self.is_active(profile_id, generation)

    def revoke(self, profile_id: UUID) -> None:
        """Cancel work, invalidate generation, then erase all associated private files."""
        self.invalidate(profile_id)
        self.erase_private_data(profile_id)

    def invalidate(self, profile_id: UUID) -> None:
        """Immediately deny new work and reject late results without touching disk."""
        with self._lock:
            previous = self._authorizations.get(profile_id)
            next_generation = (previous.generation + 1) if previous else 1
            self._authorizations[profile_id] = ProfileAuthorization(
                profile_id=profile_id,
                active=False,
                generation=next_generation,
                source_id=previous.source_id if previous else "revoked",
                scopes=frozenset(),
                confirmed_at=previous.confirmed_at if previous else utc_now(),
                revoked_at=utc_now(),
            )
            for task in self._tasks.pop(profile_id, []):
                task.cancel.set()

    def erase_private_data(self, profile_id: UUID) -> None:
        self._store.delete_profile(profile_id)
        profile_temp = self._temp_root / profile_id.hex
        if profile_temp.exists():
            shutil.rmtree(profile_temp)
