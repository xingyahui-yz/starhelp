"""Source adapter contracts and explicitly synthetic offline adapter."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
import json
import threading
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from starhelp_knowledge.errors import InvalidPayload, Retryable, SourceBlocked


@dataclass(frozen=True, slots=True)
class SourceCapabilities:
    status: str
    discovery: bool
    pagination: bool
    time_order: bool
    full_text: bool
    coverage: str
    note: str


class PublicSourceAdapter(ABC):
    """An adapter must be bound to a currently allowed source policy."""

    source_id: str
    adapter_version: str

    @abstractmethod
    def capabilities(self) -> SourceCapabilities: ...

    @abstractmethod
    def discover(self, scope: dict[str, Any], cursor: str | None = None) -> dict[str, Any]: ...


class SyntheticFixtureAdapter(PublicSourceAdapter):
    """Offline sample adapter. Its output is never marked as real source data."""

    source_id = "fixture:offline"
    adapter_version = "fixture-1"

    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(
            status="declared",
            discovery=True,
            pagination=False,
            time_order=False,
            full_text=False,
            coverage="synthetic fixture only",
            note="not connected to a real source and not valid evidence of source coverage",
        )

    def discover(self, scope: dict[str, Any], cursor: str | None = None) -> dict[str, Any]:
        if cursor is not None:
            raise SourceBlocked("fixture adapter has no pagination")
        return {
            "source_id": self.source_id,
            "adapter_version": self.adapter_version,
            "status": "synthetic",
            "scope": dict(scope),
            "items": [],
            "coverage": {"status": "unknown", "reason": "fixture-only"},
        }


class _RejectRedirects(HTTPRedirectHandler):
    def redirect_request(self, req: Request, fp: Any, code: int, msg: str, headers: Any, new_url: str) -> None:
        return None


class VerifiedJSONSourceAdapter(PublicSourceAdapter):
    """Fetch one public JSON endpoint after separate human-recorded permission checks.

    This is a transport adapter, not a source-specific parser. It never sends cookies,
    credentials, player data, query parameters, or account-derived values.
    """

    def __init__(
        self,
        *,
        source_id: str,
        adapter_version: str,
        endpoint: str,
        source_policy: dict[str, Any],
        capability_snapshot: dict[str, Any],
        opener: Any = None,
        max_bytes: int = 8_000_000,
        timeout_seconds: float = 15,
    ) -> None:
        if not isinstance(source_policy, dict) or source_policy.get("permission_status") != "allowed":
            raise SourceBlocked()
        if not isinstance(capability_snapshot, dict) or capability_snapshot.get("status") != "verified":
            raise SourceBlocked("source capability has not been verified")
        if (
            source_policy.get("source_id") != source_id
            or capability_snapshot.get("source_id") != source_id
            or capability_snapshot.get("adapter_version") != adapter_version
        ):
            raise SourceBlocked("source policy and capability snapshot do not match this adapter")
        if not 1 <= max_bytes <= 32_000_000 or not 1 <= timeout_seconds <= 60:
            raise InvalidPayload("invalid source request limits")
        self.source_id = source_id
        self.adapter_version = adapter_version
        self.endpoint = endpoint
        domains, paths = source_policy.get("allowed_domains"), source_policy.get("allowed_paths", [])
        rate_policy = source_policy.get("rate_policy", {})
        if (
            not isinstance(domains, list) or not domains
            or any(not isinstance(domain, str) or not domain or "/" in domain or ":" in domain for domain in domains)
            or not isinstance(paths, list)
            or any(not isinstance(path, str) or not path.startswith("/") or "?" in path or "#" in path for path in paths)
            or not isinstance(rate_policy, dict)
        ):
            raise InvalidPayload("invalid source request policy")
        self._domains = tuple(domain.casefold().rstrip(".") for domain in domains)
        self._paths = tuple(paths)
        self._rate_policy = rate_policy
        self._max_bytes = max_bytes
        self._timeout = timeout_seconds
        self._opener = opener or build_opener(_RejectRedirects())
        self._last_request_at = 0.0
        self._lock = threading.Lock()
        self._validate_endpoint()

    def capabilities(self) -> SourceCapabilities:
        return SourceCapabilities(
            status="verified",
            discovery=False,
            pagination=False,
            time_order=False,
            full_text=False,
            coverage="endpoint-specific; completeness not inferred",
            note="transport verification does not prove source permission, full coverage, or data accuracy",
        )

    def discover(self, scope: dict[str, Any], cursor: str | None = None) -> dict[str, Any]:
        if cursor is not None:
            raise SourceBlocked("pagination is not supported by this adapter")
        allowed_scope = {"game_version", "environment", "release_status", "mode_id", "cycle_id", "stage_id"}
        if not isinstance(scope, dict) or set(scope) - allowed_scope:
            raise InvalidPayload("invalid public source scope")
        data = self.fetch_json()
        return {
            "source_id": self.source_id,
            "adapter_version": self.adapter_version,
            "status": data["status"],
            "scope": dict(scope),
            "observed_at": data.get("observed_at"),
            "etag": data.get("etag"),
            "last_modified": data.get("last_modified"),
            "content_hash": data.get("content_hash"),
            "payload": data.get("payload"),
            "coverage": {"status": "unknown", "reason": "endpoint transport does not establish completeness"},
        }

    def fetch_json(self, *, etag: str | None = None) -> dict[str, Any]:
        headers = {
            "Accept": "application/json",
            "User-Agent": "StarHelpKnowledge/0.1 (+public-data; no-auth)",
            "Cache-Control": "no-cache",
        }
        if etag is not None:
            if not isinstance(etag, str) or len(etag) > 500 or "\r" in etag or "\n" in etag:
                raise InvalidPayload("invalid source cache validator")
            headers["If-None-Match"] = etag
        request = Request(self.endpoint, headers=headers, method="GET")
        if any(key.casefold() in {"authorization", "cookie", "proxy-authorization"} for key in request.headers):
            raise SourceBlocked("credential headers are forbidden")
        minimum_interval = self._rate_policy.get("min_interval_seconds", 0)
        if not isinstance(minimum_interval, int | float) or isinstance(minimum_interval, bool) or not 0 <= minimum_interval <= 3600:
            raise InvalidPayload("invalid source rate policy")
        with self._lock:
            delay = float(minimum_interval) - (time.monotonic() - self._last_request_at)
            if delay > 0:
                time.sleep(delay)
            self._last_request_at = time.monotonic()
        try:
            response = self._opener.open(request, timeout=self._timeout)
        except HTTPError as error:
            if error.code == 304:
                return {"status": "not_modified", "etag": etag}
            if error.code == 429 or 500 <= error.code <= 599:
                raise Retryable("source temporarily unavailable") from None
            raise SourceBlocked("source returned an unsuccessful status") from None
        except (URLError, TimeoutError, OSError):
            raise Retryable("source connection failed") from None
        with response:
            final_url = response.geturl()
            if not self._url_is_allowed(final_url):
                raise SourceBlocked("source redirected outside its allowed scope")
            status = getattr(response, "status", 200)
            if status < 200 or status >= 300:
                raise SourceBlocked("source returned an unsuccessful status")
            content_type = response.headers.get("Content-Type", "").split(";", 1)[0].strip().casefold()
            if content_type not in {"application/json", "text/json"} and not content_type.endswith("+json"):
                raise SourceBlocked("source did not return JSON")
            raw = response.read(self._max_bytes + 1)
            if len(raw) > self._max_bytes:
                raise SourceBlocked("source response exceeds configured size")
            try:
                payload = json.loads(raw.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                raise SourceBlocked("source JSON is invalid") from None
            from datetime import UTC, datetime

            import hashlib

            return {
                "status": "fetched",
                "observed_at": datetime.now(UTC).isoformat(timespec="seconds"),
                "etag": response.headers.get("ETag"),
                "last_modified": response.headers.get("Last-Modified"),
                "content_hash": hashlib.sha256(raw).hexdigest(),
                "payload": payload,
            }

    def _validate_endpoint(self) -> None:
        if not self._url_is_allowed(self.endpoint):
            raise SourceBlocked("endpoint is outside the source's allowed scope")

    def _url_is_allowed(self, url: str) -> bool:
        try:
            parsed = urlparse(url)
            port = parsed.port
        except (TypeError, ValueError):
            return False
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password or port not in {None, 443} or parsed.query or parsed.fragment:
            return False
        hostname = parsed.hostname.casefold().rstrip(".")
        if not any(hostname == domain or hostname.endswith("." + domain) for domain in self._domains):
            return False
        return not self._paths or any(parsed.path == prefix or parsed.path.startswith(prefix.rstrip("/") + "/") for prefix in self._paths)
