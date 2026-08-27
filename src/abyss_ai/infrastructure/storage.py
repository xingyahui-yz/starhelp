from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path


class LocalJsonStore:
    """Atomic local JSON storage with basic secret-field denial."""

    _KEY_PATTERN = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._-]{0,127}$")
    _FORBIDDEN_FIELDS = frozenset(
        {
            "password",
            "cookie",
            "cookies",
            "authorization",
            "api_key",
            "access_token",
            "refresh_token",
            "token",
            "uid",
            "raw_uid",
        }
    )

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        try:
            self.root.chmod(0o700)
        except OSError:
            pass

    def _path_for(self, key: str) -> Path:
        if not self._KEY_PATTERN.fullmatch(key):
            raise ValueError("invalid local store key")
        return self.root / f"{key}.json"

    def _reject_secrets(self, value: object, path: str = "$") -> None:
        if isinstance(value, dict):
            for key, item in value.items():
                if key.lower() in self._FORBIDDEN_FIELDS:
                    raise ValueError(f"sensitive field is forbidden at {path}.{key}")
                self._reject_secrets(item, f"{path}.{key}")
        elif isinstance(value, list):
            for index, item in enumerate(value):
                self._reject_secrets(item, f"{path}[{index}]")

    def save(self, key: str, value: dict[str, object]) -> Path:
        self._reject_secrets(value)
        destination = self._path_for(key)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{key}.", suffix=".tmp", dir=self.root
        )
        temporary = Path(temporary_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            try:
                temporary.chmod(0o600)
            except OSError:
                pass
            temporary.replace(destination)
            return destination
        except Exception:
            temporary.unlink(missing_ok=True)
            raise

    def load(self, key: str) -> dict[str, object]:
        with self._path_for(key).open(encoding="utf-8") as handle:
            value = json.load(handle)
        if not isinstance(value, dict):
            raise ValueError("stored JSON root must be an object")
        self._reject_secrets(value)
        return value
