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


_SNAPSHOT_UNAVAILABLE = "当前账号快照不可用，无法核验报告依据"
_PUBLIC_RELEASE_UNAVAILABLE = "本机当前公共资料版本未知，无法核对报告依据"
_PUBLIC_RELEASE_CHANGED = "本机当前公共资料版本已变化；旧报告保留原版本依据"
_WITHDRAWAL_STATUS_UNKNOWN = "最新公共资料撤回/禁用状态未知"
_RECHECKABLE_REASONS = frozenset({
    _SNAPSHOT_UNAVAILABLE,
    _PUBLIC_RELEASE_UNAVAILABLE,
    _PUBLIC_RELEASE_CHANGED,
    _WITHDRAWAL_STATUS_UNKNOWN,
})


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

    def assess_for_display(
        self,
        report: AnalysisReport,
        *,
        current_snapshot_revision: int | None,
        current_public_release_id: str | None = None,
        withdrawn_refs: frozenset[str] = frozenset(),
        withdrawal_status_known: bool = False,
    ) -> AnalysisReport:
        """Refresh an unsaved report's validity without persisting the report."""
        self._lifecycle.require_active(
            report.profile_id, report.authorization_generation
        )
        return self._assess_snapshot(
            report,
            current_snapshot_revision,
            current_public_release_id=current_public_release_id,
            withdrawn_refs=withdrawn_refs,
            withdrawal_status_known=withdrawal_status_known,
        )

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

    def save_explicitly(
        self,
        report: AnalysisReport,
        *,
        current_snapshot_revision: int | None,
        current_public_release_id: str | None = None,
        withdrawn_refs: frozenset[str] = frozenset(),
        withdrawal_status_known: bool = False,
    ) -> Path:
        key = f"profile-{report.profile_id.hex}-report-{report.report_id.hex}"
        assessed = self._assess_snapshot(
            report,
            current_snapshot_revision,
            current_public_release_id=current_public_release_id,
            withdrawn_refs=withdrawn_refs,
            withdrawal_status_known=withdrawal_status_known,
        )
        return self._lifecycle.run_authorized(
            report.profile_id,
            report.authorization_generation,
            lambda: self._store.save(key, self._to_dict(assessed)),
        )

    def _assess_snapshot(
        self,
        report: AnalysisReport,
        current_snapshot_revision: int | None,
        *,
        current_public_release_id: str | None = None,
        withdrawn_refs: frozenset[str] = frozenset(),
        withdrawal_status_known: bool = False,
    ) -> AnalysisReport:
        if not isinstance(withdrawal_status_known, bool):
            raise ValueError("withdrawal status knowledge must be an explicit boolean")
        if report.validity is ReportValidity.EVIDENCE_WITHDRAWN:
            return report
        if withdrawn_refs & report.public_refs:
            return replace(report, validity=ReportValidity.EVIDENCE_WITHDRAWN,
                           validity_reason="引用证据已知撤回")
        if report.validity is ReportValidity.EXPIRED:
            return report
        if (report.validity is ReportValidity.NEEDS_REVIEW
                and report.validity_reason in _RECHECKABLE_REASONS):
            report = replace(report, validity=ReportValidity.CURRENT, validity_reason=None)
        if current_snapshot_revision is None:
            return replace(report, validity=ReportValidity.NEEDS_REVIEW,
                           validity_reason=_SNAPSHOT_UNAVAILABLE)
        assessed = self.mark_stale(
            report,
            current_snapshot_revision=current_snapshot_revision,
            withdrawn_refs=withdrawn_refs,
            report_refs=report.public_refs,
        )
        if assessed.validity in {ReportValidity.EXPIRED, ReportValidity.EVIDENCE_WITHDRAWN}:
            return assessed
        if current_public_release_id is None:
            return replace(assessed, validity=ReportValidity.NEEDS_REVIEW,
                           validity_reason=_PUBLIC_RELEASE_UNAVAILABLE)
        if current_public_release_id != assessed.public_release_id:
            return replace(assessed, validity=ReportValidity.NEEDS_REVIEW,
                           validity_reason=_PUBLIC_RELEASE_CHANGED)
        if not withdrawal_status_known:
            return replace(assessed, validity=ReportValidity.NEEDS_REVIEW,
                           validity_reason=_WITHDRAWAL_STATUS_UNKNOWN)
        return assessed

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
        current_public_release_id: str | None = None,
        withdrawn_refs: frozenset[str] = frozenset(),
        withdrawal_status_known: bool = False,
    ) -> tuple[AnalysisReport, ...]:
        return self._lifecycle.run_authorized(
            profile_id,
            generation,
            lambda: self._list_saved_active(
                profile_id=profile_id,
                generation=generation,
                current_snapshot_revision=current_snapshot_revision,
                current_public_release_id=current_public_release_id,
                withdrawn_refs=withdrawn_refs,
                withdrawal_status_known=withdrawal_status_known,
            ),
        )

    def _list_saved_active(
        self,
        *,
        profile_id: UUID,
        generation: int,
        current_snapshot_revision: int | None,
        current_public_release_id: str | None,
        withdrawn_refs: frozenset[str],
        withdrawal_status_known: bool,
    ) -> tuple[AnalysisReport, ...]:
        reports: list[AnalysisReport] = []
        for key in self._store.list_profile_keys(profile_id, "report"):
            data = self._store.load(key)
            report = self._from_dict(data)
            if report.profile_id != profile_id:
                raise ValueError("saved report belongs to a different profile")
            if report.authorization_generation != generation:
                raise ValueError("saved report belongs to an older authorization generation")
            updated = self._assess_snapshot(
                report,
                current_snapshot_revision,
                current_public_release_id=current_public_release_id,
                withdrawn_refs=withdrawn_refs,
                withdrawal_status_known=withdrawal_status_known,
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
