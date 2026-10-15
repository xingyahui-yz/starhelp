"""Stable package entry point for the draft local-planner contract."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .engine import ADAPTER_PROFILE, PLANNER_VERSION, analyze_request


def analyze(request: Mapping[str, Any]) -> dict[str, Any]:
    """Analyze one fully materialized request without I/O or persistent state.

    The function does not mutate ``request``. Expected domain/compatibility failures
    are returned as structured results; malformed top-level input returns an error
    envelope rather than leaking exceptions to the caller.
    """
    return analyze_request(request)
