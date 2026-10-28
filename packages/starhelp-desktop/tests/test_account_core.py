from __future__ import annotations

import hashlib
import hmac
import json
import os
import sys
import threading
import tempfile
import time
import unittest
import urllib.request
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QDialog, QListWidget, QMessageBox

from starhelp_desktop.bundles import (
    BundleRejected,
    BundleValidator,
    PublicBundleCache,
    PublicBundleSynchronizer,
    ValidatedBundle,
)
from starhelp_desktop.equipment import EquipmentIdentityService, EquipmentMergeConflictError
from starhelp_desktop.gui import (
    AccountsPage,
    ReportsPage,
    PublicKnowledgePage,
    StarHelpWindow,
    TaskPage,
    _OcrWorker,
    _ProfileFetchWorker,
    _ProgressBus,
    _ProgressPage,
)
from starhelp_desktop.imports import (
    OcrDraft,
    OcrTextLine,
    RapidOcrEngine,
    StructuredImportAdapter,
    confirm_import,
    proposal_from_ocr_mapping,
    read_ocr_image,
)
from starhelp_desktop.lifecycle import ProfileLifecycle
from starhelp_desktop.merge import merge_import
from starhelp_desktop.models import (
    AccountSnapshot,
    EquipmentIdentity,
    EquipmentInstance,
    FieldFact,
    FieldStatus,
    ImportProposal,
    Ownership,
    ProfileAuthorization,
    SourceKind,
)
from starhelp_desktop.privacy import PublicQueryBuilder, PublicScope
from starhelp_desktop.planner import (
    LocalPlannerProcess,
    PlannerCancelled,
    PlannerUnavailable,
    _validate_request_envelope,
)
from starhelp_desktop.public_profile import (
    MihomoPublicProfileClient,
    ProfileRequestError,
    PublicProfileSelection,
    _RejectRedirects,
)
from starhelp_desktop.profiles import ProfileRepository
from starhelp_desktop.progress import PlayerProgressEntry, ProgressRepository
from starhelp_desktop.reports import ReportLifecycle, ReportValidity
from starhelp_desktop.storage import EncryptedPrivateStore, WindowsDpapiProtector
from starhelp_desktop.tasks import AnalysisTaskDraft, TaskRepository


class TestProtector:
    def protect(self, data: bytes) -> bytes:
        return bytes(value ^ 0xA5 for value in data)

    def unprotect(self, data: bytes) -> bytes:
        return bytes(value ^ 0xA5 for value in data)


def fact(value: object, source: str = "manual") -> FieldFact:
    return FieldFact(
        value=value,
        status=FieldStatus.CONFIRMED,
        source_kind=SourceKind.MANUAL,
        source_id=source,
        observed_at=datetime(2026, 10, 15, tzinfo=UTC),
        confirmed_at=datetime(2026, 10, 15, tzinfo=UTC),
    )


def temporary_directory() -> tempfile.TemporaryDirectory[str]:
    return tempfile.TemporaryDirectory(dir=Path(__file__).parent)


class MergeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.profile_id = uuid4()
        self.snapshot = AccountSnapshot(
            profile_id=self.profile_id,
            snapshot_id=uuid4(),
            revision=3,
            generated_at=datetime(2026, 10, 14, tzinfo=UTC),
            fields={"character:101.level": fact(80), "character:101.speed": fact(145)},
            ownership={"101": Ownership.OWNED, "102": Ownership.UNKNOWN},
            coverage=frozenset({"character:101.level", "character:101.speed", "ownership:101"}),
        )

    def test_partial_refresh_only_updates_covered_fields(self) -> None:
        incoming = FieldFact(79, FieldStatus.NEEDS_REVIEW, SourceKind.PUBLIC_PROFILE,
                             "fixture-source", datetime(2026, 10, 15, tzinfo=UTC))
        existing_fields = dict(self.snapshot.fields)
        existing_fields["character:101.level"] = FieldFact(
            80, FieldStatus.CONFIRMED, SourceKind.PUBLIC_PROFILE, "fixture-source",
            datetime(2026, 10, 14, tzinfo=UTC), datetime(2026, 10, 14, tzinfo=UTC),
        )
        snapshot = replace(self.snapshot, fields=existing_fields)
        proposal = ImportProposal.create(
            source_kind=SourceKind.PUBLIC_PROFILE,
            source_id="fixture-source",
            observed_at=datetime(2026, 10, 15, tzinfo=UTC),
            fields={"character:101.level": incoming},
            coverage=frozenset({"character:101.level"}),
        )
        result = merge_import(snapshot, confirm_import(proposal))
        self.assertEqual(result.snapshot.fields["character:101.level"].value, 79)
        self.assertEqual(result.snapshot.fields["character:101.speed"].value, 145)
        self.assertEqual(result.snapshot.fields["character:101.speed"].observed_at,
                         self.snapshot.fields["character:101.speed"].observed_at)
        self.assertEqual(result.retained_uncovered, frozenset({"character:101.speed", "ownership:101"}))

    def test_conflict_is_not_silently_overwritten_and_can_be_confirmed(self) -> None:
        proposal = ImportProposal.create(
            source_kind=SourceKind.OCR,
            source_id="synthetic-ocr",
            observed_at=datetime(2026, 10, 15, tzinfo=UTC),
            fields={"character:101.level": fact(78, "synthetic-ocr")},
            coverage=frozenset({"character:101.level"}),
        )
        confirmed_proposal = confirm_import(proposal)
        result = merge_import(self.snapshot, confirmed_proposal)
        self.assertEqual(result.snapshot.fields["character:101.level"].value, 80)
        self.assertEqual(len(result.conflicts), 1)
        confirmed = merge_import(self.snapshot, confirmed_proposal, confirmed_conflict_values={
            "character:101.level": "incoming",
        })
        self.assertEqual(confirmed.snapshot.fields["character:101.level"].value, 78)
        self.assertEqual(confirmed.snapshot.fields["character:101.level"].status, FieldStatus.CONFIRMED)

    def test_equipment_type_and_identical_stats_do_not_merge_instances(self) -> None:
        one = EquipmentInstance(uuid4(), "relic-type-9", "head", EquipmentIdentity.UNCONFIRMED,
                               "101", {"crit": fact(0.1)})
        two = EquipmentInstance(uuid4(), "relic-type-9", "head", EquipmentIdentity.UNCONFIRMED,
                               "101", {"crit": fact(0.1)})
        proposal = ImportProposal.create(
            source_kind=SourceKind.STRUCTURED_IMPORT,
            source_id="synthetic-file",
            observed_at=datetime(2026, 10, 15, tzinfo=UTC),
            fields={},
            equipment=(two,),
            coverage=frozenset({"equipment:displayed"}),
        )
        result = merge_import(replace(self.snapshot, equipment=(one,)), confirm_import(proposal))
        self.assertEqual(len(result.snapshot.equipment), 2)
        self.assertFalse(any(item.may_be_reassigned for item in result.snapshot.equipment))

    def test_snapshot_rejects_duplicate_local_equipment_instance_ids(self) -> None:
        instance_id = uuid4()
        first = EquipmentInstance(
            instance_id, "fixture:light-cone", "light_cone", EquipmentIdentity.PLAYER_CONFIRMED,
            "101",
        )
        duplicate = EquipmentInstance(
            instance_id, "fixture:relic", "body", EquipmentIdentity.UNCONFIRMED, "102",
        )

        with self.assertRaisesRegex(ValueError, "duplicate local equipment instance identity"):
            replace(self.snapshot, equipment=(first, duplicate))

    def test_only_player_action_establishes_equipment_identity(self) -> None:
        one = EquipmentInstance(uuid4(), "relic-type-9", "head", EquipmentIdentity.AMBIGUOUS,
                                "101", {"crit": fact(0.1)})
        two = EquipmentInstance(uuid4(), "relic-type-9", "head", EquipmentIdentity.UNCONFIRMED,
                                "101", {"crit": fact(0.1)})
        snapshot = replace(self.snapshot, equipment=(one, two))
        identity = EquipmentIdentityService()
        confirmed = identity.confirm_instance(snapshot, one.local_instance_id)
        self.assertTrue(confirmed.equipment[0].may_be_reassigned)
        self.assertFalse(confirmed.equipment[1].may_be_reassigned)
        linked = identity.link_import_to_existing(
            confirmed, imported_instance_id=two.local_instance_id,
            existing_instance_id=one.local_instance_id, player_confirmed_same_copy=True,
        )
        self.assertEqual(len(linked.equipment), 1)
        self.assertEqual(linked.equipment[0].local_instance_id, one.local_instance_id)

    def test_duplicate_equipment_link_requires_per_field_conflict_choices(self) -> None:
        one = EquipmentInstance(
            uuid4(), "relic-type-9", "head", EquipmentIdentity.PLAYER_CONFIRMED,
            "101", {"crit": fact(0.1, "existing"), "speed": fact(4, "existing")},
        )
        duplicate = EquipmentInstance(
            uuid4(), "relic-type-9", "head", EquipmentIdentity.UNCONFIRMED,
            "102", {"crit": fact(0.2, "incoming"), "speed": fact(4, "incoming")},
        )
        snapshot = replace(self.snapshot, equipment=(one, duplicate))
        identity = EquipmentIdentityService()
        with self.assertRaises(EquipmentMergeConflictError) as raised:
            identity.link_import_to_existing(
                snapshot, imported_instance_id=duplicate.local_instance_id,
                existing_instance_id=one.local_instance_id, player_confirmed_same_copy=True,
            )
        self.assertEqual({item.path for item in raised.exception.conflicts},
                         {"crit", "owner_character_id"})
        self.assertEqual(len(snapshot.equipment), 2)

        linked = identity.link_import_to_existing(
            snapshot, imported_instance_id=duplicate.local_instance_id,
            existing_instance_id=one.local_instance_id, player_confirmed_same_copy=True,
            conflict_choices={"crit": "incoming", "owner_character_id": "existing"},
        )
        self.assertEqual(len(linked.equipment), 1)
        result = linked.equipment[0]
        self.assertEqual(result.local_instance_id, one.local_instance_id)
        self.assertEqual(result.owner_character_id, "101")
        self.assertEqual(result.facts["crit"].value, 0.2)
        self.assertEqual(result.facts["crit"].source_id, "incoming")
        self.assertEqual(result.facts["crit"].status, FieldStatus.CONFIRMED)
        self.assertEqual(result.facts["speed"].source_id, "existing")

    def test_duplicate_equipment_link_needs_player_confirmation_and_matching_type(self) -> None:
        one = EquipmentInstance(uuid4(), "relic-type-9", "head", EquipmentIdentity.AMBIGUOUS,
                                "101", {})
        duplicate = EquipmentInstance(uuid4(), "relic-type-8", "head", EquipmentIdentity.UNCONFIRMED,
                                      "101", {})
        snapshot = replace(self.snapshot, equipment=(one, duplicate))
        identity = EquipmentIdentityService()
        with self.assertRaises(PermissionError):
            identity.link_import_to_existing(
                snapshot, imported_instance_id=duplicate.local_instance_id,
                existing_instance_id=one.local_instance_id, player_confirmed_same_copy=False,
            )
        with self.assertRaisesRegex(ValueError, "type mismatch"):
            identity.link_import_to_existing(
                snapshot, imported_instance_id=duplicate.local_instance_id,
                existing_instance_id=one.local_instance_id, player_confirmed_same_copy=True,
            )


class ProgressPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        cls.app = QApplication.instance() or QApplication([])

    def test_public_query_consent_expires_when_uid_or_server_changes(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            store = EncryptedPrivateStore(root / "private", TestProtector())
            lifecycle = ProfileLifecycle(store, root / "temp")
            profiles = ProfileRepository(store, lifecycle)
            page = AccountsPage(profiles, lifecycle, _ProgressBus())
            page.uid.setText("100000999")
            page.server.setText("fixture-server")

            page.confirm_consent.setChecked(True)
            page.uid.setText("100000998")
            self.assertFalse(page.confirm_consent.isChecked())
            self.assertIn("重新确认", page.preview.toPlainText())

            page.confirm_consent.setChecked(True)
            page.server.setText("another-fixture-server")
            self.assertFalse(page.confirm_consent.isChecked())
            page.close()

    def test_import_preview_displays_equipment_identity_and_field_provenance(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            store = EncryptedPrivateStore(root / "private", TestProtector())
            lifecycle = ProfileLifecycle(store, root / "temp")
            repository = ProfileRepository(store, lifecycle)
            page = AccountsPage(repository, lifecycle, _ProgressBus())
            proposal = StructuredImportAdapter().preview_object({
                "schema_id": StructuredImportAdapter.SCHEMA_ID,
                "schema_version": StructuredImportAdapter.SCHEMA_VERSION,
                "source_id": "fixture-export",
                "observed_at": "2026-10-17T12:30:00+08:00",
                "fields": {},
                "equipment": [{
                    "public_type_id": "fixture:relic-type",
                    "slot": "fixture:body",
                    "owner_character_id": "fixture:character",
                    "facts": {
                        "attribute:fixture.speed": {
                            "value": 12,
                            "scope": "synthetic-main-affix",
                        },
                    },
                }],
            }).proposal

            page._render_proposal(proposal)

            rendered = page.preview.toPlainText()
            self.assertIn("类型 fixture:relic-type", rendered)
            self.assertIn("身份 unconfirmed", rendered)
            self.assertIn("attribute:fixture.speed = 12", rendered)
            self.assertIn("needs_review", rendered)
            self.assertIn("structured_import", rendered)
            self.assertIn("2026-10-17T04:30:00+00:00", rendered)
            self.assertIn("synthetic-main-affix", rendered)
            page.close()

    def test_window_close_cancels_background_tasks_without_revoking_profiles(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            store = EncryptedPrivateStore(root / "private", TestProtector())
            window = StarHelpWindow(store, root / "temp", PublicBundleCache(root / "cache"))
            profile = window.profiles.begin_profile(
                label="Synthetic shutdown profile",
                provider_id="local-import",
                server_label="fixture-region",
            )
            cancel = window.lifecycle.register_task(profile.profile_id, profile.generation)
            self.assertTrue(window.accounts_page.auto_refresh_timer.isActive())

            self.assertTrue(window.close())

            self.assertTrue(cancel.is_set())
            self.assertFalse(window.accounts_page.auto_refresh_timer.isActive())
            self.assertTrue(window.lifecycle.is_active(profile.profile_id, profile.generation))
            with self.assertRaisesRegex(PermissionError, "shutting down"):
                window.lifecycle.register_task(profile.profile_id, profile.generation)
            self.assertEqual(
                [item.profile_id for item in window.profiles.list_profiles()], [profile.profile_id]
            )

    def test_progress_page_keeps_only_bounded_session_history(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            store = EncryptedPrivateStore(root / "private", TestProtector())
            lifecycle = ProfileLifecycle(store, root / "temp")
            profiles = ProfileRepository(store, lifecycle)
            profile = profiles.begin_profile(
                label="synthetic progress profile",
                provider_id="mihomo-public-profile",
                server_label="fixture-server",
            )
            proposal = MihomoPublicProfileClient().to_preview({
                "player": {"memory_data": {"level": 8, "chaos_id": 1234, "chaos_level": 12}},
                "characters": [],
            })
            profiles.save_confirmed_import(profile.profile_id, profile.generation,
                                           confirm_import(proposal))

            bus = _ProgressBus()
            progress_records = ProgressRepository(store, lifecycle)
            page = _ProgressPage(profiles, progress_records, bus)
            page.show()
            self.app.processEvents()
            self.assertIn("Mihomo 忘却之庭摘要", page.mode_status.toPlainText())
            self.assertIn("memory_data.chaos_id: 1234", page.mode_status.toPlainText())
            for mode in _ProgressPage.MODES:
                self.assertIn(f"{mode}：未知", page.mode_status.toPlainText())
            page.record_period.setText("fixture-cycle-1")
            page.record_stage.setText("fixture-stage-2")
            page.record_note.setText("synthetic-player-note")
            page.add_record_button.click()
            self.app.processEvents()
            self.assertEqual(page.records.count(), 1)
            self.assertIn("玩家自述：已达成", page.records.item(0).text())
            self.assertIn("不提交给生产分析", page.mode_status.toPlainText())
            self.assertIn("混沌回忆：未知", page.mode_status.toPlainText())
            entries = progress_records.list_entries(profile.profile_id, profile.generation)
            self.assertEqual(len(entries), 1)
            self.assertEqual(entries[0].stage_label, "fixture-stage-2")
            progress_path = store.root / f"profile-{profile.profile_id.hex}-progress-notes.bin"
            self.assertTrue(progress_path.is_file())
            self.assertNotIn(b"synthetic-player-note", progress_path.read_bytes())
            page.records.setCurrentRow(0)
            with patch.object(QMessageBox, "question", return_value=QMessageBox.StandardButton.Yes):
                page.delete_record_button.click()
            self.app.processEvents()
            self.assertEqual(progress_records.list_entries(profile.profile_id, profile.generation), ())
            self.assertFalse(progress_path.exists())
            progress_records.add(PlayerProgressEntry.create(
                profile_id=profile.profile_id,
                authorization_generation=profile.generation,
                mode_label="虚构叙事",
                period_label="fixture-cycle-1",
                stage_label="fixture-stage-3",
                outcome="待确认",
            ))
            self.assertEqual(len(store.list_profile_keys(profile.profile_id, "progress")), 1)

            for index in range(_ProgressPage.MAX_HISTORY + 2):
                bus.updated.emit(f"synthetic operation {index}", -1 if index == 51 else index % 101)

            self.assertEqual(page.history.count(), _ProgressPage.MAX_HISTORY)
            self.assertIn("synthetic operation 51", page.history.item(0).text())
            self.assertNotIn("synthetic operation 0", [
                page.history.item(index).text() for index in range(page.history.count())
            ])
            self.assertIn("进行中", page.history.item(0).text())

            page.hide()
            profiles.revoke(profile.profile_id)
            page.show()
            self.app.processEvents()
            self.assertIn("尚无已授权档案", page.mode_status.toPlainText())
            self.assertEqual(store.list_profile_keys(profile.profile_id, "progress"), ())
            self.assertEqual(page.records.count(), 0)
            page.close()

    def test_task_and_report_pages_clear_revoked_profile_data_on_reentry(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            store = EncryptedPrivateStore(root / "private", TestProtector())
            lifecycle = ProfileLifecycle(store, root / "temp")
            profiles = ProfileRepository(store, lifecycle)
            profile = profiles.begin_profile(
                label="synthetic revoked profile",
                provider_id="synthetic-source",
                server_label="fixture-server",
            )
            tasks = TaskRepository(store, lifecycle)
            task = AnalysisTaskDraft.create(
                profile_id=profile.profile_id,
                authorization_generation=profile.generation,
                mode_label="fixture-mode",
                cycle_id="fixture-cycle-secret",
                stage_id="fixture-stage-secret",
                goal_label="fixture-goal",
            )
            tasks.save_last(task)

            reports = ReportLifecycle(store, lifecycle)
            report = reports.make_temporary(
                profile_id=profile.profile_id,
                generation=profile.generation,
                task={"fixture": "task"},
                result={"fixture": "synthetic-report-secret"},
                snapshot_revision=1,
                public_release_id="fixture-release",
                planner_version="fixture-planner",
            )
            reports.save_explicitly(report, current_snapshot_revision=1)

            task_page = TaskPage(profiles, tasks, _ProgressBus(), lifecycle, store)
            report_page = ReportsPage(
                profiles, lifecycle, store, PublicBundleCache(root / "public-cache")
            )
            task_page.show()
            report_page.show()
            self.app.processEvents()
            report_page.report_list.setCurrentRow(0)
            self.app.processEvents()
            self.assertEqual(task_page.stage.text(), "fixture-stage-secret")
            self.assertIn("synthetic-report-secret", report_page.detail.toPlainText())

            task_page.hide()
            report_page.hide()
            profiles.revoke(profile.profile_id)
            task_page.show()
            report_page.show()
            self.app.processEvents()

            self.assertIsNone(task_page.profile.currentData())
            self.assertEqual(task_page.cycle.text(), "")
            self.assertEqual(task_page.stage.text(), "")
            self.assertEqual(task_page.fixed.text(), "")
            self.assertEqual(report_page.report_list.count(), 0)
            self.assertEqual(report_page.detail.toPlainText(), "")
            self.assertIsNone(report_page.pending_report)
            self.assertNotIn("synthetic-report-secret", report_page.status.text())
            task_page.close()
            report_page.close()

    def test_pending_report_preview_marks_changed_snapshot_as_expired(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            store = EncryptedPrivateStore(root / "private", TestProtector())
            lifecycle = ProfileLifecycle(store, root / "temp")
            profiles = ProfileRepository(store, lifecycle)
            profile = profiles.begin_profile(
                label="synthetic report profile",
                provider_id="synthetic-source",
                server_label="fixture-server",
            )
            first_import = confirm_import(ImportProposal.create(
                source_kind=SourceKind.MANUAL,
                source_id="fixture-first-import",
                observed_at=datetime.now(UTC),
                fields={},
                coverage=frozenset(),
            ))
            snapshot = profiles.save_confirmed_import(
                profile.profile_id, profile.generation, first_import
            ).snapshot
            reports_page = ReportsPage(
                profiles, lifecycle, store, PublicBundleCache(root / "public-cache")
            )
            report = reports_page.reports.make_temporary(
                profile_id=profile.profile_id,
                generation=profile.generation,
                task={"fixture": "task"},
                result={"fixture": "result"},
                snapshot_revision=snapshot.revision,
                public_release_id="fixture-release",
                planner_version="fixture-planner",
            )
            reports_page.stage_temporary_report(report)
            self.assertEqual(reports_page.pending_report.validity, ReportValidity.CURRENT)
            self.assertIn('"状态": "current"', reports_page.detail.toPlainText())

            next_import = confirm_import(ImportProposal.create(
                source_kind=SourceKind.MANUAL,
                source_id="fixture-second-import",
                observed_at=datetime.now(UTC),
                fields={},
                coverage=frozenset(),
            ))
            profiles.save_confirmed_import(
                profile.profile_id, profile.generation, next_import
            )
            reports_page.refresh_reports()

            self.assertEqual(reports_page.pending_report.validity, ReportValidity.EXPIRED)
            self.assertIn("快照已变化", reports_page.status.text())
            self.assertIn("账号快照已更新", reports_page.status.text())
            self.assertIn('"状态": "expired"', reports_page.detail.toPlainText())
            self.assertIn("账号快照已更新", reports_page.detail.toPlainText())
            self.assertEqual(store.list_profile_keys(profile.profile_id, "report"), ())
            reports_page.close()

    def test_task_equipment_lock_picker_uses_only_current_profile_instances(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            store = EncryptedPrivateStore(root / "private", TestProtector())
            lifecycle = ProfileLifecycle(store, root / "temp")
            profiles = ProfileRepository(store, lifecycle)
            profile = profiles.begin_profile(
                label="synthetic equipment profile",
                provider_id="synthetic-source",
                server_label="fixture-server",
            )
            instance_id = uuid4()
            equipment = EquipmentInstance(
                local_instance_id=instance_id,
                public_type_id="fixture-equipment-type",
                slot="fixture-slot",
                identity=EquipmentIdentity.UNCONFIRMED,
                owner_character_id="fixture-character",
            )
            proposal = confirm_import(ImportProposal.create(
                source_kind=SourceKind.MANUAL,
                source_id="fixture-equipment-import",
                observed_at=datetime.now(UTC),
                fields={},
                equipment=(equipment,),
                coverage=frozenset({"equipment"}),
            ))
            profiles.save_confirmed_import(profile.profile_id, profile.generation, proposal)
            tasks = TaskRepository(store, lifecycle)
            page = TaskPage(profiles, tasks, _ProgressBus(), lifecycle, store)

            def choose_first_equipment() -> QDialog.DialogCode:
                dialog = page.findChild(QDialog)
                self.assertIsNotNone(dialog)
                choices = dialog.findChild(QListWidget, "equipmentLockChoices")
                self.assertIsNotNone(choices)
                choices.item(0).setCheckState(Qt.CheckState.Checked)
                return QDialog.DialogCode.Accepted

            with patch.object(QDialog, "exec", side_effect=choose_first_equipment):
                page.open_equipment_lock_picker()
            self.assertEqual(page.locked.text(), str(instance_id))

            page.cycle.setText("fixture-cycle")
            page.stage.setText("fixture-stage")
            page.create_task()
            saved = tasks.load_last(profile.profile_id, profile.generation)
            self.assertEqual(saved.locked_equipment_instance_ids, (str(instance_id),))

            page.locked.setText(str(uuid4()))
            with patch("starhelp_desktop.gui.QMessageBox.warning") as warning:
                page.create_task()
            warning.assert_called_once()
            self.assertEqual(
                tasks.load_last(profile.profile_id, profile.generation).locked_equipment_instance_ids,
                (str(instance_id),),
            )
            page.close()

    def test_task_character_pickers_show_snapshot_ownership_without_inference(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            store = EncryptedPrivateStore(root / "private", TestProtector())
            lifecycle = ProfileLifecycle(store, root / "temp")
            profiles = ProfileRepository(store, lifecycle)
            profile = profiles.begin_profile(
                label="synthetic character profile",
                provider_id="synthetic-source",
                server_label="fixture-server",
            )
            owned_id = "fixture-character-owned"
            not_owned_id = "fixture-character-not-owned"
            proposal = confirm_import(ImportProposal.create(
                source_kind=SourceKind.MANUAL,
                source_id="fixture-character-import",
                observed_at=datetime.now(UTC),
                fields={},
                ownership={owned_id: Ownership.OWNED, not_owned_id: Ownership.NOT_OWNED},
                coverage=frozenset({f"ownership:{owned_id}", f"ownership:{not_owned_id}"}),
            ))
            profiles.save_confirmed_import(profile.profile_id, profile.generation, proposal)
            tasks = TaskRepository(store, lifecycle)
            page = TaskPage(profiles, tasks, _ProgressBus(), lifecycle, store)

            def select_character(character_id: str, *, disabled_id: str | None = None):
                def accept_dialog() -> QDialog.DialogCode:
                    dialogs = page.findChildren(QDialog)
                    self.assertTrue(dialogs)
                    dialog = dialogs[-1]
                    choices = dialog.findChild(QListWidget, "characterChoices")
                    self.assertIsNotNone(choices)
                    found = False
                    for index in range(choices.count()):
                        item = choices.item(index)
                        current_id = item.data(Qt.ItemDataRole.UserRole)
                        if current_id == disabled_id:
                            self.assertFalse(bool(item.flags() & Qt.ItemFlag.ItemIsEnabled))
                        if current_id == character_id:
                            item.setCheckState(Qt.CheckState.Checked)
                            found = True
                    self.assertTrue(found)
                    return QDialog.DialogCode.Accepted

                return accept_dialog

            with patch.object(
                QDialog, "exec", side_effect=select_character(owned_id, disabled_id=not_owned_id)
            ):
                page.open_character_picker(page.fixed, "固定角色", owned_only=True)
            with patch.object(QDialog, "exec", side_effect=select_character(not_owned_id)):
                page.open_character_picker(page.excluded, "排除角色", owned_only=False)
            self.assertEqual(page.fixed.text(), owned_id)
            self.assertEqual(page.excluded.text(), not_owned_id)

            page.cycle.setText("fixture-cycle")
            page.stage.setText("fixture-stage")
            page.create_task()
            saved = tasks.load_last(profile.profile_id, profile.generation)
            self.assertEqual(saved.fixed_character_ids, (owned_id,))
            self.assertEqual(saved.excluded_character_ids, (not_owned_id,))

            page.excluded.clear()
            for invalid_fixed_id in (not_owned_id, "fixture-character-unknown"):
                page.fixed.setText(invalid_fixed_id)
                with patch("starhelp_desktop.gui.QMessageBox.warning") as warning:
                    page.create_task()
                warning.assert_called_once()
                self.assertIn("明确标记为 owned", warning.call_args.args[2])
                self.assertEqual(
                    tasks.load_last(profile.profile_id, profile.generation).fixed_character_ids,
                    (owned_id,),
                )
            page.close()

    def test_task_page_runs_explicit_synthetic_demo_and_stages_unsaved_report(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            store = EncryptedPrivateStore(root / "private", TestProtector())
            lifecycle = ProfileLifecycle(store, root / "temp")
            profiles = ProfileRepository(store, lifecycle)
            tasks = TaskRepository(store, lifecycle)
            cache = PublicBundleCache(root / "public-cache")
            bus = _ProgressBus()
            task_page = TaskPage(profiles, tasks, bus, lifecycle, store)
            reports_page = ReportsPage(profiles, lifecycle, store, cache)
            task_page.temporary_report_ready.connect(reports_page.stage_temporary_report)

            with patch(
                "starhelp_desktop.gui.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                task_page.synthetic_demo.click()

            deadline = time.monotonic() + 30
            while reports_page.pending_report is None and time.monotonic() < deadline:
                self.app.processEvents()
                time.sleep(0.01)

            self.assertIsNotNone(reports_page.pending_report)
            self.assertTrue(reports_page.pending_report.task.get("synthetic_demo"))
            demo_profiles = [
                item for item in profiles.list_profiles()
                if item.provider_id == "synthetic-demo"
            ]
            self.assertEqual(len(demo_profiles), 1)
            self.assertEqual(task_page.profile.currentData(), str(demo_profiles[0].profile_id))
            self.assertEqual(store.list_profile_keys(demo_profiles[0].profile_id, "report"), ())
            self.assertIn("合成联调完成", task_page.status.text())
            self.assertIn("仅合成 fixture", reports_page.status.text())
            report_text = reports_page.detail.toPlainText()
            self.assertIn("## 分析范围与目标", report_text)
            self.assertIn("## 当前配装方案", report_text)
            self.assertIn("## 培养与材料缺口", report_text)
            self.assertIn("## 公共证据引用", report_text)

            reports_page.save_pending_button.click()
            self.assertIsNone(reports_page.pending_report)
            self.assertEqual(
                len(store.list_profile_keys(demo_profiles[0].profile_id, "report")), 1
            )
            task_page.close()
            reports_page.close()

    def test_public_knowledge_page_shows_cached_coverage_and_marks_it_unverified(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            cache = PublicBundleCache(root / "public-cache")
            payload = {
                "schema_id": "PublicBundle",
                "manifest": {
                    "index_release_id": "fixture-release-offline",
                    "coverage": {"status": "synthetic", "reason": "fixture-only"},
                    "published_at": "2026-10-18T00:00:00Z",
                },
            }
            bundle = ValidatedBundle(
                release_id="fixture-release-offline",
                schema_version="0.1-draft",
                payload_json=json.dumps(payload).encode("utf-8"),
                coverage=payload["manifest"]["coverage"],
                verified_at=datetime(2026, 10, 18, tzinfo=UTC),
            )
            cache.activate(bundle)

            page = PublicKnowledgePage(cache)
            text = page.status.toPlainText()
            self.assertIn("fixture-release-offline", text)
            self.assertIn("synthetic", text)
            self.assertIn("未在本页验签", text)
            self.assertIn("最近撤回/禁用状态：未知", text)
            self.assertIn("本机最近验签记录（未签名回执）", text)
            self.assertIn("2026-10-18T00:00:00+00:00", text)

            receipt_file = cache.root / "verification-fixture-release-offline.json"
            receipt_file.write_bytes(b"{" + b" " * 8192)
            page.refresh_status()
            self.assertIn("本机验签记录：invalid", page.status.toPlainText())

            cache.activate(bundle)
            cached_file = cache.root / "release-fixture-release-offline.json"
            cached_file.write_bytes(cached_file.read_bytes() + b" ")
            page.refresh_status()
            self.assertIn("本机验签记录：mismatch", page.status.toPlainText())
            page.close()

    def test_account_page_cancellation_discards_late_public_profile_result(self) -> None:
        class EmptyRepository:
            def list_profiles(self):
                return []

        class Lifecycle:
            def __init__(self) -> None:
                self.unregistered = []

            def unregister_task(self, profile_id, generation, cancel) -> None:
                self.unregistered.append((profile_id, generation, cancel))

        lifecycle = Lifecycle()
        page = AccountsPage(EmptyRepository(), lifecycle, _ProgressBus())
        event = threading.Event()
        profile_id = uuid4()
        page.fetch_profile = type("Profile", (), {"profile_id": profile_id, "generation": 4})()
        page.pending_cancel = event
        page.cancel_fetch_button.setEnabled(True)

        page.cancel_fetch_button.click()
        self.assertTrue(event.is_set())
        self.assertFalse(page.cancel_fetch_button.isEnabled())
        self.assertIn("请求已经发出", page.preview.toPlainText())

        page._fetch_cancelled(event)
        self.assertIsNone(page.pending_cancel)
        self.assertIsNone(page.fetch_profile)
        self.assertEqual(lifecycle.unregistered, [(profile_id, 4, event)])
        cancelled_text = page.preview.toPlainText()
        page._fetch_completed(object(), event)
        self.assertEqual(page.preview.toPlainText(), cancelled_text)
        self.assertFalse(page.cancel_fetch_button.isEnabled())
        page.close()

    def test_profile_fetch_worker_emits_cancelled_after_network_result(self) -> None:
        class Client:
            def __init__(self, event: threading.Event) -> None:
                self.event = event

            def fetch(self, _selection):
                self.event.set()
                return object()

        client = MihomoPublicProfileClient()
        event = threading.Event()
        worker = _ProfileFetchWorker(
            Client(event), PublicProfileSelection("100000999", "CN", client.PROVIDER_ID, True), event
        )
        cancelled = []
        completed = []
        worker.signals.cancelled.connect(cancelled.append)
        worker.signals.completed.connect(lambda *_args: completed.append(True))

        worker.run()

        self.assertEqual(cancelled, [event])
        self.assertEqual(completed, [])

    def test_ocr_worker_discards_result_when_cancelled_during_recognition(self) -> None:
        event = threading.Event()
        worker = _OcrWorker(b"synthetic-image", event)
        draft = OcrDraft((), datetime.now(UTC))
        cancelled = []
        completed = []

        def recognize(_image_bytes: bytes) -> OcrDraft:
            event.set()
            return draft

        with patch("starhelp_desktop.gui.RapidOcrEngine") as engine:
            engine.return_value.recognize.side_effect = recognize
            worker.signals.cancelled.connect(cancelled.append)
            worker.signals.completed.connect(lambda *_args: completed.append(True))
            worker.run()

        self.assertEqual(cancelled, [event])
        self.assertEqual(completed, [])
        self.assertEqual(worker.image_bytes, b"")

    def test_account_switch_and_revoke_discard_profile_bound_ocr_preview(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            store = EncryptedPrivateStore(root / "private", TestProtector())
            lifecycle = ProfileLifecycle(store, root / "temp")
            repository = ProfileRepository(store, lifecycle)
            first = repository.begin_profile(
                label="Synthetic first", provider_id="local-import", server_label="fixture-region"
            )
            second = repository.begin_profile(
                label="Synthetic second", provider_id="local-import", server_label="fixture-region"
            )
            page = AccountsPage(repository, lifecycle, _ProgressBus())
            page.profile_list.setCurrentIndex(
                page.profile_list.findData(str(first.profile_id))
            )
            first_cancel = lifecycle.register_task(first.profile_id, first.generation)
            page.ocr_profile = first
            page.ocr_cancel = first_cancel
            page.ocr_draft = OcrDraft(
                lines=(OcrTextLine("synthetic first profile", 0.99, ()),),
                recognized_at=datetime.now(UTC),
            )
            page.ocr_candidate.addItem("synthetic OCR line", 0)
            page.pending = proposal_from_ocr_mapping(
                page.ocr_draft, {"character:fixture.level": 0}
            )
            page.pending_profile = first
            page.save_button.setEnabled(True)

            page.profile_list.setCurrentIndex(
                page.profile_list.findData(str(second.profile_id))
            )

            self.assertTrue(first_cancel.is_set())
            self.assertIsNone(page.ocr_draft)
            self.assertIsNone(page.ocr_profile)
            self.assertIsNone(page.pending)
            self.assertFalse(page.save_button.isEnabled())
            self.assertEqual(page.ocr_candidate.count(), 0)
            self.assertIn("旧档案", page.preview.toPlainText())

            page.profile_list.setCurrentIndex(
                page.profile_list.findData(str(first.profile_id))
            )
            revoke_cancel = lifecycle.register_task(first.profile_id, first.generation)
            page.ocr_profile = first
            page.ocr_cancel = revoke_cancel
            page.ocr_draft = OcrDraft(
                lines=(OcrTextLine("synthetic revoke profile", 0.99, ()),),
                recognized_at=datetime.now(UTC),
            )
            page.ocr_candidate.addItem("synthetic revoke line", 0)
            page.pending = proposal_from_ocr_mapping(
                page.ocr_draft, {"character:fixture.level": 0}
            )
            page.pending_profile = first
            page.save_button.setEnabled(True)
            with patch(
                "starhelp_desktop.gui.QMessageBox.question",
                return_value=QMessageBox.StandardButton.Yes,
            ):
                page.revoke_selected()

            self.assertTrue(revoke_cancel.is_set())
            self.assertFalse(lifecycle.accepts_result(first.profile_id, first.generation))
            self.assertIsNone(page.ocr_draft)
            self.assertIsNone(page.pending)
            self.assertFalse(page.save_button.isEnabled())
            self.assertEqual(page.ocr_candidate.count(), 0)
            self.assertEqual(
                [profile.profile_id for profile in repository.list_profiles()],
                [second.profile_id],
            )
            page.close()

    def test_account_switch_cancels_public_fetch_and_discards_late_preview(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            store = EncryptedPrivateStore(root / "private", TestProtector())
            lifecycle = ProfileLifecycle(store, root / "temp")
            repository = ProfileRepository(store, lifecycle)
            first = repository.begin_profile(
                label="Synthetic fetch first", provider_id="local-import",
                server_label="fixture-region",
            )
            second = repository.begin_profile(
                label="Synthetic fetch second", provider_id="local-import",
                server_label="fixture-region",
            )
            page = AccountsPage(repository, lifecycle, _ProgressBus())
            page.profile_list.setCurrentIndex(
                page.profile_list.findData(str(first.profile_id))
            )
            cancel = lifecycle.register_task(first.profile_id, first.generation)
            page.fetch_profile = first
            page.pending_cancel = cancel
            page.pending_auto_refresh = True
            page.cancel_fetch_button.setEnabled(True)

            page.profile_list.setCurrentIndex(
                page.profile_list.findData(str(second.profile_id))
            )

            self.assertTrue(cancel.is_set())
            self.assertIsNone(page.fetch_profile)
            self.assertIsNone(page.pending_cancel)
            self.assertIsNone(page.pending)
            self.assertIsNone(page.pending_profile)
            self.assertFalse(page.cancel_fetch_button.isEnabled())
            cancelled_text = page.preview.toPlainText()
            self.assertIn("已切换档案", cancelled_text)
            page._fetch_completed(ImportProposal.create(
                source_kind=SourceKind.PUBLIC_PROFILE,
                source_id="synthetic-late-response",
                observed_at=datetime.now(UTC),
                fields={},
                coverage=frozenset(),
            ), cancel)
            page._fetch_failed("synthetic late failure", cancel)
            self.assertEqual(page.preview.toPlainText(), cancelled_text)
            self.assertEqual(
                [entry.profile_id for entry in repository.list_profiles()],
                [first.profile_id, second.profile_id],
            )
            page.close()

    def test_account_switch_discards_bound_structured_import_preview(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            store = EncryptedPrivateStore(root / "private", TestProtector())
            lifecycle = ProfileLifecycle(store, root / "temp")
            repository = ProfileRepository(store, lifecycle)
            first = repository.begin_profile(
                label="Synthetic import first", provider_id="local-import",
                server_label="fixture-region",
            )
            second = repository.begin_profile(
                label="Synthetic import second", provider_id="local-import",
                server_label="fixture-region",
            )
            page = AccountsPage(repository, lifecycle, _ProgressBus())
            page.profile_list.setCurrentIndex(
                page.profile_list.findData(str(first.profile_id))
            )
            page.pending = StructuredImportAdapter().preview_object({
                "schema_id": StructuredImportAdapter.SCHEMA_ID,
                "schema_version": StructuredImportAdapter.SCHEMA_VERSION,
                "observed_at": "2026-10-18T00:00:00Z",
                "fields": {"character:fixture.level": {"value": 80}},
            }).proposal
            page.pending_profile = first
            page._render_proposal(page.pending)
            page.save_button.setEnabled(True)

            page.profile_list.setCurrentIndex(
                page.profile_list.findData(str(second.profile_id))
            )

            self.assertIsNone(page.pending)
            self.assertIsNone(page.pending_profile)
            self.assertFalse(page.save_button.isEnabled())
            self.assertIn("旧档案导入预览已清除", page.preview.toPlainText())
            self.assertEqual(store.list_profile_keys(first.profile_id, "snapshot"), ())
            self.assertEqual(store.list_profile_keys(second.profile_id, "snapshot"), ())
            page.close()


class ImportAndPrivacyTests(unittest.TestCase):
    def test_ocr_image_file_read_is_bounded_without_a_size_check_race(self) -> None:
        with temporary_directory() as directory:
            image_path = Path(directory) / "synthetic.png"
            with patch.object(RapidOcrEngine, "MAX_IMAGE_BYTES", 8):
                image_path.write_bytes(b"12345678")
                self.assertEqual(read_ocr_image(image_path), b"12345678")

                image_path.write_bytes(b"123456789")
                with self.assertRaisesRegex(ValueError, "16 MiB"):
                    read_ocr_image(image_path)

                image_path.write_bytes(b"")
                with self.assertRaisesRegex(ValueError, "为空"):
                    read_ocr_image(image_path)

    def test_public_uid_redirects_are_rejected(self) -> None:
        handler = _RejectRedirects()
        request = urllib.request.Request(
            "https://api.mihomo.me/sr_info_parsed/100000999?lang=cn"
        )
        self.assertIsNone(handler.redirect_request(
            request, None, 302, "Found", {}, "https://other.example/redirected"
        ))

    def test_structured_import_rejects_uid_and_credentials(self) -> None:
        adapter = StructuredImportAdapter()
        base = {
            "schema_id": adapter.SCHEMA_ID,
            "schema_version": adapter.SCHEMA_VERSION,
            "observed_at": "2026-10-15T00:00:00Z",
            "fields": {"character:fixture.level": {"value": 80}},
        }
        with self.assertRaisesRegex(ValueError, "credential-like"):
            adapter.preview_object({**base, "uid": "100000999"})
        with self.assertRaisesRegex(ValueError, "credential-like"):
            adapter.preview_object({**base, "other": {"access_token": "secret"}})
        preview = adapter.preview_object(base)
        self.assertEqual(preview.proposal.fields["character:fixture.level"].value, 80)
        self.assertFalse(preview.proposal.confirmed)

    def test_structured_import_preserves_equipment_facts_as_unconfirmed_local_facts(self) -> None:
        adapter = StructuredImportAdapter()
        preview = adapter.preview_object({
            "schema_id": adapter.SCHEMA_ID,
            "schema_version": adapter.SCHEMA_VERSION,
            "source_id": "fixture-export",
            "observed_at": "2026-10-17T12:30:00+08:00",
            "fields": {"character:fixture.level": {"value": 80}},
            "equipment": [{
                "public_type_id": "fixture:relic-type",
                "slot": "fixture:body",
                "owner_character_id": "fixture:character",
                "facts": {
                    "attribute:fixture.speed": {
                        "value": 12,
                        "scope": "synthetic-main-affix",
                    },
                    "attribute:fixture.crit": {"value": 0.1},
                },
            }],
        })

        equipment = preview.proposal.equipment[0]
        self.assertEqual(preview.raw_field_count, 3)
        self.assertEqual(equipment.public_type_id, "fixture:relic-type")
        self.assertEqual(equipment.owner_character_id, "fixture:character")
        self.assertEqual(equipment.identity, EquipmentIdentity.UNCONFIRMED)
        self.assertEqual(equipment.facts["attribute:fixture.speed"].value, 12)
        self.assertEqual(equipment.facts["attribute:fixture.speed"].scope,
                         "synthetic-main-affix")
        for fact in equipment.facts.values():
            self.assertEqual(fact.source_kind, SourceKind.STRUCTURED_IMPORT)
            self.assertEqual(fact.source_id, "fixture-export")
            self.assertEqual(fact.observed_at.isoformat(), "2026-10-17T04:30:00+00:00")
            self.assertIsNone(fact.confirmed_at)
            self.assertEqual(fact.status, FieldStatus.NEEDS_REVIEW)
        self.assertFalse(preview.proposal.confirmed)

    def test_structured_import_rejects_invalid_equipment_fact_paths_and_identifiers(self) -> None:
        adapter = StructuredImportAdapter()
        base = {
            "schema_id": adapter.SCHEMA_ID,
            "schema_version": adapter.SCHEMA_VERSION,
            "observed_at": "2026-10-17T00:00:00Z",
            "fields": {},
            "equipment": [{"public_type_id": "fixture:type", "slot": "fixture:body"}],
        }
        invalid_cases = (
            {"facts": {"profile.uid": {"value": "hidden"}}},
            {"facts": {"attribute:fixture.speed": 12}},
            {"facts": {"attribute:fixture.speed": {"value": 12, "scope": []}}},
            {"owner_character_id": "100000999"},
            {"public_type_id": "fixture:100000999"},
        )
        for override in invalid_cases:
            with self.subTest(override=override):
                equipment = {**base["equipment"][0], **override}
                with self.assertRaises(ValueError):
                    adapter.preview_object({**base, "equipment": [equipment]})

    def test_confirmed_import_confirms_equipment_facts_but_not_copy_identity(self) -> None:
        adapter = StructuredImportAdapter()
        proposal = adapter.preview_object({
            "schema_id": adapter.SCHEMA_ID,
            "schema_version": adapter.SCHEMA_VERSION,
            "source_id": "fixture-export",
            "observed_at": "2026-10-19T00:00:00Z",
            "fields": {},
            "equipment": [{
                "public_type_id": "fixture:relic-type",
                "slot": "fixture:body",
                "facts": {"attribute:fixture.speed": {"value": 12}},
            }],
        }).proposal

        confirmed = confirm_import(proposal)
        fact = confirmed.equipment[0].facts["attribute:fixture.speed"]
        self.assertTrue(confirmed.confirmed)
        self.assertEqual(fact.status, FieldStatus.CONFIRMED)
        self.assertIsNotNone(fact.confirmed_at)
        self.assertEqual(confirmed.equipment[0].identity, EquipmentIdentity.UNCONFIRMED)

        snapshot = AccountSnapshot(
            profile_id=uuid4(), snapshot_id=uuid4(), revision=0,
            generated_at=datetime.now(UTC),
        )
        merged = merge_import(snapshot, confirmed)
        self.assertEqual(merged.snapshot.equipment[0].facts["attribute:fixture.speed"].status,
                         FieldStatus.CONFIRMED)
        self.assertEqual(merged.snapshot.equipment[0].identity, EquipmentIdentity.UNCONFIRMED)

    def test_structured_import_rejects_excessive_json_complexity(self) -> None:
        adapter = StructuredImportAdapter()
        base: object = {"schema_id": adapter.SCHEMA_ID,
                        "schema_version": adapter.SCHEMA_VERSION,
                        "observed_at": "2026-10-15T00:00:00Z", "fields": {}}
        nested = base
        for _ in range(65):
            nested = {"nested": nested}
        with self.assertRaisesRegex(ValueError, "nesting limit"):
            adapter.preview_object(nested)

        with temporary_directory() as directory:
            path = Path(directory) / "duplicate.json"
            path.write_text(
                '{"schema_id":"starhelp.account-import","schema_id":"starhelp.account-import"}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                adapter.preview_file(path)

            path.write_bytes(b'{"schema_id":"starhelp.account-import","x":NaN}')
            with self.assertRaisesRegex(ValueError, "non-standard JSON number"):
                adapter.preview_file(path)

            path.write_bytes(b" " * (16 * 1024 * 1024 + 1))
            with self.assertRaisesRegex(ValueError, "16 MiB file limit"):
                adapter.preview_file(path)

    def test_public_profile_fetch_requires_explicit_confirmation(self) -> None:
        client = MihomoPublicProfileClient()
        with self.assertRaises(PermissionError):
            client.fetch(PublicProfileSelection("100000999", "CN", client.PROVIDER_ID, False))

    def test_public_profile_fetch_requires_returned_uid_match(self) -> None:
        client = MihomoPublicProfileClient()
        selection = PublicProfileSelection("100000999", "CN", client.PROVIDER_ID, True)

        class Response:
            status = 200

            def __init__(self, body: bytes) -> None:
                self.body = body

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self, _limit: int) -> bytes:
                return self.body

        class Opener:
            def __init__(self, body: bytes) -> None:
                self.response = Response(body)
                self.request_url: str | None = None

            def open(self, request, timeout: float):
                if not 1 <= timeout <= 60:
                    raise AssertionError("public profile request timeout is out of range")
                self.request_url = request.full_url
                return self.response

        matching = json.dumps({"player": {"uid": selection.uid}, "characters": []}).encode()
        opener = Opener(matching)
        with patch("urllib.request.build_opener", return_value=opener):
            self.assertEqual(client.fetch(selection).ownership, {})
        self.assertEqual(
            opener.request_url,
            "https://api.mihomo.me/sr_info_parsed/100000999?lang=cn",
        )

        for payload in (
            {"player": {"uid": "100000998"}, "characters": []},
            {"characters": []},
        ):
            with self.subTest(payload=payload):
                body = json.dumps(payload).encode()
                with patch("urllib.request.build_opener", return_value=Opener(body)):
                    with self.assertRaisesRegex(ProfileRequestError, "UID did not match") as raised:
                        client.fetch(selection)
                    self.assertNotIn("100000999", str(raised.exception))
                    self.assertNotIn("100000998", str(raised.exception))

    def test_mihomo_fixture_only_marks_displayed_character_owned(self) -> None:
        client = MihomoPublicProfileClient()
        proposal = client.to_preview({
            "player": {"uid": "100000999", "nickname": "synthetic", "signature": "private"},
            "characters": [{
                "id": "1212", "level": 80, "rank": 1,
                "skills": [{"id": "121201", "level": 5}],
                "light_cone": {
                    "id": "23014", "level": 80, "rank": 1,
                    "attributes": [{"field": "atk", "value": 582.1, "percent": False}],
                },
                "relics": [{"id": "61041", "type": 1, "level": 15, "set_id": "104"}],
                "attributes": [{"field": "spd", "value": 134.5}],
            }],
        })
        self.assertEqual(proposal.ownership, {"1212": Ownership.OWNED})
        self.assertIn("character:1212.stat:spd", proposal.fields)
        self.assertNotIn("100000999", json.dumps(proposal.fields, default=str))
        self.assertEqual(proposal.equipment[0].identity, EquipmentIdentity.AMBIGUOUS)
        self.assertFalse(proposal.equipment[0].may_be_reassigned)
        self.assertIn("attribute:0.value", proposal.equipment[0].facts)

    def test_mihomo_preserves_only_named_memory_summary_values_without_mode_mapping(self) -> None:
        proposal = MihomoPublicProfileClient().to_preview({
            "player": {
                "uid": "100000999",
                "memory_data": {
                    "level": 8,
                    "chaos_id": 1234,
                    "chaos_level": 12,
                    "negative": -1,
                    "malformed_bool": True,
                    "unexpected": "ignored",
                },
            },
            "characters": [],
        })

        self.assertEqual(
            {path: item.value for path, item in proposal.fields.items()},
            {
                "progress:mihomo-memory-summary:level": 8,
                "progress:mihomo-memory-summary:chaos_id": 1234,
                "progress:mihomo-memory-summary:chaos_level": 12,
            },
        )
        self.assertEqual(proposal.coverage, frozenset(proposal.fields))
        self.assertTrue(all(item.status is FieldStatus.NEEDS_REVIEW for item in proposal.fields.values()))
        self.assertTrue(all(item.scope.startswith("mihomo-player.memory_data.")
                            for item in proposal.fields.values()))
        self.assertNotIn("100000999", json.dumps(proposal.fields, default=str))
        self.assertTrue(any("未将其换算" in warning for warning in proposal.warnings))

    def test_mihomo_malformed_optional_arrays_are_ignored(self) -> None:
        proposal = MihomoPublicProfileClient().to_preview({
            "characters": [{"id": "fixture", "skills": None, "attributes": "bad"}],
        })
        self.assertEqual(proposal.ownership, {"fixture": Ownership.OWNED})
        self.assertEqual(proposal.fields, {})

    def test_mihomo_rejects_conflicting_duplicate_records_and_fields(self) -> None:
        client = MihomoPublicProfileClient()
        with self.assertRaisesRegex(ProfileRequestError, "duplicate character"):
            client.to_preview({"characters": [
                {"id": "fixture", "level": 80},
                {"id": "fixture", "level": 70},
            ]})
        with self.assertRaisesRegex(ProfileRequestError, "conflicting duplicate fields"):
            client.to_preview({"characters": [{
                "id": "fixture",
                "attributes": [
                    {"field": "spd", "value": 100},
                    {"field": "spd", "value": 120},
                ],
            }]})
        with self.assertRaisesRegex(ProfileRequestError, "conflicting duplicate fields"):
            client.to_preview({"characters": [{
                "id": "fixture",
                "skills": [
                    {"id": "skill", "level": 5},
                    {"id": "skill", "level": 6},
                ],
            }]})

    def test_mihomo_rejects_ambiguous_json_and_filters_invalid_numbers(self) -> None:
        client = MihomoPublicProfileClient()
        for raw in (
            b'{"characters": [], "characters": []}',
            b'{"characters": [{"id": "fixture", "attributes": [{"field": "spd", "value": NaN}]}]}',
            b'{"characters":' + b'[' * 5000 + b']' * 5000 + b'}',
        ):
            with self.assertRaises(ProfileRequestError):
                client._decode_response(raw)
        with self.assertRaisesRegex(ProfileRequestError, "unsupported shape"):
            client._decode_response(b'[]')

        proposal = client.to_preview({"characters": [
            {"id": True, "level": 80},
            {
                "id": "fixture",
                "level": True,
                "rank": float("inf"),
                "attributes": [
                    {"field": "spd", "value": float("nan")},
                    {"field": "atk", "value": True},
                    {"field": "def", "value": 15},
                ],
                "skills": [
                    {"id": True, "level": 10},
                    {"id": "skill", "level": True},
                    {"id": "overflow", "level": 10**1000},
                ],
                "light_cone": {"id": True, "level": 80},
                "relics": [{"id": "relic-type", "level": True, "set_id": False}],
            },
        ]})
        self.assertEqual(proposal.ownership, {"fixture": Ownership.OWNED})
        self.assertEqual(set(proposal.fields), {"character:fixture.stat:def"})
        self.assertEqual(proposal.fields["character:fixture.stat:def"].value, 15)
        self.assertEqual(len(proposal.equipment), 1)
        self.assertEqual(proposal.equipment[0].facts, {})

    def test_mihomo_response_complexity_is_bounded(self) -> None:
        client = MihomoPublicProfileClient()
        with patch("starhelp_desktop.public_profile._MAX_RESPONSE_JSON_NODES", 4):
            with self.assertRaisesRegex(ProfileRequestError, "complexity limits"):
                client._decode_response(b'{"characters":[1,2,3]}')
        with patch("starhelp_desktop.public_profile._MAX_RESPONSE_JSON_DEPTH", 1):
            with self.assertRaisesRegex(ProfileRequestError, "complexity limits"):
                client._decode_response(b'{"outer":{"inner":0}}')
        with patch("starhelp_desktop.public_profile._MAX_RESPONSE_JSON_STRING_LENGTH", 3):
            with self.assertRaisesRegex(ProfileRequestError, "complexity limits"):
                client._decode_response(b'{"characters":[],"ignored":"too long"}')

    def test_mihomo_skips_oversized_public_ids_and_field_names(self) -> None:
        oversized = "x" * 161
        proposal = MihomoPublicProfileClient().to_preview({"characters": [
            {"id": oversized, "level": 80},
            {
                "id": "fixture",
                "attributes": [
                    {"field": oversized, "value": 100},
                    {"field": "speed\ninvalid", "value": 100},
                    {"field": "spd", "value": 100},
                ],
                "light_cone": {"id": oversized, "level": 80},
                "relics": [{"id": "relic-type", "type": {"untrusted": True},
                            "main_affix": {"field": oversized, "value": 20}}],
            },
        ]})
        self.assertEqual(proposal.ownership, {"fixture": Ownership.OWNED})
        self.assertEqual(set(proposal.fields), {"character:fixture.stat:spd"})
        self.assertEqual(proposal.equipment[0].slot, "relic:unknown")
        self.assertEqual(proposal.equipment[0].facts, {})

    def test_public_query_is_allowlisted_and_uid_like_input_is_rejected(self) -> None:
        builder = PublicQueryBuilder()
        request = builder.build(PublicScope("fixture-version", "live", "fixture-mode",
                                            "fixture-cycle", "fixture-stage", "stage_templates"))
        self.assertIn(b'"schema_id":"PublicQuery"', builder.serialize(request))
        with self.assertRaisesRegex(ValueError, "UID-like"):
            builder.build(PublicScope("100000999", "live", "m", "c", "s", "stage_templates"))
        with self.assertRaisesRegex(ValueError, "missing"):
            builder.build(PublicScope("fixture-version", "live", "m", "", "s", "stage_templates"))
        with self.assertRaisesRegex(ValueError, "public goal"):
            builder.build(PublicScope("fixture-version", "live", "m", "c", "s",
                                      "stage_templates", "100000999"))
        request["account_snapshot"] = {"private": True}
        with self.assertRaisesRegex(ValueError, "unapproved field"):
            builder.serialize(request)

    def test_public_query_serializer_revalidates_transport_boundary(self) -> None:
        builder = PublicQueryBuilder()
        request = builder.build(PublicScope(
            "fixture-version", "live", "fixture-mode", "fixture-cycle", "fixture-stage",
            "stage_templates",
        ))

        invalid_requests = (
            ({**request, "query_kind": "account_snapshot"}, "query kind"),
            ({**request, "schema_version": "future"}, "schema"),
            ({key: value for key, value in request.items() if key != "scope"}, "missing"),
            ({**request, "scope": {**request["scope"], "environment": "production"}},
             "environment"),
            ({**request, "scope": {**request["scope"], "stage_id": " stage "}},
             "stage_id"),
            ({**request, "scope": {**request["scope"], "mode_id": "m\nmode"}},
             "mode_id"),
            ({**request, "scope": {**request["scope"], "cycle_id": "x" * 161}},
             "cycle_id"),
            ({**request, "index_release_id": "100000999"}, "release ID"),
            ({**request, "public_goal": {"kind": "100000999"}}, "public goal"),
        )
        for malformed, message in invalid_requests:
            with self.subTest(malformed=malformed):
                with self.assertRaisesRegex(ValueError, message):
                    builder.serialize(malformed)

    def test_ocr_text_requires_explicit_field_mapping_and_confirmation(self) -> None:
        draft = OcrDraft(
            lines=(OcrTextLine("等级 80", 0.93, ((0, 0), (10, 0), (10, 10), (0, 10))),),
            recognized_at=datetime.now(UTC),
            warnings=("synthetic fixture",),
        )
        proposal = proposal_from_ocr_mapping(draft, {"character:fixture.level": 0})
        self.assertEqual(proposal.fields["character:fixture.level"].value, "等级 80")
        self.assertFalse(proposal.confirmed)
        with self.assertRaises(IndexError):
            proposal_from_ocr_mapping(draft, {"character:fixture.level": 4})


class StorageLifecycleTests(unittest.TestCase):
    def test_private_store_rejects_oversized_envelope_before_unprotect(self) -> None:
        with temporary_directory() as directory:
            store = EncryptedPrivateStore(Path(directory) / "private", TestProtector())
            path = store.root / "fixture-object.bin"
            path.write_bytes(b"SHDPAPI1" + b"x" * 64)
            with patch("starhelp_desktop.storage._MAX_PRIVATE_OBJECT_BYTES", 8), patch(
                "starhelp_desktop.storage._MAX_DPAPI_ENVELOPE_OVERHEAD", 0
            ), patch.object(store._protector, "unprotect") as unprotect:
                with self.assertRaisesRegex(ValueError, "encrypted private object"):
                    store.load("fixture-object")
                unprotect.assert_not_called()

    def test_private_store_bounds_plaintext_on_save_and_after_unprotect(self) -> None:
        with temporary_directory() as directory:
            store = EncryptedPrivateStore(Path(directory) / "private", TestProtector())
            with patch("starhelp_desktop.storage._MAX_PRIVATE_OBJECT_BYTES", 8), patch.object(
                store._protector, "protect"
            ) as protect:
                with self.assertRaisesRegex(ValueError, "private object exceeds"):
                    store.save("fixture-large", {"data": "x" * 64})
                protect.assert_not_called()

            path = store.root / "fixture-decrypted-large.bin"
            path.write_bytes(b"SHDPAPI1x")
            with patch("starhelp_desktop.storage._MAX_PRIVATE_OBJECT_BYTES", 8), patch(
                "starhelp_desktop.storage._MAX_DPAPI_ENVELOPE_OVERHEAD", 32
            ), patch.object(store._protector, "unprotect", return_value=b"x" * 9):
                with self.assertRaisesRegex(ValueError, "private object exceeds"):
                    store.load("fixture-decrypted-large")

    @unittest.skipUnless(sys.platform == "win32", "Windows DPAPI integration check")
    def test_windows_dpapi_round_trips_synthetic_private_object(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory) / "dpapi-store"
            value = {"fixture": f"synthetic-only-{uuid4().hex}"}
            store = EncryptedPrivateStore(root, WindowsDpapiProtector())
            encrypted_path = store.save("synthetic-profile", value)
            encrypted_bytes = encrypted_path.read_bytes()

            self.assertTrue(encrypted_bytes.startswith(b"SHDPAPI1"))
            self.assertNotIn(value["fixture"].encode("ascii"), encrypted_bytes)
            restarted_store = EncryptedPrivateStore(root, WindowsDpapiProtector())
            self.assertEqual(restarted_store.load("synthetic-profile"), value)

    def test_encrypted_store_never_writes_plain_json(self) -> None:
        with temporary_directory() as directory:
            store = EncryptedPrivateStore(Path(directory), TestProtector())
            path = store.save("profile-fixture-snapshot", {"display": "sensitive fixture"})
            self.assertNotIn(b"sensitive fixture", path.read_bytes())
            self.assertEqual(store.load("profile-fixture-snapshot")["display"], "sensitive fixture")

    def test_revoke_cancels_tasks_rejects_late_results_and_deletes_private_files(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            store = EncryptedPrivateStore(root / "private", TestProtector())
            profile_id = uuid4()
            lifecycle = ProfileLifecycle(store, root / "temp")
            lifecycle.authorize(ProfileAuthorization(
                profile_id, True, 1, "synthetic-source", frozenset({"display"}),
                datetime.now(UTC),
            ))
            cancel = lifecycle.register_task(profile_id, 1)
            private_file = store.save(f"profile-{profile_id.hex}-snapshot", {"fixture": True})
            temp_file = root / "temp" / profile_id.hex / "scan.tmp"
            temp_file.parent.mkdir(parents=True)
            temp_file.write_bytes(b"synthetic")
            lifecycle.revoke(profile_id)
            self.assertTrue(cancel.is_set())
            self.assertFalse(lifecycle.accepts_result(profile_id, 1))
            self.assertFalse(private_file.exists())
            self.assertFalse(temp_file.exists())
            with self.assertRaises(PermissionError):
                lifecycle.require_active(profile_id, 1)

    def test_finished_task_is_unregistered_without_losing_active_cancellation(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            store = EncryptedPrivateStore(root / "private", TestProtector())
            profile_id = uuid4()
            lifecycle = ProfileLifecycle(store, root / "temp")
            lifecycle.authorize(ProfileAuthorization(
                profile_id, True, 1, "synthetic-source", frozenset({"display"}),
                datetime.now(UTC),
            ))
            finished = lifecycle.register_task(profile_id, 1)
            active = lifecycle.register_task(profile_id, 1)
            lifecycle.unregister_task(profile_id, 1, finished)
            lifecycle.revoke(profile_id)
            self.assertFalse(finished.is_set())
            self.assertTrue(active.is_set())

    def test_revoke_serializes_with_in_flight_explicit_report_save(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            store = EncryptedPrivateStore(root / "private", TestProtector())
            lifecycle = ProfileLifecycle(store, root / "temp")
            profile_id = uuid4()
            lifecycle.authorize(ProfileAuthorization(
                profile_id, True, 1, "synthetic-source", frozenset({"reports"}),
                datetime.now(UTC),
            ))
            reports = ReportLifecycle(store, lifecycle)
            report = reports.make_temporary(
                profile_id=profile_id, generation=1, task={"fixture": "task"},
                result={"fixture": "result"}, snapshot_revision=1,
                public_release_id="fixture-release", planner_version="fixture",
            )
            save_entered = threading.Event()
            allow_save = threading.Event()
            revoke_started = threading.Event()
            revoke_done = threading.Event()
            original_save = store.save

            def slow_save(key: str, value: dict[str, object]):
                save_entered.set()
                if not allow_save.wait(2):
                    raise TimeoutError("synthetic save gate timed out")
                return original_save(key, value)

            store.save = slow_save
            saver = threading.Thread(
                target=reports.save_explicitly,
                args=(report,),
                kwargs={"current_snapshot_revision": 1},
            )

            def revoke() -> None:
                revoke_started.set()
                lifecycle.revoke(profile_id)
                revoke_done.set()

            revoker = threading.Thread(target=revoke)
            saver.start()
            self.assertTrue(save_entered.wait(2))
            revoker.start()
            self.assertTrue(revoke_started.wait(2))
            self.assertFalse(revoke_done.wait(0.05))
            allow_save.set()
            saver.join(2)
            revoker.join(2)
            self.assertFalse(saver.is_alive())
            self.assertFalse(revoker.is_alive())
            report_key = f"profile-{profile_id.hex}-report-{report.report_id.hex}"
            with self.assertRaises(FileNotFoundError):
                store.load(report_key)

    def test_reports_are_temporary_until_explicit_save_and_expire_on_snapshot_change(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            store = EncryptedPrivateStore(root / "private", TestProtector())
            profile_id = uuid4()
            lifecycle = ProfileLifecycle(store, root / "temp")
            lifecycle.authorize(ProfileAuthorization(
                profile_id, True, 1, "synthetic-source", frozenset({"analyze"}),
                datetime.now(UTC),
            ))
            reports = ReportLifecycle(store, lifecycle)
            report = reports.make_temporary(profile_id=profile_id, generation=1, task={"fixture": True},
                                             result={"fixture": "result"}, snapshot_revision=1,
                                             public_release_id="fixture-release", planner_version="fixture",
                                             public_refs=frozenset({"fixture:evidence:1"}))
            self.assertEqual(list((root / "private").glob("*.bin")), [])
            self.assertEqual(reports.mark_stale(report, current_snapshot_revision=2).validity,
                             ReportValidity.EXPIRED)
            saved = reports.save_explicitly(report, current_snapshot_revision=2)
            self.assertTrue(saved.exists())
            saved_after_change = reports.list_saved(
                profile_id=profile_id,
                generation=1,
                current_snapshot_revision=2,
            )
            self.assertEqual(saved_after_change[0].validity, ReportValidity.EXPIRED)
            withdrawn = reports.list_saved(
                profile_id=profile_id,
                generation=1,
                current_snapshot_revision=1,
                withdrawn_refs=frozenset({"fixture:evidence:1"}),
            )
            self.assertEqual(withdrawn[0].validity, ReportValidity.EVIDENCE_WITHDRAWN)
            still_withdrawn = reports.list_saved(
                profile_id=profile_id, generation=1, current_snapshot_revision=2
            )
            self.assertEqual(still_withdrawn[0].validity, ReportValidity.EVIDENCE_WITHDRAWN)
            unavailable_snapshot = reports.list_saved(
                profile_id=profile_id, generation=1, current_snapshot_revision=None
            )
            self.assertEqual(unavailable_snapshot[0].validity, ReportValidity.EVIDENCE_WITHDRAWN)
            bundle_bound = reports.make_temporary(
                profile_id=profile_id, generation=1, task={"fixture": "bundle-bound"},
                result={"fixture": "result"}, snapshot_revision=1,
                public_release_id="fixture-release", planner_version="fixture",
            )
            reports.save_explicitly(
                bundle_bound,
                current_snapshot_revision=1,
                current_public_release_id="fixture-release",
            )
            release_changed = reports.list_saved(
                profile_id=profile_id,
                generation=1,
                current_snapshot_revision=1,
                current_public_release_id="fixture-release-2",
            )
            by_id = {item.report_id: item for item in release_changed}
            self.assertEqual(by_id[bundle_bound.report_id].validity, ReportValidity.NEEDS_REVIEW)
            self.assertIn("公共资料版本已变化", by_id[bundle_bound.report_id].validity_reason)
            snapshot_bound = reports.make_temporary(
                profile_id=profile_id, generation=1, task={"fixture": "second"},
                result={"fixture": "result"}, snapshot_revision=1,
                public_release_id="fixture-release", planner_version="fixture",
            )
            reports.save_explicitly(snapshot_bound, current_snapshot_revision=1)
            unbound_report = reports.make_temporary(
                profile_id=profile_id, generation=1, task={"fixture": "missing-snapshot"},
                result={"fixture": "result"}, snapshot_revision=9,
                public_release_id="fixture-release", planner_version="fixture",
            )
            reports.save_explicitly(unbound_report, current_snapshot_revision=None)
            needs_review = reports.list_saved(
                profile_id=profile_id, generation=1, current_snapshot_revision=None
            )
            by_id = {item.report_id: item for item in needs_review}
            self.assertEqual(by_id[unbound_report.report_id].validity, ReportValidity.NEEDS_REVIEW)
            expired = reports.list_saved(
                profile_id=profile_id, generation=1, current_snapshot_revision=2
            )
            by_id = {item.report_id: item for item in expired}
            self.assertEqual(by_id[snapshot_bound.report_id].validity, ReportValidity.EXPIRED)
            lifecycle.revoke(profile_id)
            with self.assertRaises(PermissionError):
                reports.save_explicitly(snapshot_bound, current_snapshot_revision=1)

    def test_profiles_store_only_confirmed_local_snapshot_and_revoke_survives_restart(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            store = EncryptedPrivateStore(root / "private", TestProtector())
            lifecycle = ProfileLifecycle(store, root / "temp")
            repository = ProfileRepository(store, lifecycle)
            proposal = confirm_import(StructuredImportAdapter().preview_object({
                "schema_id": StructuredImportAdapter.SCHEMA_ID,
                "schema_version": StructuredImportAdapter.SCHEMA_VERSION,
                "observed_at": "2026-10-15T00:00:00Z",
                "fields": {"character:fixture.level": {"value": 80}},
            }).proposal)
            profile = repository.create_from_confirmed_import(
                label="Synthetic profile",
                provider_id="synthetic-source",
                server_label="fixture-region",
                proposal=proposal,
            )
            snapshot = repository.load_snapshot(profile.profile_id, profile.generation)
            self.assertEqual(snapshot.fields["character:fixture.level"].value, 80)
            self.assertFalse(any("100000999" in path.name for path in (root / "private").iterdir()))
            repository.revoke(profile.profile_id)
            self.assertEqual(repository.list_profiles(), ())
            restored = ProfileRepository(store, ProfileLifecycle(store, root / "temp"))
            self.assertEqual(restored.list_profiles(), ())
            with self.assertRaises(FileNotFoundError):
                store.load(f"profile-{profile.profile_id.hex}-snapshot")

    def test_lifecycle_revoke_cannot_be_followed_by_a_late_snapshot_write(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            store = EncryptedPrivateStore(root / "private", TestProtector())
            lifecycle = ProfileLifecycle(store, root / "temp")
            repository = ProfileRepository(store, lifecycle)
            profile = repository.begin_profile(
                label="Synthetic profile", provider_id="local-import", server_label="fixture-region"
            )
            proposal = confirm_import(StructuredImportAdapter().preview_object({
                "schema_id": StructuredImportAdapter.SCHEMA_ID,
                "schema_version": StructuredImportAdapter.SCHEMA_VERSION,
                "observed_at": "2026-10-15T00:00:00Z",
                "fields": {"character:fixture.level": {"value": 80}},
            }).proposal)
            snapshot_key = f"profile-{profile.profile_id.hex}-snapshot"
            save_entered = threading.Event()
            allow_save = threading.Event()
            revoke_started = threading.Event()
            revoke_done = threading.Event()
            original_save = store.save

            def slow_snapshot_save(key: str, value: dict[str, object]) -> Path:
                if key == snapshot_key:
                    save_entered.set()
                    if not allow_save.wait(2):
                        raise TimeoutError("synthetic snapshot-save gate timed out")
                return original_save(key, value)

            store.save = slow_snapshot_save  # type: ignore[method-assign]
            saver = threading.Thread(
                target=repository.save_confirmed_import,
                args=(profile.profile_id, profile.generation, proposal),
            )

            def revoke() -> None:
                revoke_started.set()
                lifecycle.revoke(profile.profile_id)
                revoke_done.set()

            revoker = threading.Thread(target=revoke)
            saver.start()
            self.assertTrue(save_entered.wait(2))
            revoker.start()
            self.assertTrue(revoke_started.wait(2))
            self.assertFalse(revoke_done.wait(0.05))
            allow_save.set()
            saver.join(2)
            revoker.join(2)
            self.assertFalse(saver.is_alive())
            self.assertFalse(revoker.is_alive())
            self.assertFalse((root / "private" / f"{snapshot_key}.bin").exists())
            self.assertFalse(lifecycle.accepts_result(profile.profile_id, profile.generation))

    def test_revoke_tombstone_prevents_catalog_write_failure_from_resurrecting_profile(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            store = EncryptedPrivateStore(root / "private", TestProtector())
            lifecycle = ProfileLifecycle(store, root / "temp")
            repository = ProfileRepository(store, lifecycle)
            profile = repository.begin_profile(
                label="Synthetic profile", provider_id="local-import", server_label="fixture-region"
            )
            store.save(f"profile-{profile.profile_id.hex}-snapshot", {
                "schema_id": "synthetic-private-fixture",
            })
            original_save = store.save

            def fail_catalog_save(key: str, value: dict[str, object]) -> Path:
                if key == ProfileRepository.CATALOG_KEY:
                    raise OSError("synthetic catalog write failure")
                return original_save(key, value)

            store.save = fail_catalog_save  # type: ignore[method-assign]
            with self.assertRaisesRegex(OSError, "synthetic catalog write failure"):
                repository.revoke(profile.profile_id)
            self.assertFalse(lifecycle.is_active(profile.profile_id))
            self.assertEqual(repository.list_profiles(), ())

            store.save = original_save  # type: ignore[method-assign]
            restarted_lifecycle = ProfileLifecycle(store, root / "temp")
            restarted = ProfileRepository(store, restarted_lifecycle)
            self.assertEqual(restarted.list_profiles(), ())
            self.assertFalse(restarted_lifecycle.is_active(profile.profile_id))
            with self.assertRaises(FileNotFoundError):
                store.load(f"profile-{profile.profile_id.hex}-snapshot")
            with self.assertRaises(FileNotFoundError):
                store.load(ProfileRepository.REVOCATIONS_KEY)

    def test_last_task_is_encrypted_restored_after_restart_and_removed_on_revoke(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            store = EncryptedPrivateStore(root / "private", TestProtector())
            lifecycle = ProfileLifecycle(store, root / "temp")
            profiles = ProfileRepository(store, lifecycle)
            profile = profiles.begin_profile(
                label="Synthetic profile", provider_id="local-import", server_label="fixture-region"
            )
            tasks = TaskRepository(store, lifecycle)
            task = AnalysisTaskDraft.create(
                profile_id=profile.profile_id,
                authorization_generation=profile.generation,
                mode_label="fixture-mode",
                cycle_id="fixture-cycle",
                stage_id="fixture-stage",
                goal_label="fixture-goal",
                fixed_character_ids="fixture-character-a",
                excluded_character_ids="fixture-character-b",
                locked_equipment_instance_ids="fixture-local-equipment-a",
            )
            tasks.save_last(task)
            task_path = root / "private" / f"profile-{profile.profile_id.hex}-last-task.bin"
            self.assertNotIn(b"fixture-stage", task_path.read_bytes())

            restarted_lifecycle = ProfileLifecycle(store, root / "temp")
            restarted_profiles = ProfileRepository(store, restarted_lifecycle)
            restarted_tasks = TaskRepository(store, restarted_lifecycle)
            restored = restarted_tasks.load_last(profile.profile_id, profile.generation)
            self.assertEqual(restored, task)

            restarted_profiles.revoke(profile.profile_id)
            self.assertFalse(task_path.exists())
            with self.assertRaises(PermissionError):
                restarted_tasks.load_last(profile.profile_id, profile.generation)

    def test_player_confirmed_equipment_link_persists_in_encrypted_snapshot(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            store = EncryptedPrivateStore(root / "private", TestProtector())
            lifecycle = ProfileLifecycle(store, root / "temp")
            profiles = ProfileRepository(store, lifecycle)
            first = EquipmentInstance(
                uuid4(), "fixture:relic-type:1", "head", EquipmentIdentity.PLAYER_CONFIRMED,
                "fixture:character:1", {},
            )
            duplicate = EquipmentInstance(
                uuid4(), "fixture:relic-type:1", "head", EquipmentIdentity.UNCONFIRMED,
                "fixture:character:1", {},
            )
            proposal = confirm_import(ImportProposal.create(
                source_kind=SourceKind.STRUCTURED_IMPORT,
                source_id="synthetic-duplicate-import",
                observed_at=datetime.now(UTC),
                fields={},
                equipment=(first, duplicate),
                coverage=frozenset({"equipment:displayed"}),
            ))
            profile = profiles.create_from_confirmed_import(
                label="Synthetic equipment profile", provider_id="local-import",
                server_label="fixture-region", proposal=proposal,
            )
            saved = profiles.link_equipment_instances(
                profile.profile_id, profile.generation,
                imported_instance_id=duplicate.local_instance_id,
                existing_instance_id=first.local_instance_id,
                player_confirmed_same_copy=True,
            )
            restored = profiles.load_snapshot(profile.profile_id, profile.generation)
            self.assertEqual(saved, restored)
            self.assertEqual(len(restored.equipment), 1)
            self.assertEqual(restored.equipment[0].local_instance_id, first.local_instance_id)

    def test_auto_refresh_uid_requires_separate_consent_is_encrypted_and_cleared(self) -> None:
        with temporary_directory() as directory:
            root = Path(directory)
            store = EncryptedPrivateStore(root / "private", TestProtector())
            lifecycle = ProfileLifecycle(store, root / "temp")
            repository = ProfileRepository(store, lifecycle)
            profile = repository.begin_profile(
                label="Synthetic public profile",
                provider_id=MihomoPublicProfileClient.PROVIDER_ID,
                server_label="fixture-region",
            )
            with self.assertRaises(PermissionError):
                repository.set_auto_refresh(
                    profile.profile_id, True, separately_confirmed=False, uid="100000999"
                )
            repository.set_auto_refresh(
                profile.profile_id, True, separately_confirmed=True, uid="100000999"
            )
            config_path = root / "private" / f"profile-{profile.profile_id.hex}-refresh.bin"
            self.assertNotIn(b"100000999", config_path.read_bytes())

            restarted = ProfileRepository(store, ProfileLifecycle(store, root / "temp"))
            config = restarted.auto_refresh_config(profile.profile_id, profile.generation)
            self.assertEqual(config["uid"], "100000999")
            attempted = datetime(2026, 10, 16, tzinfo=UTC)
            restarted.record_auto_refresh_attempt(profile.profile_id, profile.generation, attempted)
            self.assertEqual(
                restarted.auto_refresh_config(profile.profile_id, profile.generation)["last_attempt_at"],
                attempted.isoformat(),
            )

            restarted.set_auto_refresh(profile.profile_id, False, separately_confirmed=False)
            self.assertFalse(config_path.exists())
            self.assertIsNone(restarted.auto_refresh_config(profile.profile_id, profile.generation))
            restarted.set_auto_refresh(
                profile.profile_id, True, separately_confirmed=True, uid="100000999"
            )
            restarted.revoke(profile.profile_id)
            self.assertFalse(config_path.exists())

    def test_task_rejects_conflicting_or_malformed_constraints(self) -> None:
        base = {
            "profile_id": uuid4(),
            "authorization_generation": 1,
            "mode_label": "fixture-mode",
            "cycle_id": "fixture-cycle",
            "stage_id": "fixture-stage",
            "goal_label": "fixture-goal",
        }
        with self.assertRaisesRegex(ValueError, "both fixed and excluded"):
            AnalysisTaskDraft.create(**base, fixed_character_ids="fixture-a",
                                     excluded_character_ids="fixture-a")
        with self.assertRaisesRegex(ValueError, "empty identifier"):
            AnalysisTaskDraft.create(**base, locked_equipment_instance_ids="fixture-a,")
        with self.assertRaisesRegex(ValueError, "duplicate identifier"):
            AnalysisTaskDraft.create(**base, fixed_character_ids="fixture-a,fixture-a")


class BundleTests(unittest.TestCase):
    def test_cached_release_read_is_bounded_before_json_parsing(self) -> None:
        with temporary_directory() as directory:
            cache = PublicBundleCache(Path(directory) / "cache")
            cached_file = cache.root / cache._filename("fixture-release-bounded")
            cached_file.write_bytes(b"x" * 9)
            with patch.object(BundleValidator, "MAX_BUNDLE_BYTES", 8):
                with self.assertRaisesRegex(BundleRejected, "configured size limit"):
                    cache.read_release("fixture-release-bounded")

    def test_rejects_oversized_deep_and_excessively_large_bundle_objects(self) -> None:
        validator = BundleValidator()
        validator.MAX_BUNDLE_BYTES = 8
        with self.assertRaisesRegex(BundleRejected, "64 MiB size limit"):
            validator.validate(b" " * 9, supported_capabilities=frozenset())
        with self.assertRaisesRegex(BundleRejected, "64 MiB"):
            validator.validate({"payload": "x" * 32}, supported_capabilities=frozenset())

        validator.MAX_BUNDLE_BYTES = 64 * 1024 * 1024
        validator.MAX_JSON_DEPTH = 4
        nested: object = "fixture"
        for _ in range(5):
            nested = {"nested": nested}
        with self.assertRaisesRegex(BundleRejected, "nesting limit"):
            validator.validate({"payload": nested}, supported_capabilities=frozenset())

        validator.MAX_JSON_DEPTH = 64
        validator.MAX_JSON_NODES = 3
        with self.assertRaisesRegex(BundleRejected, "node limit"):
            validator.validate({"payload": [1, 2, 3]}, supported_capabilities=frozenset())

        validator.MAX_JSON_NODES = 500_000
        cyclic: dict[str, object] = {}
        cyclic["self"] = cyclic
        with self.assertRaisesRegex(BundleRejected, "circular"):
            validator.validate(cyclic, supported_capabilities=frozenset())
        with self.assertRaisesRegex(BundleRejected, "non-finite"):
            validator.validate({"value": float("nan")}, supported_capabilities=frozenset())
        with self.assertRaisesRegex(BundleRejected, "256-bit"):
            validator.validate({"value": 1 << 256}, supported_capabilities=frozenset())

    def test_validates_hash_and_dependencies_before_activation(self) -> None:
        validator = BundleValidator()
        object_a = {"kind": "entity", "refs": []}
        object_b = {"kind": "template", "refs": ["entity:1"]}
        objects = {"entity:1": object_a, "template:1": object_b}
        canonical = lambda obj: json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":")).encode("utf-8")
        fixture_key = b"synthetic-only-fixture-signing-key"

        class FixtureVerifier:
            def verify(self, key_id: str, signed_bytes: bytes, signature: bytes) -> bool:
                return key_id == "synthetic" and hmac.compare_digest(
                    hmac.digest(fixture_key, signed_bytes, "sha256"), signature
                )

        manifest = {
            "index_release_id": "fixture-release-1",
            "required_capabilities": [],
            "signing_key_id": "synthetic",
            "members": {key: hashlib.sha256(canonical(obj)).hexdigest()
                        for key, obj in objects.items()},
            "coverage": {"status": "synthetic"},
        }
        envelope = {
            "contract_version": "0.1-draft",
            "schema_id": "PublicBundle",
            "schema_version": "0.1-draft",
            "manifest": manifest,
            "signature": hmac.digest(fixture_key, canonical(manifest), "sha256").hex(),
            "objects": objects,
        }
        verifier = FixtureVerifier()
        with self.assertRaisesRegex(BundleRejected, "signature verification is unavailable"):
            validator.validate(envelope, supported_capabilities=frozenset())
        bundle = validator.validate(envelope, supported_capabilities=frozenset(),
                                    signature_verifier=verifier)
        with temporary_directory() as directory:
            cache = PublicBundleCache(Path(directory))
            cache.activate(bundle)
            self.assertEqual(cache.current_release_id(), "fixture-release-1")
            self.assertEqual(cache.available_release_ids(), ("fixture-release-1",))
        bad = json.loads(json.dumps(envelope))
        bad["objects"]["entity:1"]["name"] = "mutated"
        with self.assertRaises(BundleRejected):
            validator.validate(bad, supported_capabilities=frozenset(), signature_verifier=verifier)
        dangling = json.loads(json.dumps(envelope))
        dangling["objects"]["template:1"]["refs"] = ["missing"]
        for key in dangling["manifest"]["members"]:
            canonical_object = canonical(dangling["objects"][key])
            dangling["manifest"]["members"][key] = hashlib.sha256(canonical_object).hexdigest()
        dangling["signature"] = hmac.digest(
            fixture_key, canonical(dangling["manifest"]), "sha256"
        ).hex()
        with self.assertRaisesRegex(BundleRejected, "missing dependencies"):
            validator.validate(dangling, supported_capabilities=frozenset(),
                               signature_verifier=verifier)

    def test_sync_keeps_previous_release_until_verified_candidate_activates(self) -> None:
        fixture_key = b"synthetic-sync-signing-key"
        canonical = lambda obj: json.dumps(obj, ensure_ascii=False, sort_keys=True,
                                           separators=(",", ":")).encode("utf-8")

        class FixtureVerifier:
            def verify(self, key_id: str, signed_bytes: bytes, signature: bytes) -> bool:
                return key_id == "sync-key" and hmac.compare_digest(
                    hmac.digest(fixture_key, signed_bytes, "sha256"), signature
                )

        def make_release(release_id: str) -> dict[str, object]:
            objects = {"fixture:object": {"kind": "fixture", "refs": []}}
            manifest = {
                "index_release_id": release_id,
                "required_capabilities": [],
                "signing_key_id": "sync-key",
                "members": {"fixture:object": hashlib.sha256(
                    canonical(objects["fixture:object"])
                ).hexdigest()},
                "coverage": {"fixture": True},
            }
            return {
                "contract_version": "0.1-draft",
                "schema_id": "PublicBundle",
                "schema_version": "0.1-draft",
                "manifest": manifest,
                "signature": hmac.digest(fixture_key, canonical(manifest), "sha256").hex(),
                "objects": objects,
            }

        class FixtureSource:
            def __init__(self, envelope: dict[str, object], release_id: str) -> None:
                self.envelope = envelope
                self.release_id = release_id
                self.fetches = 0

            def discover_release(self, current_release_id: str | None) -> str | None:
                return self.release_id

            def fetch_release(self, release_id: str) -> object:
                self.fetches += 1
                if release_id != self.release_id:
                    raise AssertionError("unexpected release request")
                return self.envelope

        with temporary_directory() as directory:
            cache = PublicBundleCache(Path(directory))
            sync = PublicBundleSynchronizer(
                cache, signature_verifier=FixtureVerifier(), supported_capabilities=frozenset()
            )
            first = sync.sync(FixtureSource(make_release("fixture-release-1"), "fixture-release-1"))
            self.assertTrue(first.updated)
            second = sync.sync(FixtureSource(make_release("fixture-release-2"), "fixture-release-2"))
            self.assertEqual(second.previous_release_id, "fixture-release-1")
            self.assertEqual(cache.available_release_ids(),
                             ("fixture-release-1", "fixture-release-2"))
            self.assertEqual(sync.load_current().release_id, "fixture-release-2")
            verification_receipt = cache.inspect_cached_metadata("fixture-release-2")[
                "verification_receipt"
            ]
            self.assertEqual(verification_receipt["status"], "content-matched-local-record")
            self.assertIsNotNone(verification_receipt["verified_at"])
            self.assertEqual(sync.load_release("fixture-release-1").release_id, "fixture-release-1")

            current_path = cache.root / cache._filename("fixture-release-2")
            original_bytes = current_path.read_bytes()
            tampered = json.loads(original_bytes.decode("utf-8"))
            tampered["objects"]["fixture:object"]["tampered"] = True
            current_path.write_text(json.dumps(tampered), encoding="utf-8")
            with self.assertRaisesRegex(BundleRejected, "member hash mismatch"):
                sync.load_current()
            current_path.write_bytes(original_bytes)
            self.assertEqual(sync.load_current().release_id, "fixture-release-2")

            current_source = FixtureSource(make_release("fixture-release-2"), "fixture-release-2")
            current = sync.sync(current_source)
            self.assertFalse(current.updated)
            self.assertEqual(current_source.fetches, 0)

            unsigned = make_release("fixture-release-3")
            unsigned["signature"] = "00" * 64
            with self.assertRaisesRegex(BundleRejected, "signature verification failed"):
                sync.sync(FixtureSource(unsigned, "fixture-release-3"))
            self.assertEqual(cache.current_release_id(), "fixture-release-2")
            self.assertEqual(cache.available_release_ids(),
                             ("fixture-release-1", "fixture-release-2"))


class LocalPlannerProcessTests(unittest.TestCase):
    @staticmethod
    def request(profile_id: object, generation: int) -> dict[str, object]:
        return {
            "contract_version": "0.1-draft",
            "schema_id": "AnalysisRequest",
            "schema_version": "0.1-draft",
            "request_id": "fixture:request:1",
            "authorization_generation": generation,
            "account_snapshot": {
                "profile_id": str(profile_id),
                "authorization_generation": generation,
                "authorization_state": "active",
                "snapshot_revision": 7,
            },
            "public_bundle": {"manifest": {"index_release_id": "fixture:release:1"}},
            "task": {"public_goal": {"kind": "fixture:goal:clear"}},
        }

    def _run(self, script: str, *, required: frozenset[str] = frozenset(), timeout: float = 3.0,
             max_response: int = 1024 * 1024) -> object:
        with temporary_directory() as temporary:
            root = Path(temporary)
            profile_id = uuid4()
            store = EncryptedPrivateStore(root / "private", TestProtector())
            lifecycle = ProfileLifecycle(store, root / "temp")
            lifecycle.authorize(ProfileAuthorization(
                profile_id, True, 1, "synthetic-source", frozenset({"analysis"}), datetime.now(UTC)
            ))
            adapter = LocalPlannerProcess(
                (sys.executable, "-c", script), required_capabilities=required,
                timeout_seconds=timeout, max_response_bytes=max_response,
            )
            return adapter.analyze(
                request=self.request(profile_id, 1), profile_id=profile_id,
                authorization_generation=1, lifecycle=lifecycle,
            )

    def test_local_process_receives_complete_request_and_returns_compatible_result(self) -> None:
        script = (
            "import json,sys; request=json.loads(sys.stdin.readline()); "
            "print(json.dumps({'protocol':'starhelp-local-planner','protocol_version':'0.1-draft',"
            "'planner_version':'fixture:planner:1','capabilities':['fixture:analyze:v1'],"
            "'result':{'status':'coverage_insufficient','request_id':request['request_id'],"
            "'snapshot_revision':request['account_snapshot']['snapshot_revision'],"
            "'authorization_generation':request['account_snapshot']['authorization_generation']}}))"
        )
        result = self._run(script, required=frozenset({"fixture:analyze:v1"}))
        self.assertEqual(result.planner_version, "fixture:planner:1")
        self.assertEqual(result.result["status"], "coverage_insufficient")

    def test_zero_snapshot_revision_is_rejected_before_spawning_worker(self) -> None:
        profile_id = uuid4()
        request = self.request(profile_id, 1)
        request["account_snapshot"]["snapshot_revision"] = 0
        with self.assertRaisesRegex(ValueError, "snapshot revision must be a positive integer"):
            _validate_request_envelope(request, profile_id, 1)

    def test_incompatible_or_oversized_results_are_rejected(self) -> None:
        incompatible = (
            "import json; print(json.dumps({'protocol':'starhelp-local-planner',"
            "'protocol_version':'0.1-draft','planner_version':'fixture:planner:1',"
            "'capabilities':[],'result':{'status':'coverage_insufficient'}}))"
        )
        with self.assertRaisesRegex(PlannerUnavailable, "lacks required capabilities"):
            self._run(incompatible, required=frozenset({"fixture:required:v1"}))
        with self.assertRaisesRegex(PlannerUnavailable, "size limit"):
            self._run("print('x' * 4096)", max_response=128)

    def test_timeout_terminates_planner_process(self) -> None:
        with self.assertRaisesRegex(PlannerUnavailable, "timed out"):
            self._run("import time; time.sleep(5)", timeout=0.15)

    def test_revoke_cancels_subprocess_and_rejects_result(self) -> None:
        with temporary_directory() as temporary:
            root = Path(temporary)
            profile_id = uuid4()
            store = EncryptedPrivateStore(root / "private", TestProtector())
            lifecycle = ProfileLifecycle(store, root / "temp")
            lifecycle.authorize(ProfileAuthorization(
                profile_id, True, 1, "synthetic-source", frozenset({"analysis"}), datetime.now(UTC)
            ))
            adapter = LocalPlannerProcess(
                (sys.executable, "-c", "import time; time.sleep(5)"),
                required_capabilities=frozenset(), timeout_seconds=10,
            )
            outcome: list[BaseException] = []

            def analyze() -> None:
                try:
                    adapter.analyze(
                        request=self.request(profile_id, 1), profile_id=profile_id,
                        authorization_generation=1, lifecycle=lifecycle,
                    )
                except BaseException as exc:
                    outcome.append(exc)

            worker = threading.Thread(target=analyze)
            worker.start()
            threading.Event().wait(0.2)
            lifecycle.revoke(profile_id)
            worker.join(2)
            self.assertFalse(worker.is_alive())
            self.assertEqual(len(outcome), 1)
            self.assertIsInstance(outcome[0], PlannerCancelled)


if __name__ == "__main__":
    unittest.main()
