"""Small dependency-free WSGI interface with strict request allowlists."""

from __future__ import annotations

import json
import re
from http import HTTPStatus
from datetime import UTC, datetime
from typing import Any
from urllib.parse import unquote

from starhelp_knowledge.errors import (
    Conflict,
    InvalidPayload,
    InvalidTransition,
    KnowledgeError,
    NotFound,
    PermissionDenied,
    UnsupportedContract,
)
from starhelp_knowledge.policy import Principal, TokenAuthenticator
from starhelp_knowledge.database import MIGRATION_VERSION
from starhelp_knowledge.public_distribution import PublicDistributionStore, canonical_json_bytes
from starhelp_knowledge.service import KnowledgeService


def _only(payload: Any, names: set[str]) -> dict[str, Any]:
    if not isinstance(payload, dict) or set(payload) - names:
        raise InvalidPayload("unexpected request field")
    return payload


def _status(error: KnowledgeError) -> int:
    if isinstance(error, InvalidPayload | UnsupportedContract):
        return HTTPStatus.BAD_REQUEST
    if isinstance(error, PermissionDenied):
        return HTTPStatus.FORBIDDEN
    if isinstance(error, NotFound):
        return HTTPStatus.NOT_FOUND
    if isinstance(error, Conflict | InvalidTransition):
        return HTTPStatus.CONFLICT
    return HTTPStatus.UNPROCESSABLE_ENTITY


