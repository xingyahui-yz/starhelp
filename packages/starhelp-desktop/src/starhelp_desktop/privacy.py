from __future__ import annotations

import json
import re
from dataclasses import dataclass


_UID = re.compile(r"(?<!\d)\d{8,12}(?!\d)")


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

    @staticmethod
    def serialize(request: dict[str, object]) -> bytes:
        # Validate top-level keys again at the actual transport boundary.
        allowed = {
            "contract_version", "schema_id", "schema_version", "query_kind", "scope",
            "public_goal", "index_release_id",
        }
        if set(request) - allowed:
            raise ValueError("outbound public request contains an unapproved field")
        scope = request.get("scope")
        allowed_scope = {"game_version", "environment", "mode_id", "cycle_id", "stage_id"}
        if not isinstance(scope, dict) or set(scope) != allowed_scope:
            raise ValueError("outbound public scope does not match the allowlist")
        if any(not isinstance(value, str) or not value or _UID.search(value) for value in scope.values()):
            raise ValueError("outbound public scope contains a private or malformed value")
        goal = request.get("public_goal")
        if goal is not None and (
            not isinstance(goal, dict) or set(goal) != {"kind"}
            or not isinstance(goal["kind"], str) or _UID.search(goal["kind"])
        ):
            raise ValueError("outbound public goal does not match the allowlist")
        release_id = request.get("index_release_id")
        if release_id is not None and (not isinstance(release_id, str) or _UID.search(release_id)):
            raise ValueError("outbound release ID is malformed")
        payload = json.dumps(request, ensure_ascii=False, separators=(",", ":"))
        if _UID.search(payload):
            raise ValueError("UID-like value blocked at outbound serialization boundary")
        return payload.encode("utf-8")
