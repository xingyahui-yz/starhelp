from __future__ import annotations

import json
import re
from dataclasses import dataclass


_UID = re.compile(r"(?<!\d)\d{8,12}(?!\d)")
_CONTROL = re.compile(r"[\x00-\x1f\x7f]")
_MAX_PUBLIC_IDENTIFIER_LENGTH = 160


def _validate_public_identifier(value: object, label: str) -> str:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or len(value) > _MAX_PUBLIC_IDENTIFIER_LENGTH
        or _CONTROL.search(value)
        or _UID.search(value)
    ):
        raise ValueError(f"{label} is malformed or UID-like")
    return value


@dataclass(frozen=True, slots=True)
class PublicScope:
    game_version: str
    environment: str
    mode_id: str
    cycle_id: str
    stage_id: str
    query_kind: str
    public_goal_kind: str | None = None


class PublicQueryBuilder:
    """Constructs outbound public requests from typed public fields only."""

    ALLOWED_ENVIRONMENTS = frozenset({"live", "test", "unknown"})
    ALLOWED_KINDS = frozenset({"stage_templates", "public_fact", "bundle_discovery"})

    def build(self, scope: PublicScope, *, release_id: str | None = None) -> dict[str, object]:
        required = (
            scope.game_version, scope.environment, scope.mode_id, scope.cycle_id,
            scope.stage_id, scope.query_kind,
        )
        if any(not isinstance(value, str) or not value.strip() for value in required):
            raise ValueError("public scope contains a missing or malformed value")
        if any(value != value.strip() or _UID.search(value) for value in required):
            raise ValueError("public scope contains an empty or UID-like value")
        if scope.public_goal_kind is not None and (
            not isinstance(scope.public_goal_kind, str)
            or not scope.public_goal_kind.strip()
            or scope.public_goal_kind != scope.public_goal_kind.strip()
            or _UID.search(scope.public_goal_kind)
        ):
            raise ValueError("public goal contains a malformed or UID-like value")
        if scope.environment not in self.ALLOWED_ENVIRONMENTS:
            raise ValueError("unsupported public environment")
        if scope.query_kind not in self.ALLOWED_KINDS:
            raise ValueError("unsupported public query kind")
        if release_id is not None and (
            not isinstance(release_id, str) or not release_id.strip()
            or release_id != release_id.strip() or _UID.search(release_id)
        ):
            raise ValueError("public release ID is malformed")
        request: dict[str, object] = {
            "contract_version": "0.1-draft",
            "schema_id": "PublicQuery",
            "schema_version": "0.1-draft",
            "query_kind": scope.query_kind,
            "scope": {
                "game_version": scope.game_version,
                "environment": scope.environment,
                "mode_id": scope.mode_id,
                "cycle_id": scope.cycle_id,
                "stage_id": scope.stage_id,
            },
        }
        if scope.public_goal_kind:
            request["public_goal"] = {"kind": scope.public_goal_kind}
        if release_id is not None:
            request["index_release_id"] = release_id
        return request

    @classmethod
    def serialize(cls, request: dict[str, object]) -> bytes:
        # Revalidate the complete public contract at the actual transport boundary.
        if not isinstance(request, dict):
            raise ValueError("outbound public request must be an object")
        allowed = {
            "contract_version", "schema_id", "schema_version", "query_kind", "scope",
            "public_goal", "index_release_id",
        }
        if set(request) - allowed:
            raise ValueError("outbound public request contains an unapproved field")
        required = {"contract_version", "schema_id", "schema_version", "query_kind", "scope"}
        if not required.issubset(request):
            raise ValueError("outbound public request is missing required fields")
        if (
            request["contract_version"] != "0.1-draft"
            or request["schema_id"] != "PublicQuery"
            or request["schema_version"] != "0.1-draft"
        ):
            raise ValueError("outbound public request has an unsupported schema")
        query_kind = request["query_kind"]
        if not isinstance(query_kind, str) or query_kind not in cls.ALLOWED_KINDS:
            raise ValueError("outbound public query kind is unsupported")
        scope = request.get("scope")
        allowed_scope = {"game_version", "environment", "mode_id", "cycle_id", "stage_id"}
        if not isinstance(scope, dict) or set(scope) != allowed_scope:
            raise ValueError("outbound public scope does not match the allowlist")
        for name, value in scope.items():
            _validate_public_identifier(value, f"outbound public scope {name}")
        if scope["environment"] not in cls.ALLOWED_ENVIRONMENTS:
            raise ValueError("outbound public environment is unsupported")
        goal = request.get("public_goal")
        if "public_goal" in request:
            if not isinstance(goal, dict) or set(goal) != {"kind"}:
                raise ValueError("outbound public goal does not match the allowlist")
            _validate_public_identifier(goal["kind"], "outbound public goal")
        if "index_release_id" in request:
            _validate_public_identifier(request["index_release_id"], "outbound release ID")
        payload = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
        if _UID.search(payload):
            raise ValueError("UID-like value blocked at outbound serialization boundary")
        return payload.encode("utf-8")
