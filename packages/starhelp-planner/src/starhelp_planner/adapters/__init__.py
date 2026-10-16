"""Explicit, pure in-memory producer adapters; no producer runtime dependencies."""

from .entry import analyze_producers, prepare_producer_request

__all__ = ["analyze_producers", "prepare_producer_request"]
