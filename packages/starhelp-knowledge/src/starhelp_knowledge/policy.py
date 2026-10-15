"""Strict public request validation and role checks."""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass
from typing import Any

from starhelp_knowledge.errors import InvalidPayload, PermissionDenied

CONTRACT_VERSION = "0.1-draft"
PUBLIC_QUERY_FIELDS = frozenset(
    {
        "contract_version",
        "schema_id",
        "schema_version",
        "query_kind",
        "index_release_id",
        "scope",
        "public_goal",
        "public_question",
        "public_entity_ids",
        "cursor",
        "limit",
        "client_capabilities",
        "cached_release_ids",
    }
)
SCOPE_FIELDS = frozenset(
    {"game_version", "environment", "release_status", "mode_id", "cycle_id", "stage_id"}
)
GOAL_FIELDS = frozenset({"kind", "threshold", "unit"})
ROLE_PERMISSIONS = {
    "reader": frozenset({"read"}),
    "updater": frozenset({"read", "update"}),
    "reviewer": frozenset({"read", "review"}),
    "publisher": frozenset({"read", "publish"}),
    "admin": frozenset({"read", "update", "review", "publish", "admin"}),
}
TOKEN_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,160}$")


def _reject_extra(value: dict[str, Any], allowed: frozenset[str], context: str) -> None:
    if not isinstance(value, dict):
        raise InvalidPayload()
    if set(value) - allowed:
        # Deliberately do not echo the names or values: unexpected keys can carry private data.
        raise InvalidPayload(f"unexpected {context} field")


def validate_public_query(payload: Any) -> dict[str, Any]:
    """Validate a public-only query and return a normalized shallow copy."""
    _reject_extra(payload, PUBLIC_QUERY_FIELDS, "query")
    if payload.get("contract_version", CONTRACT_VERSION) != CONTRACT_VERSION:
        raise InvalidPayload("unsupported contract version")
    if payload.get("schema_id", "PublicQuery") != "PublicQuery" or payload.get("schema_version", CONTRACT_VERSION) != CONTRACT_VERSION:
        raise InvalidPayload("unsupported query schema")
    query_kind = payload.get("query_kind")
    if query_kind not in {"search", "stage_templates", "entity", "public_question", "release_discovery"}:
        raise InvalidPayload("unsupported query kind")
    scope = payload.get("scope", {})
    if not isinstance(scope, dict):
        raise InvalidPayload("invalid public scope")
    _reject_extra(scope, SCOPE_FIELDS, "scope")
    if scope.get("environment") not in {None, "live", "beta", "unknown"}:
        raise InvalidPayload("invalid environment")
    if scope.get("release_status") not in {None, "released", "unreleased", "unknown"}:
        raise InvalidPayload("invalid release status")
    goal = payload.get("public_goal")
    if goal is not None:
        if not isinstance(goal, dict):
            raise InvalidPayload("invalid public goal")
        _reject_extra(goal, GOAL_FIELDS, "goal")
        if not isinstance(goal.get("kind"), str):
            raise InvalidPayload("invalid public goal")
    question = payload.get("public_question")
    if question is not None and (not isinstance(question, str) or len(question) > 2000):
        raise InvalidPayload("invalid public question")
    entity_ids = payload.get("public_entity_ids", [])
    if not isinstance(entity_ids, list) or len(entity_ids) > 100 or any(
        not isinstance(item, str) or len(item) > 200 for item in entity_ids
    ):
        raise InvalidPayload("invalid public entity list")
    limit = payload.get("limit", 20)
    if not isinstance(limit, int) or isinstance(limit, bool) or not 1 <= limit <= 100:
        raise InvalidPayload("invalid result limit")
    for key in ("index_release_id", "cursor"):
        value = payload.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > 200):
            raise InvalidPayload(f"invalid {key}")
    return {**payload, "scope": dict(scope), "public_entity_ids": list(entity_ids), "limit": limit}


@dataclass(frozen=True, slots=True)
class Principal:
    actor_id: str
    roles: frozenset[str]

    def require(self, role: str) -> None:
        permission = "admin" if role == "admin" else role
        if not any(permission in ROLE_PERMISSIONS.get(actual, ()) for actual in self.roles):
            raise PermissionDenied()


class TokenAuthenticator:
    """Authenticate opaque API tokens against configured SHA-256 token hashes."""

    def __init__(self, actors: dict[str, dict[str, Any]] | None = None) -> None:
        self._actors = actors or {}

    def authenticate(self, token: str | None) -> Principal | None:
        if token is None or not TOKEN_RE.fullmatch(token):
            return None
        token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
        for actor_id, actor in self._actors.items():
            expected = actor.get("token_sha256")
            if isinstance(expected, str) and hmac.compare_digest(token_hash, expected.lower()):
                roles = frozenset(role for role in actor.get("roles", []) if role in ROLE_PERMISSIONS)
                return Principal(actor_id=actor_id, roles=roles)
        return None
