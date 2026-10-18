from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from .lifecycle import ProfileLifecycle
from .planner import LocalPlannerProcess, PlannerResult, PlannerUnavailable
from .reports import AnalysisReport, ReportLifecycle


@dataclass(frozen=True, slots=True)
class ProducerAnalysisExecution:
    """One local analysis result and, when plans exist, its unsaved report."""

    planner_result: PlannerResult
    temporary_report: AnalysisReport | None


class ProducerAnalysisRunner:
    """Run a complete B-built request through the local worker and stage eligible output."""

    def __init__(self, planner: LocalPlannerProcess, reports: ReportLifecycle) -> None:
        self._planner = planner
        self._reports = reports

    def run(
        self,
        *,
        request: dict[str, Any],
        profile_id: UUID,
        authorization_generation: int,
        lifecycle: ProfileLifecycle,
    ) -> ProducerAnalysisExecution:
        """Analyze locally; never persist the result without a separate explicit save action."""
        result = self._planner.analyze(
            request=request,
            profile_id=profile_id,
            authorization_generation=authorization_generation,
            lifecycle=lifecycle,
        )
        if result.result.get("status") != "plans_available":
            return ProducerAnalysisExecution(result, None)

        snapshot = request["account_snapshot"]
        bundle = request["public_bundle"]
        manifest = bundle.get("manifest")
        if not isinstance(manifest, dict) or not isinstance(
            manifest.get("index_release_id"), str
        ):
            raise PlannerUnavailable("analysis request has no public release identity")
        release_id = manifest["index_release_id"]
        citations = result.result.get("citations", [])
        if not isinstance(citations, list):
            raise PlannerUnavailable("planner result has malformed public references")
        if any(
            not isinstance(item, dict)
            or not isinstance(item.get("id"), str)
            or not item["id"]
            or not isinstance(item.get("revision"), int)
            or isinstance(item.get("revision"), bool)
            or item["revision"] < 1
            or (item.get("index_release_id") is not None
                and item.get("index_release_id") != release_id)
            for item in citations
        ):
            raise PlannerUnavailable("planner result has malformed or cross-release references")
        public_refs = frozenset(
            f"{item['id']}@{item['revision']}"
            for item in citations
        )
        report = self._reports.make_temporary(
            profile_id=profile_id,
            generation=authorization_generation,
            task=request["task"],
            result=result.result,
            snapshot_revision=snapshot["snapshot_revision"],
            public_release_id=release_id,
            planner_version=result.planner_version,
            public_refs=public_refs,
        )
        return ProducerAnalysisExecution(result, report)
