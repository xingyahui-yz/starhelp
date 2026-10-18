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
        if result.result.get("index_release_id") != release_id:
            raise PlannerUnavailable("planner result belongs to a different public release")
        public_objects = bundle.get("objects")
        if not isinstance(public_objects, dict):
            raise PlannerUnavailable("analysis request has no complete public object graph")
        planner_view = public_objects.get(f"planner-view:{release_id}")
        planner_payload = planner_view.get("bundle") if isinstance(planner_view, dict) else None
        evidence = planner_payload.get("evidence") if isinstance(planner_payload, dict) else None
        if not isinstance(evidence, list):
            raise PlannerUnavailable("analysis request has no public evidence catalog")
        evidence_by_id = {
            item["id"]: item
            for item in evidence
            if isinstance(item, dict) and isinstance(item.get("id"), str)
        }
        citations = result.result.get("citations", [])
        if not isinstance(citations, list) or not citations:
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
            or not isinstance(evidence_by_id.get(item.get("id")), dict)
            or evidence_by_id[item["id"]].get("revision") != item["revision"]
            for item in citations
        ):
            raise PlannerUnavailable(
                "planner result has malformed, missing, or cross-release references"
            )
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
