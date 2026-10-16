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
    public_refs: frozenset[str] = frozenset()
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
        public_refs: frozenset[str] = frozenset(),
    ) -> AnalysisReport:
        self._lifecycle.require_active(profile_id, generation)
        return AnalysisReport(
            report_id=uuid4(), profile_id=profile_id, authorization_generation=generation,
            created_at=datetime.now(UTC), task=task, result=result,
            snapshot_revision=snapshot_revision, public_release_id=public_release_id,
            planner_version=planner_version, public_refs=public_refs,
        )

    def save_explicitly(self, report: AnalysisReport) -> Path:
        key = f"profile-{report.profile_id.hex}-report-{report.report_id.hex}"
        return self._lifecycle.run_authorized(
            report.profile_id,
            report.authorization_generation,
            lambda: self._store.save(key, self._to_dict(report)),
        )

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
        if report.validity in {ReportValidity.EVIDENCE_WITHDRAWN, ReportValidity.EXPIRED}:
            return report
        if current_snapshot_revision != report.snapshot_revision:
            return replace(report, validity=ReportValidity.EXPIRED,
                           validity_reason="账号快照已更新")
        return report

    def list_saved(
        self,
        *,
        profile_id: UUID,
        generation: int,
        current_snapshot_revision: int | None,
        withdrawn_refs: frozenset[str] = frozenset(),
    ) -> tuple[AnalysisReport, ...]:
        return self._lifecycle.run_authorized(
            profile_id,
            generation,
            lambda: self._list_saved_active(
                profile_id=profile_id,
                generation=generation,
                current_snapshot_revision=current_snapshot_revision,
                withdrawn_refs=withdrawn_refs,
            ),
        )

    def _list_saved_active(
        self,
        *,
        profile_id: UUID,
        generation: int,
        current_snapshot_revision: int | None,
        withdrawn_refs: frozenset[str],
    ) -> tuple[AnalysisReport, ...]:
        reports: list[AnalysisReport] = []
        for key in self._store.list_profile_keys(profile_id, "report"):
            data = self._store.load(key)
            report = self._from_dict(data)
            if report.profile_id != profile_id:
                raise ValueError("saved report belongs to a different profile")
            if report.authorization_generation != generation:
                raise ValueError("saved report belongs to an older authorization generation")
            current_revision = current_snapshot_revision
            if current_revision is None:
                updated = replace(
                    report,
                    validity=ReportValidity.NEEDS_REVIEW,
                    validity_reason="当前账号快照不可用，无法核验报告依据",
                )
            else:
                updated = self.mark_stale(
                    report,
                    current_snapshot_revision=current_revision,
                    withdrawn_refs=withdrawn_refs,
                    report_refs=report.public_refs,
                )
            if updated != report:
                self._store.save(key, self._to_dict(updated))
            reports.append(updated)
        return tuple(sorted(reports, key=lambda item: item.created_at, reverse=True))

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
            "public_refs": sorted(report.public_refs),
            "validity": report.validity.value,
            "validity_reason": report.validity_reason,
        }

    @staticmethod
    def _from_dict(data: dict[str, Any]) -> AnalysisReport:
        return AnalysisReport(
            report_id=UUID(data["report_id"]),
            profile_id=UUID(data["profile_id"]),
            authorization_generation=int(data["authorization_generation"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            task=dict(data["task"]),
            result=dict(data["result"]),
            snapshot_revision=int(data["snapshot_revision"]),
            public_release_id=str(data["public_release_id"]),
            planner_version=str(data["planner_version"]),
            public_refs=frozenset(str(item) for item in data.get("public_refs", [])),
            validity=ReportValidity(data.get("validity", ReportValidity.CURRENT.value)),
            validity_reason=(str(data["validity_reason"])
                             if data.get("validity_reason") is not None else None),
        )
