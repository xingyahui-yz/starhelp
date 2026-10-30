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
_PUBLIC_BASIS_CHANGED = "生成报告后公共依据 epoch 已变化；报告保留历史依据，不能恢复为当前方案"
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
    # A report is not current until its snapshot, release, and withdrawal state
    # have been checked by the host. Callers that construct one directly must
    # not inherit an optimistic status before that assessment.
    validity: ReportValidity = ReportValidity.NEEDS_REVIEW
    validity_reason: str | None = _PUBLIC_RELEASE_UNAVAILABLE
    public_basis_sha256: str | None = None
    public_epoch: int | None = None


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
        current_public_basis_sha256: str | None = None,
        current_public_epoch: int | None = None,
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
            current_public_basis_sha256=current_public_basis_sha256,
            current_public_epoch=current_public_epoch,
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
        public_basis_sha256: str | None = None,
        public_epoch: int | None = None,
    ) -> AnalysisReport:
        self._lifecycle.require_active(profile_id, generation)
        if ((public_basis_sha256 is None) != (public_epoch is None)
                or (public_basis_sha256 is not None and (
                    len(public_basis_sha256) != 64 or any(
                        character not in "0123456789abcdef" for character in public_basis_sha256
                    )
                ))
                or (public_epoch is not None and (
                    not isinstance(public_epoch, int) or isinstance(public_epoch, bool)
                    or public_epoch < 1
                ))):
            raise ValueError("public basis report identity is malformed")
        return AnalysisReport(
            report_id=uuid4(), profile_id=profile_id, authorization_generation=generation,
            created_at=datetime.now(UTC), task=task, result=result,
            snapshot_revision=snapshot_revision, public_release_id=public_release_id,
            planner_version=planner_version, public_refs=public_refs,
            public_basis_sha256=public_basis_sha256, public_epoch=public_epoch,
        )

    def save_explicitly(
        self,
        report: AnalysisReport,
        *,
        current_snapshot_revision: int | None,
        current_public_release_id: str | None = None,
        withdrawn_refs: frozenset[str] = frozenset(),
        withdrawal_status_known: bool = False,
        current_public_basis_sha256: str | None = None,
        current_public_epoch: int | None = None,
    ) -> Path:
        key = f"profile-{report.profile_id.hex}-report-{report.report_id.hex}"
        assessed = self._assess_snapshot(
            report,
            current_snapshot_revision,
            current_public_release_id=current_public_release_id,
            withdrawn_refs=withdrawn_refs,
            withdrawal_status_known=withdrawal_status_known,
            current_public_basis_sha256=current_public_basis_sha256,
            current_public_epoch=current_public_epoch,
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
        current_public_basis_sha256: str | None = None,
        current_public_epoch: int | None = None,
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
        if report.validity is ReportValidity.NEEDS_REVIEW and report.validity_reason == _PUBLIC_BASIS_CHANGED:
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
        if report.public_basis_sha256 is not None and (
            current_public_basis_sha256 != report.public_basis_sha256
            or current_public_epoch != report.public_epoch
        ):
            return replace(assessed, validity=ReportValidity.NEEDS_REVIEW,
                           validity_reason=_PUBLIC_BASIS_CHANGED)
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
        current_public_basis_sha256: str | None = None,
        current_public_epoch: int | None = None,
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
                current_public_basis_sha256=current_public_basis_sha256,
                current_public_epoch=current_public_epoch,
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
        current_public_basis_sha256: str | None,
        current_public_epoch: int | None,
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
                current_public_basis_sha256=current_public_basis_sha256,
                current_public_epoch=current_public_epoch,
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
            "public_basis_sha256": report.public_basis_sha256,
            "public_epoch": report.public_epoch,
        }

    @staticmethod
    def _from_dict(data: dict[str, Any]) -> AnalysisReport:
        validity = ReportValidity(data.get("validity", ReportValidity.NEEDS_REVIEW.value))
        validity_reason = (
            str(data["validity_reason"])
            if data.get("validity_reason") is not None
            else _PUBLIC_RELEASE_UNAVAILABLE if validity is ReportValidity.NEEDS_REVIEW else None
        )
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
            validity=validity,
            validity_reason=validity_reason,
            public_basis_sha256=(str(data["public_basis_sha256"])
                                 if data.get("public_basis_sha256") is not None else None),
            public_epoch=(int(data["public_epoch"])
                          if data.get("public_epoch") is not None else None),
        )