class KnowledgeApplication:
    def __init__(
        self,
        service: KnowledgeService,
        authenticator: TokenAuthenticator,
        *,
        distribution_store: PublicDistributionStore | None = None,
        instance_id: str = "starhelp-knowledge-local",
    ) -> None:
        self.service = service
        self.authenticator = authenticator
        self.distribution_store = distribution_store
        self.instance_id = instance_id

    def __call__(self, environ: dict[str, Any], start_response: Any) -> list[bytes]:
        method = environ.get("REQUEST_METHOD", "GET").upper()
        path = unquote(environ.get("PATH_INFO", "/"))
        try:
            if method == "GET" and path == "/health":
                return self._respond(start_response, HTTPStatus.OK, {"status": "ok", "service": "starhelp-knowledge"})
            if method == "GET" and path == "/health/ready":
                return self._respond(start_response, HTTPStatus.OK, self._readiness())
            if method == "GET" and path == "/v1/distributions":
                query = _parse_query(environ.get("QUERY_STRING", ""))
                if set(query) != {"profile", "channel"} or self.distribution_store is None:
                    raise InvalidPayload("distribution discovery requires profile and channel")
                return self._respond_raw(
                    start_response, HTTPStatus.OK,
                    self.distribution_store.get_catalog(profile=query["profile"], channel=query["channel"]),
                )
            if method == "GET" and path == "/v1/distribution-revocations":
                query = _parse_query(environ.get("QUERY_STRING", ""))
                if set(query) != {"profile", "channel"} or self.distribution_store is None:
                    raise InvalidPayload("revocation discovery requires profile and channel")
                return self._respond_raw(
                    start_response, HTTPStatus.OK,
                    self.distribution_store.get_revocations(profile=query["profile"], channel=query["channel"]),
                )
            distribution_match = re.fullmatch(r"/v1/distributions/([A-Za-z0-9][A-Za-z0-9._:-]{0,199})", path)
            if method == "GET" and distribution_match:
                if self.distribution_store is None:
                    raise NotFound()
                return self._respond_raw(
                    start_response, HTTPStatus.OK,
                    self.distribution_store.get_artifact(distribution_match.group(1)),
                    content_type="application/vnd.starhelp.publicbundle+json",
                )
            if method == "GET" and path == "/v1/releases":
                data = self.service.search({"query_kind": "release_discovery"})
                return self._respond(start_response, HTTPStatus.OK, data)
            if method == "GET" and path.startswith("/v1/releases/") and path.endswith("/bundle"):
                release_id = path.removeprefix("/v1/releases/").removesuffix("/bundle").strip("/")
                data = self.service.get_release_bundle(release_id)
                return self._respond(start_response, HTTPStatus.OK, data)
            if method == "GET" and path.startswith("/v1/templates/"):
                template_id = path.removeprefix("/v1/templates/").strip("/")
                query = _parse_query(environ.get("QUERY_STRING", ""))
                if set(query) != {"release"}:
                    raise InvalidPayload("template fetch requires one release")
                data = self.service.get_complete_template(query["release"], template_id)
                return self._respond(start_response, HTTPStatus.OK, data)
            if method == "POST" and path == "/v1/query":
                payload = self._body(environ)
                return self._respond(start_response, HTTPStatus.OK, self.service.search(payload))
            if method == "POST" and path == "/v1/public-search":
                payload = self._body(environ)
                return self._respond(start_response, HTTPStatus.OK, self.service.search_public(payload))

            if path.startswith("/v1/admin/"):
                principal = self._principal(environ)
                return self._admin(method, path, principal, self._body(environ) if method == "POST" else {}, environ, start_response)
            return self._respond(start_response, HTTPStatus.NOT_FOUND, {"error": {"code": "not_found", "message": "not found"}})
        except KnowledgeError as error:
            data = {"error": {"code": error.code, "message": str(error), "retryable": error.retryable}}
            return self._respond(start_response, _status(error), data)
        except (json.JSONDecodeError, UnicodeDecodeError, ValueError):
            return self._respond(start_response, HTTPStatus.BAD_REQUEST, {"error": {"code": "invalid_payload", "message": "invalid request body", "retryable": False}})
        except Exception:
            # Do not expose request bodies, exception messages, stack traces, or SQL parameters.
            return self._respond(start_response, HTTPStatus.INTERNAL_SERVER_ERROR, {"error": {"code": "internal_error", "message": "request failed", "retryable": True}})

    def _admin(self, method: str, path: str, principal: Principal, body: dict[str, Any], environ: dict[str, Any], start_response: Any) -> list[bytes]:
        if method == "GET" and path == "/v1/admin/source-report":
            return self._respond(start_response, HTTPStatus.OK, self.service.source_report(principal))
        if method == "GET" and re.fullmatch(r"/v1/admin/update-runs/[^/]+", path):
            match = re.fullmatch(r"/v1/admin/update-runs/([^/]+)", path)
            assert match is not None
            return self._respond(start_response, HTTPStatus.OK, self.service.update_run_status(match.group(1)))
        if method != "POST":
            raise InvalidPayload("unsupported admin method")
        if path == "/v1/admin/sources":
            data = _only(body, {"source_id", "name", "platform", "source_role"})
            self.service.add_source(principal, **data)
            return self._respond(start_response, HTTPStatus.CREATED, {"status": "created"})
        if path == "/v1/admin/source-policies":
            data = _only(body, {"source_id", "permission_status", "terms_reference", "allowed_domains", "allowed_paths", "rate_policy", "storage_policy", "checked_at"})
            policy_id = self.service.set_source_policy(principal, **data)
            return self._respond(start_response, HTTPStatus.CREATED, {"policy_id": policy_id})
        if path == "/v1/admin/source-capabilities":
            data = _only(body, {"source_id", "adapter_version", "status", "capabilities", "coverage", "evidence"})
            snapshot_id = self.service.record_source_capabilities(principal, **data)
            return self._respond(start_response, HTTPStatus.CREATED, {"snapshot_id": snapshot_id})
        if path == "/v1/admin/evidence":
            data = _only(body, {"source_id", "external_content_id", "canonical_url", "content_kind", "title", "author_id", "excerpt", "locator", "license_status", "published_at", "relation", "evidence_status", "scope"})
            evidence_id = self.service.add_public_evidence(principal, **data)
            return self._respond(start_response, HTTPStatus.CREATED, {"evidence_id": evidence_id})
        if path == "/v1/admin/candidates":
            data = _only(body, {"kind", "record_id", "scope", "payload", "evidence_refs", "dependency_refs"})
            result = self.service.create_candidate(principal, **data)
            return self._respond(start_response, HTTPStatus.CREATED, result)
        if path == "/v1/admin/reviews":
            data = _only(body, {"kind", "record_id", "revision", "expected_content_hash", "decision", "note"})
            return self._respond(start_response, HTTPStatus.OK, self.service.review_candidate(principal, **data))
        if path == "/v1/admin/releases":
            data = _only(body, {"members", "coverage", "required_capabilities", "schema_version"})
            return self._respond(start_response, HTTPStatus.CREATED, self.service.build_release(principal, **data))
        match = re.fullmatch(r"/v1/admin/releases/([^/]+)/validate", path)
        if match:
            data = _only(body, {"idempotency_key"})
            return self._respond(start_response, HTTPStatus.OK, self.service.validate_release(principal, match.group(1), **data))
        match = re.fullmatch(r"/v1/admin/releases/([^/]+)/activate", path)
        if match:
            data = _only(body, {"expected_active_release_id", "idempotency_key"})
            return self._respond(start_response, HTTPStatus.OK, self.service.activate_release(principal, match.group(1), **data))
        if path == "/v1/admin/releases/rollback":
            data = _only(body, {"target_release_id", "expected_active_release_id", "idempotency_key"})
            target = data.pop("target_release_id")
            return self._respond(start_response, HTTPStatus.OK, self.service.rollback_release(principal, target, **data))
        if path == "/v1/admin/disable":
            data = _only(body, {"kind", "record_id", "revision", "reason"})
            self.service.disable_record(principal, **data)
            return self._respond(start_response, HTTPStatus.OK, {"status": "disabled"})
        if path == "/v1/admin/update-runs":
            data = _only(body, {"idempotency_key", "source_id", "public_scope"})
            return self._respond(start_response, HTTPStatus.CREATED, self.service.create_update_run(principal, **data))
        match = re.fullmatch(r"/v1/admin/update-runs/([^/]+)", path)
        if method == "GET" and match:
            return self._respond(start_response, HTTPStatus.OK, self.service.update_run_status(match.group(1)))
        match = re.fullmatch(r"/v1/admin/update-tasks/([^/]+)/claim", path)
        if match:
            data = _only(body, {"lease_seconds"})
            return self._respond(start_response, HTTPStatus.OK, self.service.claim_update_task(principal, match.group(1), **data))
        match = re.fullmatch(r"/v1/admin/update-tasks/([^/]+)/retry", path)
        if match:
            data = _only(body, {"idempotency_key"})
            return self._respond(start_response, HTTPStatus.OK, self.service.retry_update_task(principal, match.group(1), **data))
        match = re.fullmatch(r"/v1/admin/update-tasks/([^/]+)/resume", path)
        if match:
            data = _only(body, {"idempotency_key"})
            return self._respond(start_response, HTTPStatus.OK, self.service.resume_after_review(principal, match.group(1), **data))
        match = re.fullmatch(r"/v1/admin/update-tasks/([^/]+)/cancel", path)
        if match:
            data = _only(body, {"idempotency_key"})
            return self._respond(start_response, HTTPStatus.OK, self.service.cancel_update_task(principal, match.group(1), **data))
        match = re.fullmatch(r"/v1/admin/update-tasks/([^/]+)/checkpoint", path)
        if match:
            data = _only(body, {"checkpoint", "output_hash", "state"})
            return self._respond(start_response, HTTPStatus.OK, self.service.checkpoint_update_task(principal, match.group(1), **data))
        raise NotFound()

    def _principal(self, environ: dict[str, Any]) -> Principal:
        header = environ.get("HTTP_AUTHORIZATION", "")
        prefix, _, token = header.partition(" ")
        if prefix.casefold() != "bearer" or not token:
            raise PermissionDenied()
        principal = self.authenticator.authenticate(token)
        if principal is None:
            raise PermissionDenied()
        return principal

    def _readiness(self) -> dict[str, Any]:
        database_status, migration_status, schema_version = "ready", "current", None
        try:
            with self.service.database.reader() as db:
                row = db.execute("SELECT MAX(version) AS version FROM schema_migrations").fetchone()
                schema_version = int(row["version"] or 0)
            if schema_version < MIGRATION_VERSION:
                migration_status = "pending"
        except Exception:
            database_status, migration_status = "unavailable", "failed"
        if self.distribution_store is None:
            catalog_status, active_release = "not_configured", None
        else:
            catalog_status, active_release = self.distribution_store.readiness()
        status = "ready" if database_status == "ready" and migration_status == "current" and catalog_status != "unavailable" else "not_ready"
        return {
            "status": status,
            "service": "starhelp-knowledge",
            "application_version": __import__("starhelp_knowledge").__version__,
            "schema_version": schema_version,
            "database": database_status,
            "migration": migration_status,
            "active_release_id": active_release,
            "distribution_catalog": catalog_status,
            "instance_id": self.instance_id,
            "checked_at": datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
        }

    def _body(self, environ: dict[str, Any]) -> dict[str, Any]:
        length_text = environ.get("CONTENT_LENGTH") or "0"
        try:
            length = int(length_text)
        except ValueError as exc:
            raise InvalidPayload() from exc
        if length < 0 or length > 2_000_000:
            raise InvalidPayload("request body exceeds limit")
        body = environ["wsgi.input"].read(length)
        value = json.loads(body.decode("utf-8"))
        if not isinstance(value, dict):
            raise InvalidPayload()
        return value

    @staticmethod
    def _respond(start_response: Any, status: int, value: dict[str, Any]) -> list[bytes]:
        body = json.dumps(value, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        phrase = HTTPStatus(status).phrase
        start_response(f"{status} {phrase}", [("Content-Type", "application/json; charset=utf-8"), ("Content-Length", str(len(body))), ("Cache-Control", "no-store")])
        return [body]

    @staticmethod
    def _respond_raw(
        start_response: Any,
        status: int,
        body: bytes,
        *,
        content_type: str = "application/json; charset=utf-8",
    ) -> list[bytes]:
        import hashlib

        phrase = HTTPStatus(status).phrase
        headers = [
            ("Content-Type", content_type),
            ("Content-Length", str(len(body))),
            ("Cache-Control", "no-store"),
            ("ETag", f'"{hashlib.sha256(body).hexdigest()}"'),
        ]
        start_response(f"{status} {phrase}", headers)
        return [body]


def _parse_query(query_string: str) -> dict[str, str]:
    from urllib.parse import parse_qs

    parsed = parse_qs(query_string, keep_blank_values=True, strict_parsing=True)
    if any(len(values) != 1 for values in parsed.values()):
        raise InvalidPayload("invalid query string")
    return {key: values[0] for key, values in parsed.items()}
