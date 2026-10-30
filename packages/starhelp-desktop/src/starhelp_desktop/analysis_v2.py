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
from .producer_v2 import PublicObjectIdentity
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
        inner = frozen["producer_request"]
        snapshot_data = json.loads(inner["account_snapshot"]["raw_json"])
        release_id = inner["public_bundle"]["expected_release_id"]
        if result.result.get("index_release_id") != release_id:
            raise PlannerUnavailable("v0.2 planner result belongs to a different release")
        citations = result.result.get("citations")
        if not isinstance(citations, list) or not citations:
            raise PlannerUnavailable("v0.2 result has no typed public citations")
        refs = frozenset(
            json.dumps(PublicObjectIdentity(**item).as_dict(), ensure_ascii=False,
                       sort_keys=True, separators=(",", ":"))
            for item in citations
            if isinstance(item, dict)
        )
        if len(refs) != len(citations):
            raise PlannerUnavailable("v0.2 result contains malformed or duplicate typed citations")
        task = dict(inner["task"])
        if "feedback" in inner:
            task["feedback"] = inner["feedback"]
        basis = inner["public_basis"]

        def stage() -> AnalysisReport:
            lifecycle.require_active(profile_id, authorization_generation)
            return self._reports.make_temporary(
                profile_id=profile_id, generation=authorization_generation,
                task=task, result=result.result,
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
