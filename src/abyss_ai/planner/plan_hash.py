from __future__ import annotations

import hashlib
import json
from dataclasses import asdict
from enum import Enum
from typing import Any
from uuid import UUID

from abyss_ai.domain import BattlePlan


def _normalise(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, dict):
        return {key: _normalise(item) for key, item in sorted(value.items())}
    if isinstance(value, (list, tuple)):
        return [_normalise(item) for item in value]
    return value


def hash_plan(plan: BattlePlan) -> str:
    """Return a stable hash used by the one-time human approval."""
    payload = json.dumps(
        _normalise(asdict(plan)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()

