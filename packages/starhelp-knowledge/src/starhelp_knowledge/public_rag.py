"""Deterministic public-evidence chunking, indexing, retrieval and abstention."""

from __future__ import annotations

import hashlib
import json
import math
import re
from collections import Counter
from datetime import UTC, datetime
from typing import Any, Protocol

from starhelp_knowledge.errors import InvalidPayload
from starhelp_knowledge.public_distribution import canonical_json_bytes

CHUNKER_PROFILE = "starhelp.public-rag-chunker.v1"
INDEX_PROFILE = "starhelp.public-rag-index.v1"
MAX_CHUNK_CHARS = 480
CHUNK_OVERLAP_CHARS = 80
DEFAULT_MAX_EVIDENCE_AGE_SECONDS = 180 * 24 * 60 * 60
_WORD_OR_CJK = re.compile(r"[a-z0-9]+|[\u3400-\u9fff]+", re.IGNORECASE)
_CJK = re.compile(r"^[\u3400-\u9fff]+$")


class SemanticEncoder(Protocol):
    """Optional local vector adapter. No encoder is configured in the service by default."""

    profile: str

    def encode(self, text: str) -> list[float]: ...


def tokenize(text: str) -> list[str]:
    tokens: list[str] = []
    for match in _WORD_OR_CJK.findall(text.casefold()):
        if _CJK.fullmatch(match):
            if len(match) == 1:
                tokens.append(match)
            else:
                tokens.extend(match[index:index + 2] for index in range(len(match) - 1))
        else:
            tokens.append(match)
    return tokens


def chunk_text(text: str, *, maximum: int = MAX_CHUNK_CHARS, overlap: int = CHUNK_OVERLAP_CHARS) -> list[str]:
    if type(text) is not str:
        raise InvalidPayload("public evidence text must be a string")
    text = " ".join(text.split())
    if not text:
        return []
    if type(maximum) is not int or maximum < 64 or type(overlap) is not int or not 0 <= overlap < maximum:
        raise InvalidPayload("invalid chunker limits")
    chunks: list[str] = []
    start = 0
    while start < len(text):
        end = min(start + maximum, len(text))
        if end < len(text):
            boundary = max(text.rfind(mark, start + maximum // 2, end) for mark in (". ", "! ", "? ", "。", "！", "？", "; ", ", "))
            if boundary > start:
                end = boundary + 1
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return chunks


def chunk_identity(
    *, source_id: str, evidence_id: str, revision: int, content_hash: str,
    chunker_profile: str = CHUNKER_PROFILE, chunk_index: int,
) -> str:
    return hashlib.sha256(canonical_json_bytes({
        "source_id": source_id, "evidence_id": evidence_id, "revision": revision,
        "content_hash": content_hash, "chunker_profile": chunker_profile,
        "chunk_index": chunk_index,
    })).hexdigest()


def _safe_embedding(value: Any) -> list[float] | None:
    if value is None:
        return None
    if not isinstance(value, list) or not value or any(type(item) not in (int, float) or not math.isfinite(item) for item in value):
        raise InvalidPayload("semantic encoder returned an invalid vector")
    return [float(item) for item in value]


def _cosine(left: list[float] | None, right: list[float] | None) -> float:
    if left is None or right is None or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right))
    lnorm = math.sqrt(sum(a * a for a in left))
    rnorm = math.sqrt(sum(b * b for b in right))
    return dot / (lnorm * rnorm) if lnorm and rnorm else 0.0


def _bm25(query: list[str], documents: list[str]) -> list[float]:
    if not query or not documents:
        return [0.0] * len(documents)
    tokenized = [tokenize(document) for document in documents]
    frequencies = [Counter(tokens) for tokens in tokenized]
    document_frequency = Counter(token for row in frequencies for token in row)
    average_length = sum(map(len, tokenized)) / max(1, len(tokenized))
    scores: list[float] = []
    for row, tokens in zip(frequencies, tokenized):
        score = 0.0
        for token in query:
            tf = row.get(token, 0)
            if not tf:
                continue
            df = document_frequency[token]
            idf = math.log(1 + (len(documents) - df + 0.5) / (df + 0.5))
            denominator = tf + 1.2 * (0.25 + 0.75 * len(tokens) / max(1, average_length))
            score += idf * tf * 2.2 / denominator
        scores.append(score)
    return scores


