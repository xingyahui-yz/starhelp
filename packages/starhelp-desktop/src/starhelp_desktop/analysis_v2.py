"""Basis-bound v0.2 analysis staging and explicit report persistence."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from .distribution_state import DistributionSecurityStore
from .lifecycle import ProfileLifecycle
from .planner import PlannerResult, PlannerUnavailable
from .planner_v2 import LocalProducerV2Process
from .producer_v2 import HASH_PROFILE, PublicObjectIdentity
from .reports import AnalysisReport, ReportLifecycle


@dataclass(frozen=True, slots=True)
class ProducerAnalysisExecutionV2:
    planner_result: PlannerResult
    temporary_report: AnalysisReport | None


class ProducerAnalysisRunnerV2:
    """Capture a single immutable v0.2 request and bind staged/saved reports to its basis."""

    def __init__(self, planner: LocalProducerV2Process, reports: ReportLifecycle,
                 security_state: DistributionSecurityStore) -> None:
        self._planner = planner
        self._reports = reports
        self._security = security_state

    def run(self, *, request: dict[str, Any], profile_id: UUID,
            authorization_generation: int, lifecycle: ProfileLifecycle) -> ProducerAnalysisExecutionV2:
        try:
            encoded = json.dumps(request, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
            frozen = json.loads(encoded)
        except (TypeError, ValueError, UnicodeError, RecursionError):
            raise PlannerUnavailable("v0.2 request is not immutable JSON") from None
        result = self._planner.analyze(
            request=frozen, profile_id=profile_id,
            authorization_generation=authorization_generation, lifecycle=lifecycle,
            security_state=self._security,
        )
        if result.result.get("status") != "plans_available":
            return ProducerAnalysisExecutionV2(result, None)
        producer_response = result.result
        analysis = producer_response.get("analysis")
        if not isinstance(analysis, dict):
            # Keep compatibility with direct runner fakes while consuming the v0.2
            # producer envelope, which carries domain fields under ``analysis``.
            analysis = producer_response
        inner = frozen["producer_request"]
        snapshot_data = json.loads(inner["account_snapshot"]["raw_json"])
        release_id = inner["public_bundle"]["expected_release_id"]
        if analysis.get("index_release_id") != release_id:
            raise PlannerUnavailable("v0.2 planner result belongs to a different release")
        raw_citations = analysis.get("citations")
        if not isinstance(raw_citations, list) or not raw_citations:
            raise PlannerUnavailable("v0.2 result has no typed public citations")
        try:
            citations = _bind_citations_to_native_objects(
                raw_citations, inner["public_bundle"].get("raw_json", ""), release_id,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            raise PlannerUnavailable("v0.2 result has malformed or unbound public citations") from None
        try:
            self._security.assert_public_refs_usable(citations)
        except (TypeError, ValueError):
            raise PlannerUnavailable("v0.2 result cites a revoked or malformed public reference") from None
        refs = frozenset(
            json.dumps(PublicObjectIdentity(**item).as_dict(), ensure_ascii=False,
                       sort_keys=True, separators=(",", ":"))
            for item in citations
        )
        if len(refs) != len(citations):
            raise PlannerUnavailable("v0.2 result contains malformed or duplicate typed citations")
        task = dict(inner["task"])
        if "feedback" in inner:
            task["feedback"] = inner["feedback"]
        basis = inner["public_basis"]
        report_result = dict(analysis)
        report_result["citations"] = citations
        if analysis is not producer_response:
            # Retain correlation, digest, and provenance fields from C's response
            # without hiding the domain result from the report UI.
            report_result["producer_response"] = {
                key: value for key, value in producer_response.items() if key != "analysis"
            }
            report_result["producer_response"]["analysis_citations"] = raw_citations

        def stage() -> AnalysisReport:
            lifecycle.require_active(profile_id, authorization_generation)
            return self._reports.make_temporary(
                profile_id=profile_id, generation=authorization_generation,
                task=task, result=report_result,
                snapshot_revision=snapshot_data["revision"], public_release_id=release_id,
                planner_version=result.planner_version, public_refs=refs,
                public_basis_sha256=inner["public_basis_sha256"], public_epoch=basis["epoch"],
            )

        try:
            report = self._security.run_if_epoch_current(basis["epoch"], stage)
        except ValueError as exc:
            if str(exc) == "public_basis_changed":
                raise PlannerUnavailable("public_basis_changed") from None
            raise
        return ProducerAnalysisExecutionV2(result, report)

    def save_current(self, report: AnalysisReport, *, current_snapshot_revision: int,
                     current_release_id: str, known_withdrawn_refs: frozenset[str]) -> Any:
        if report.public_basis_sha256 is None or report.public_epoch is None:
            raise ValueError("only a v0.2 basis-bound report may be saved as current")

        def save() -> Any:
            return self._reports.save_explicitly(
                report, current_snapshot_revision=current_snapshot_revision,
                current_public_release_id=current_release_id,
                withdrawn_refs=known_withdrawn_refs, withdrawal_status_known=True,
                current_public_basis_sha256=report.public_basis_sha256,
                current_public_epoch=report.public_epoch,
            )

        try:
            return self._security.run_if_epoch_current(report.public_epoch, save)
        except ValueError as exc:
            if str(exc) == "public_basis_changed":
                raise PlannerUnavailable("public_basis_changed") from None
            raise


def _bind_citations_to_native_objects(
    citations: list[Any], public_bundle_raw: str, release_id: str,
) -> list[dict[str, Any]]:
    """Resolve producer citations to signed native evidence identities before revocation checks."""
    parsed: list[PublicObjectIdentity | None] = []
    for item in citations:
        try:
            parsed.append(PublicObjectIdentity(**item))
        except (TypeError, ValueError):
            parsed.append(None)
    if not public_bundle_raw and all(item is not None for item in parsed):
        return [item.as_dict() for item in parsed if item is not None]
    try:
        envelope = json.loads(public_bundle_raw)
    except (TypeError, json.JSONDecodeError):
        raise ValueError("public bundle is invalid") from None
    objects = envelope.get("objects") if isinstance(envelope, dict) else None
    if not isinstance(objects, dict):
        raise ValueError("public bundle objects are missing")
    native = objects.get(f"native-release:{release_id}")
    projection = objects.get(f"planner-view:{release_id}")
    if not isinstance(native, dict) or not isinstance(projection, dict):
        raise ValueError("public bundle release objects are missing")
    native_bundle = native.get("bundle")
    projection_bundle = projection.get("bundle")
    if not isinstance(native_bundle, dict) or not isinstance(projection_bundle, dict):
        raise ValueError("public bundle release content is malformed")
    native_evidence = native_bundle.get("evidence")
    projected_evidence = projection_bundle.get("evidence")
    if not isinstance(native_evidence, list) or not isinstance(projected_evidence, list):
        raise ValueError("public bundle evidence is missing")
    native_by_id: dict[str, dict[str, Any]] = {}
    for item in native_evidence:
        if isinstance(item, dict) and isinstance(item.get("id"), str):
            if item["id"] in native_by_id:
                raise ValueError("duplicate native evidence identity")
            native_by_id[item["id"]] = item
    projection_by_identity: dict[tuple[str, int], dict[str, Any]] = {}
    for item in projected_evidence:
        if (isinstance(item, dict) and isinstance(item.get("id"), str)
                and isinstance(item.get("revision"), int)
                and not isinstance(item.get("revision"), bool)):
            key = (item["id"], item["revision"])
            if key in projection_by_identity:
                raise ValueError("duplicate projected evidence identity")
            projection_by_identity[key] = item

    bound: list[dict[str, Any]] = []
    for item, typed in zip(citations, parsed, strict=True):
        if not isinstance(item, dict):
            raise ValueError("citation must be an object")
        object_id = typed.id if typed is not None else item.get("id")
        revision = typed.revision if typed is not None else item.get("revision")
        if (not isinstance(object_id, str) or not object_id
                or not isinstance(revision, int) or isinstance(revision, bool)
                or revision < 1
                or (typed is None and item.get("index_release_id") != release_id)
                or (typed is not None and typed.kind != "evidence")):
            raise ValueError("citation does not identify this release")
        projected = projection_by_identity.get((object_id, revision))
        source = native_by_id.get(object_id)
        if (projected is None or source is None
                or projected.get("source_content_hash") != source.get("content_hash")):
            raise ValueError("citation does not resolve to matching native evidence")
        identity = PublicObjectIdentity(
            "evidence", object_id, revision, HASH_PROFILE, source["content_hash"],
        )
        if typed is not None and typed != identity:
            raise ValueError("typed citation differs from signed native evidence")
        bound.append(identity.as_dict())
    return bound
