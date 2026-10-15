"""Safe application errors; messages never include rejected request values."""

from __future__ import annotations


class KnowledgeError(Exception):
    code = "knowledge_error"
    retryable = False

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code.replace("_", " "))


class InvalidPayload(KnowledgeError):
    code = "invalid_payload"


class UnsupportedContract(KnowledgeError):
    code = "unsupported_contract"


class PermissionDenied(KnowledgeError):
    code = "permission_denied"


class NotFound(KnowledgeError):
    code = "not_found"


class Conflict(KnowledgeError):
    code = "revision_conflict"


class InvalidTransition(KnowledgeError):
    code = "invalid_state_transition"


class IntegrityFailure(KnowledgeError):
    code = "integrity_failed"


class MissingDependency(KnowledgeError):
    code = "missing_member"


class WithdrawnEvidence(KnowledgeError):
    code = "withdrawn_evidence"


class CoverageInsufficient(KnowledgeError):
    code = "coverage_insufficient"


class UnsupportedSchema(KnowledgeError):
    code = "unsupported_schema"


class UnsupportedCapability(KnowledgeError):
    code = "unsupported_capability"


class SourceBlocked(KnowledgeError):
    code = "source_not_authorized"


class Retryable(KnowledgeError):
    code = "retryable_failure"
    retryable = True
