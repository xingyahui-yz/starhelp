from __future__ import annotations

import hashlib
import hmac
import json
import sys
import threading
import tempfile
import unittest
import urllib.request
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from starhelp_desktop.bundles import (
    BundleRejected,
    BundleValidator,
    PublicBundleCache,
    PublicBundleSynchronizer,
)
from starhelp_desktop.equipment import EquipmentIdentityService, EquipmentMergeConflictError
from starhelp_desktop.imports import (
    OcrDraft,
    OcrTextLine,
    StructuredImportAdapter,
    confirm_import,
    proposal_from_ocr_mapping,
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
from starhelp_desktop.planner import LocalPlannerProcess, PlannerCancelled, PlannerUnavailable
from starhelp_desktop.public_profile import (
    MihomoPublicProfileClient,
    ProfileRequestError,
    PublicProfileSelection,
    _RejectRedirects,
)
from starhelp_desktop.profiles import ProfileRepository
from starhelp_desktop.reports import ReportLifecycle, ReportValidity
from starhelp_desktop.storage import EncryptedPrivateStore
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


class ImportAndPrivacyTests(unittest.TestCase):
    def test_public_uid_redirects_are_rejected(self) -> None:
        handler = _RejectRedirects()
        request = urllib.request.Request(
            "https://api.mihomo.me/sr_info_parsed/100000999?lang=cn&version=v2"
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

    def test_mihomo_malformed_optional_arrays_are_ignored(self) -> None:
        proposal = MihomoPublicProfileClient().to_preview({
            "characters": [{"id": "fixture", "skills": None, "attributes": "bad"}],
        })
        self.assertEqual(proposal.ownership, {"fixture": Ownership.OWNED})
        self.assertEqual(proposal.fields, {})

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
