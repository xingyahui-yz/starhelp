"""Fixed-origin, anonymous transport for synthetic public distribution metadata and bytes."""

from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from ipaddress import ip_address

from .producer_v2 import MAX_DOCUMENT_BYTES


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, new_url):
        return None


@dataclass(frozen=True, slots=True)
class FixedOriginDistributionSource:
    """GET-only public transport pinned to a configured HTTPS origin or loopback A."""

    origin: str
    channel: str
    consumer_profile: str = "starhelp.local.v0.2"
    timeout_seconds: float = 10.0
    envelope_max_bytes: int = 2 * 1024 * 1024

    def __post_init__(self) -> None:
        parsed = urllib.parse.urlsplit(self.origin)
        if (parsed.scheme not in {"https", "http"} or not parsed.hostname or parsed.username
                or parsed.password or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
            raise ValueError("distribution origin must be a fixed origin without credentials or path")
        if parsed.scheme == "http" and not _is_loopback(parsed.hostname):
            raise ValueError("plain HTTP is limited to the local loopback development service")
        if not self.channel or self.channel.strip() != self.channel:
            raise ValueError("distribution channel must be fixed local configuration")
        if not 0 < self.timeout_seconds <= 30:
            raise ValueError("distribution request timeout is outside the supported range")
        if not 0 < self.envelope_max_bytes <= 2 * 1024 * 1024:
            raise ValueError("analyzable envelope limit exceeds the v0.2 maximum")

    def fetch_catalog(self) -> bytes:
        query = urllib.parse.urlencode({"profile": self.consumer_profile, "channel": self.channel})
        return self._get(f"/v1/distributions?{query}", MAX_DOCUMENT_BYTES[
            "starhelp.public-distribution-catalog.v1"
        ])

    def fetch_revocations(self) -> bytes:
        query = urllib.parse.urlencode({"profile": self.consumer_profile, "channel": self.channel})
        return self._get(f"/v1/distribution-revocations?{query}", MAX_DOCUMENT_BYTES[
            "starhelp.public-revocations.v1"
        ])

    def fetch_envelope(self, release_id: str) -> bytes:
        if (not isinstance(release_id, str) or not release_id
                or any(char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-"
                       for char in release_id)):
            raise ValueError("release ID is invalid")
        return self._get(f"/v1/distributions/{urllib.parse.quote(release_id, safe='')}",
                         self.envelope_max_bytes)

    def _get(self, route: str, max_bytes: int) -> bytes:
        url = self.origin.rstrip("/") + route
        request = urllib.request.Request(
            url, headers={"Accept": "application/json", "Accept-Encoding": "identity"}, method="GET"
        )
        opener = urllib.request.build_opener(_NoRedirect())
        try:
            with opener.open(request, timeout=self.timeout_seconds) as response:
                if response.status != 200:
                    raise ValueError("public distribution returned an unexpected status")
                if response.headers.get("Content-Encoding", "identity").lower() != "identity":
                    raise ValueError("compressed public distribution bytes are not accepted")
                raw = response.read(max_bytes + 1)
        except urllib.error.HTTPError:
            raise ValueError("public distribution request failed without following redirects") from None
        except urllib.error.URLError:
            raise ValueError("public distribution origin is unavailable") from None
        if len(raw) > max_bytes:
            raise ValueError("public distribution payload exceeds its raw byte limit")
        return raw


def _is_loopback(hostname: str) -> bool:
    normalized = hostname.strip("[]").lower()
    if normalized == "localhost":
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False
