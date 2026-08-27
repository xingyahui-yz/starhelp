from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True, slots=True)
class ModelRequest:
    schema_version: str
    game_version: str
    account_payload: dict[str, object]
    stage_payload: dict[str, object]
    source_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ModelResponse:
    structured_plan: dict[str, object]
    source_ids: tuple[str, ...]
    model_id: str


class ModelProvider(Protocol):
    """Provider returns data only. It deliberately has no input/execution capability."""

    def create_plan(self, request: ModelRequest) -> ModelResponse: ...

