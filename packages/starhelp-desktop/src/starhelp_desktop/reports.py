from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from .lifecycle import ProfileLifecycle
from .storage import EncryptedPrivateStore


class ReportValidity(StrEnum):
    CURRENT = "current"
    NEEDS_REVIEW = "needs_review"
    EXPIRED = "expired"
    EVIDENCE_WITHDRAWN = "evidence_withdrawn"


@dataclass(frozen=True, slots=True)
class AnalysisReport:
    report_id: UUID
    profile_id: UUID
    authorization_generation: int
    created_at: datetime
    task: dict[str, Any]
    result: dict[str, Any]
    snapshot_revision: int
    public_release_id: str
    planner_version: str
    validity: ReportValidity = ReportValidity.CURRENT
    validity_reason: str | None = None


class ReportLifecycle:
    def __init__(self, store: EncryptedPrivateStore, lifecycle: ProfileLifecycle) -> None:
        self._store = store
        self._lifecycle = lifecycle

    def make_temporary(
        self,
        *,
        profile_id: UUID,
        generation: int,
        task: dict[str, Any],
        result: dict[str, Any],
        snapshot_revision: int,
        public_release_id: str,
        planner_version: str,
    ) -> AnalysisReport:
        self._lifecycle.require_active(profile_id, generation)
        return AnalysisReport(
            report_id=uuid4(), profile_id=profile_id, authorization_generation=generation,
            created_at=datetime.now(UTC), task=task, result=result,
            snapshot_revision=snapshot_revision, public_release_id=public_release_id,
            planner_version=planner_version,
        )

    def save_explicitly(self, report: AnalysisReport) -> Path:
        self._lifecycle.require_active(report.profile_id, report.authorization_generation)
        key = f"profile-{report.profile_id.hex}-report-{report.report_id.hex}"
        return self._store.save(key, self._to_dict(report))

    def mark_stale(
        self,
        report: AnalysisReport,
        *,
        current_snapshot_revision: int,
        withdrawn_refs: frozenset[str] = frozenset(),
        report_refs: frozenset[str] = frozenset(),
    ) -> AnalysisReport:
        if withdrawn_refs & report_refs:
            return replace(report, validity=ReportValidity.EVIDENCE_WITHDRAWN,
                           validity_reason="引用证据已知撤回")
        if current_snapshot_revision != report.snapshot_revision:
            return replace(report, validity=ReportValidity.EXPIRED,
                           validity_reason="账号快照已更新")
        return report

    @staticmethod
    def _to_dict(report: AnalysisReport) -> dict[str, Any]:
        return {
            "report_id": str(report.report_id),
            "profile_id": str(report.profile_id),
            "authorization_generation": report.authorization_generation,
            "created_at": report.created_at.isoformat(),
            "task": report.task,
            "result": report.result,
            "snapshot_revision": report.snapshot_revision,
            "public_release_id": report.public_release_id,
            "planner_version": report.planner_version,
            "validity": report.validity.value,
            "validity_reason": report.validity_reason,
        }