def retrieve_chunks(
    question: str,
    rows: list[dict[str, Any]],
    *,
    scope: dict[str, Any] | None = None,
    limit: int = 5,
    encoder: SemanticEncoder | None = None,
    max_evidence_age_seconds: int = DEFAULT_MAX_EVIDENCE_AGE_SECONDS,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    if type(question) is not str or not question.strip() or len(question) > 2000:
        raise InvalidPayload("public question must be non-empty and within limits")
    if type(limit) is not int or not 1 <= limit <= 20:
        raise InvalidPayload("public retrieval limit is outside its allowed range")
    if type(max_evidence_age_seconds) is not int or max_evidence_age_seconds < 1:
        raise InvalidPayload("evidence freshness limit is invalid")
    now = now or datetime.now(UTC)
    if now.tzinfo is None:
        raise InvalidPayload("retrieval clock must be timezone-aware")
    now = now.astimezone(UTC)
    scope = scope or {}
    fields = ("game_version", "environment", "release_status", "mode_id", "cycle_id", "stage_id")
    selected = []
    for row in rows:
        row_scope = json.loads(row["scope_json"])
        if any(scope.get(field) is not None and row_scope.get(field) != scope[field] for field in fields):
            continue
        if scope.get("environment") is None and row_scope.get("environment") not in {None, "live"}:
            continue
        if scope.get("release_status") is None and row_scope.get("release_status") not in {None, "released"}:
            continue
        selected.append((row, row_scope))
    if not selected:
        return []
    query_tokens = tokenize(question)
    texts = [f"{row['title']} {row['text']}" for row, _ in selected]
    lexical_scores = _bm25(query_tokens, texts)
    query_embedding = _safe_embedding(encoder.encode(question)) if encoder else None
    results: list[dict[str, Any]] = []
    for (row, row_scope), lexical in zip(selected, lexical_scores):
        embedding_matches = encoder is not None and row.get("embedding_profile") == encoder.profile
        embedding = json.loads(row["embedding_json"]) if embedding_matches and row["embedding_json"] else None
        semantic = _cosine(query_embedding, embedding) if encoder else 0.0
        score = lexical + max(0.0, semantic) * 0.5
        if lexical <= 0 and semantic < 0.55:
            continue
        try:
            observed_at = datetime.fromisoformat(row["observed_at"].replace("Z", "+00:00"))
            if observed_at.tzinfo is None:
                continue
            age_seconds = (now - observed_at.astimezone(UTC)).total_seconds()
        except (ValueError, TypeError, AttributeError):
            continue
        if age_seconds < -300:
            continue
        results.append({
            "chunk_id": row["chunk_id"], "evidence_id": row["evidence_id"],
            "revision": row["evidence_revision"], "content_hash": row["content_hash"],
            "source_id": row["source_id"], "release_id": row["release_id"],
            "title": row["title"], "url": row["canonical_url"],
            "locator": json.loads(row["locator_json"]), "scope": row_scope,
            "relation": row["relation"], "evidence_status": row["evidence_status"],
            "published_at": row["published_at"], "observed_at": row["observed_at"],
            "source_status": "permission_allowed_and_licensed",
            "freshness": "current" if age_seconds <= max_evidence_age_seconds else "stale",
            "excerpt": row["text"], "score": round(score, 8),
            "ranking_reason": {"lexical_bm25": round(lexical, 8), "semantic_cosine": round(semantic, 8) if encoder else None},
        })
    results.sort(key=lambda item: (-item["score"], item["evidence_id"], item["chunk_id"]))
    return results[:limit]


def grounded_answer(hits: list[dict[str, Any]]) -> dict[str, Any]:
    if not hits:
        return {"answer": None, "abstained": True, "abstention_reason": "no_matching_approved_evidence", "citations": []}
    current_hits = [hit for hit in hits if hit.get("freshness", "current") == "current"]
    if not current_hits:
        return {"answer": None, "abstained": True, "abstention_reason": "evidence_stale", "citations": _citations(hits[:3])}
    relations = {hit["relation"] for hit in current_hits}
    if "supports" in relations and "refutes" in relations:
        conflicts = [hit for hit in current_hits if hit["relation"] in {"supports", "refutes"}]
        return {"answer": None, "abstained": True, "abstention_reason": "conflicting_evidence", "citations": _citations(conflicts[:5])}
    top = current_hits[0]
    if top["evidence_status"] != "confirmed":
        return {"answer": None, "abstained": True, "abstention_reason": "evidence_not_confirmed", "citations": _citations([top])}
    prefix = "Evidence contradicts the premise: " if top["relation"] == "refutes" else ""
    answer = prefix + top["excerpt"]
    return {
        "answer": answer,
        "abstained": False,
        "abstention_reason": None,
        "answer_mode": "extractive_local_no_model",
        "citations": _citations(current_hits[:3]),
    }


def _citations(hits: list[dict[str, Any]]) -> list[dict[str, Any]]:
    citations: list[dict[str, Any]] = []
    seen: set[str] = set()
    for hit in hits:
        if hit["evidence_id"] in seen:
            continue
        seen.add(hit["evidence_id"])
        citations.append({
            "evidence_id": hit["evidence_id"], "revision": hit["revision"],
            "content_hash": hit["content_hash"], "title": hit["title"], "url": hit["url"],
            "locator": hit["locator"], "published_at": hit["published_at"],
            "observed_at": hit["observed_at"], "relation": hit["relation"],
            "source_status": hit.get("source_status", "permission_allowed_and_licensed"),
            "freshness": hit.get("freshness", "current"),
            "quote": hit["excerpt"], "chunk_id": hit["chunk_id"],
        })
    return citations


def indexed_at_utc() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")
