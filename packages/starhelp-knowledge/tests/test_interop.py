from __future__ import annotations

import copy
import hashlib
import importlib
import io
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile
import types
import unittest

from starhelp_knowledge.distribution import (
    DISTRIBUTION_CAPABILITY,
    PLANNER_CAPABILITY,
    canonical_bytes,
    planner_member_hash,
    verify_distribution_envelope,
)
from starhelp_knowledge.errors import IntegrityFailure, MissingDependency, PermissionDenied, UnsupportedCapability, WithdrawnEvidence
from starhelp_knowledge.fixture import FIXTURE_KEY_ID, _FIXTURE_SEED, _fixture_service, build_fixture_artifacts
from starhelp_knowledge.policy import Principal

A_ROOT = Path(__file__).resolve().parents[3]
B_ROOT = A_ROOT.parent / "desktop-account"
C_ROOT = A_ROOT.parent / "local-planner"
B_COMMIT = "045965bce4fbc38a3baa79b594535c9dd983d776"
C_COMMIT = "3133eda8ce571e4a58d217e52e28d6e3d3aa6bff"
B_BUNDLE_FILE = "packages/starhelp-desktop/src/starhelp_desktop/bundles.py"


def _git_text(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True, text=True).stdout


def _load_b_bundle_validator() -> types.ModuleType:
    source = _git_text(B_ROOT, "show", f"{B_COMMIT}:{B_BUNDLE_FILE}")
    module = types.ModuleType("starhelp_pinned_bundles_045965b")
    module.__file__ = f"{B_COMMIT}:{B_BUNDLE_FILE}"
    sys.modules[module.__name__] = module
    exec(compile(source, module.__file__, "exec"), module.__dict__)
    return module


def _extract_pinned_package(
    root: Path,
    commit: str,
    archive_prefix: str,
    package_parent: str,
    temp_root: Path,
) -> Path:
    data = subprocess.run(
        ["git", "archive", "--format=tar", commit, archive_prefix],
        cwd=root,
        check=True,
        capture_output=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(data), mode="r:") as archive:
        prefix = archive_prefix.rstrip("/")
        destination = temp_root / package_parent
        for member in archive.getmembers():
            name = member.name.rstrip("/")
            if member.isdir() and (prefix.startswith(name + "/") or name == prefix):
                continue
            if not name.startswith(prefix + "/") or not member.isfile():
                raise AssertionError("pinned source archive contains an unexpected member")
            relative = Path(name[len(prefix) + 1 :])
            if relative.is_absolute() or ".." in relative.parts:
                raise AssertionError("pinned source archive path escapes its package")
            stream = archive.extractfile(member)
            if stream is None:
                raise AssertionError("pinned source archive member is unreadable")
            target = destination / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(stream.read())
    return temp_root / Path(package_parent).parent


def _resign(envelope: dict[str, object]) -> None:
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    manifest = envelope["manifest"]
    objects = envelope["objects"]
    planner = objects[f"planner-view:{manifest['index_release_id']}"]["bundle"]
    manifest["planner_manifest_hash"] = hashlib.sha256(canonical_bytes(planner["manifest"])).hexdigest()
    manifest["members"] = {
        object_id: hashlib.sha256(canonical_bytes(value)).hexdigest()
        for object_id, value in objects.items()
    }
    private_key = Ed25519PrivateKey.from_private_bytes(_FIXTURE_SEED)
    envelope["signature"] = private_key.sign(canonical_bytes(manifest)).hex()


def _planner_request(view: dict[str, object], serialized_b_snapshot: dict[str, object], *, goal: dict[str, object], fixed: list[str]) -> dict[str, object]:
    if serialized_b_snapshot["fields"] or serialized_b_snapshot["equipment"]:
        raise AssertionError("synthetic B serializer input intentionally has no unmappable fields or equipment")
    ownership = serialized_b_snapshot["ownership"]
    snapshot = {
        "schema_id": "AccountSnapshot",
        "schema_version": "0.1-draft",
        "profile_id": serialized_b_snapshot["profile_id"],
        "snapshot_id": serialized_b_snapshot["snapshot_id"],
        "snapshot_revision": serialized_b_snapshot["revision"],
        # This authorization generation is synthetic harness metadata; B's snapshot serializer does not serialize it.
        "authorization_generation": 7,
        "authorization_state": "active",
        # B emits path coverage, not completeness categories, so the adapter preserves paths and marks completeness unknown.
        "coverage": {"roster": "unknown", "inventory": "unknown", "materials": "unknown"},
        "source_coverage_paths": serialized_b_snapshot["coverage"],
        "characters": [
            {"entity_id": entity_id, "ownership": state, "fields": {}}
            for entity_id, state in sorted(ownership.items())
        ],
        "equipment_instances": [],
        "materials": [],
    }
    stage = view["stages"][0]
    return {
        "adapter_profile": "starhelp.local.v0.2",
        "contract_version": "0.1-draft",
        "schema_id": "AnalysisRequest",
        "schema_version": "0.1-draft",
        "request_id": "fixture:request:interop",
        "authorization_generation": 7,
        "public_bundle": view,
        "account_snapshot": snapshot,
        "evaluation_time": "2026-10-16T01:00:00Z",
        "task": {
            "scope": stage["scope"],
            "public_goal": goal,
            "fixed_character_ids": fixed,
            "excluded_character_ids": [],
            "locked_local_instance_ids": [],
            "allow_rearrangement": False,
        },
        "latest_known_validity": {
            "withdrawn_public_refs": [],
            "checked_at": "2026-10-16T00:00:00Z",
            "online_confirmation_available": False,
        },
        "feedback": None,
    }


class InteropTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tempdir = tempfile.TemporaryDirectory(dir=Path(__file__).parent)
        self.artifacts = Path(self.tempdir.name) / "artifacts"
        self.artifacts.mkdir()
        self.created = build_fixture_artifacts(self.artifacts, b_root=B_ROOT)
        self.envelope = json.loads(Path(self.created["artifact"]).read_text(encoding="utf-8"))
        self.public_key_pem = Path(self.created["public_key"]).read_bytes()
        from cryptography.hazmat.primitives import serialization

        self.public_key = serialization.load_pem_public_key(self.public_key_pem).public_bytes_raw()

    def tearDown(self) -> None:
        self.tempdir.cleanup()

    def _verify_with_b(self, envelope: dict[str, object] | None = None) -> object:
        module = _load_b_bundle_validator()
        try:
            keyring = module.Ed25519Keyring({FIXTURE_KEY_ID: self.public_key})
            return module.BundleValidator().validate(
                self.envelope if envelope is None else envelope,
                supported_capabilities=frozenset({DISTRIBUTION_CAPABILITY}),
                expected_release_id=self.created["release_id"],
                signature_verifier=keyring,
            )
        finally:
            sys.modules.pop(module.__name__, None)

    def _assert_b_rejects(self, envelope: dict[str, object]) -> None:
        module = _load_b_bundle_validator()
        try:
            keyring = module.Ed25519Keyring({FIXTURE_KEY_ID: self.public_key})
            with self.assertRaises(module.BundleRejected):
                module.BundleValidator().validate(
                    envelope,
                    supported_capabilities=frozenset({DISTRIBUTION_CAPABILITY}),
                    expected_release_id=self.created["release_id"],
                    signature_verifier=keyring,
                )
        finally:
            sys.modules.pop(module.__name__, None)

    def test_pinned_b_verifier_and_c_planner_accept_a_generated_three_mode_fixture(self) -> None:
        b_validated = self._verify_with_b()
        self.assertEqual(b_validated.release_id, self.created["release_id"])
        self.assertEqual(b_validated.schema_version, "0.1-draft")
        a_verified = verify_distribution_envelope(
            self.envelope,
            trusted_public_keys={FIXTURE_KEY_ID: self.public_key},
            trusted_key_id=FIXTURE_KEY_ID,
            supported_distribution_capabilities={DISTRIBUTION_CAPABILITY},
            supported_planner_capabilities={PLANNER_CAPABILITY},
        )
        self.assertEqual(a_verified["release_id"], self.created["release_id"])
        planner_view = self.envelope["objects"][f"planner-view:{self.created['release_id']}"]["bundle"]
        native_bundle = self.envelope["objects"][f"native-release:{self.created['release_id']}"]["bundle"]
        self.assertEqual(
            planner_view["entities"][0]["scope"],
            native_bundle["records"]["entity"][0]["scope"],
        )
        self.assertEqual(
            planner_view["evidence"][0]["scope"],
            native_bundle["evidence"][0]["scope"],
        )

        c_source = _extract_pinned_package(
            C_ROOT,
            C_COMMIT,
            "packages/starhelp-planner/src/starhelp_planner",
            "packages/starhelp-planner/src/starhelp_planner",
            Path(self.tempdir.name),
        )
        sys.dont_write_bytecode = True
        sys.path.insert(0, str(c_source))
        modules_before = {name for name in sys.modules if name == "starhelp_planner" or name.startswith("starhelp_planner.")}
        for name in modules_before:
            del sys.modules[name]
        try:
            planner = importlib.import_module("starhelp_planner")
            b_snapshot = json.loads(Path(self.created["b_snapshot"]).read_text(encoding="utf-8"))
            normal = planner.analyze(_planner_request(planner_view, b_snapshot, goal={"kind": "fixture:goal:clear"}, fixed=[]))
            self.assertEqual(normal["status"], "plans_available")
            self.assertTrue(any(plan["variant"]["id"] == "fixture:variant:main" for plan in normal["current_equipment_plans"]))

            alternate = planner.analyze(
                _planner_request(
                    planner_view,
                    b_snapshot,
                    goal={"kind": "fixture:goal:clear"},
                    fixed=["fixture:character:c"],
                )
            )
            self.assertEqual(alternate["status"], "plans_available")
            self.assertTrue(any(plan["variant"]["id"] == "fixture:variant:alternate" for plan in alternate["current_equipment_plans"]))
            self.assertFalse(any(plan["variant"]["id"] == "fixture:variant:main" for plan in alternate["current_equipment_plans"]))

            no_match = planner.analyze(
                _planner_request(
                    planner_view,
                    b_snapshot,
                    goal={"kind": "fixture:goal:no-match"},
                    fixed=[],
                )
            )
            self.assertEqual(no_match["status"], "no_reviewed_template")
            self.assertEqual(no_match["current_equipment_plans"], [])
        finally:
            for name in [name for name in sys.modules if name == "starhelp_planner" or name.startswith("starhelp_planner.")]:
                del sys.modules[name]
            sys.path.remove(str(c_source))

    def test_reproducible_signed_distribution_and_b_snapshot_hashes(self) -> None:
        second_dir = Path(self.tempdir.name) / "rebuild"
        second_dir.mkdir()
        second = build_fixture_artifacts(second_dir, b_root=B_ROOT)
        for first_key, second_key in (("artifact", "artifact"), ("public_key", "public_key"), ("b_snapshot", "b_snapshot")):
            self.assertEqual(Path(self.created[first_key]).read_bytes(), Path(second[second_key]).read_bytes())
        self.assertEqual(self.created["bundle_sha256"], second["bundle_sha256"])
        self.assertEqual(self.created["b_snapshot_sha256"], second["b_snapshot_sha256"])

    def test_tamper_missing_dependencies_and_cross_release_are_rejected(self) -> None:
        tampered = copy.deepcopy(self.envelope)
        release_id = self.created["release_id"]
        tampered["objects"][f"planner-view:{release_id}"]["bundle"]["templates"][0]["title"] = "tampered"
        self._assert_b_rejects(tampered)

        missing = copy.deepcopy(self.envelope)
        planner_view = missing["objects"][f"planner-view:{release_id}"]["bundle"]
        template_member = next(member for member in planner_view["manifest"]["members"] if member["kind"] == "template")
        template_member["dependencies"] = [
            dep for dep in template_member["dependencies"] if dep["kind"] != "stage"
        ]
        _resign(missing)
        with self.assertRaises(MissingDependency):
            verify_distribution_envelope(
                missing,
                trusted_public_keys={FIXTURE_KEY_ID: self.public_key},
                trusted_key_id=FIXTURE_KEY_ID,
                supported_distribution_capabilities={DISTRIBUTION_CAPABILITY},
                supported_planner_capabilities={PLANNER_CAPABILITY},
            )

        cross_release = copy.deepcopy(self.envelope)
        planner_view = cross_release["objects"][f"planner-view:{release_id}"]["bundle"]
        planner_view["variants"][0]["index_release_id"] = "fixture:other-release"
        variant_member = next(member for member in planner_view["manifest"]["members"] if member["kind"] == "variant")
        variant = planner_view["variants"][0]
        variant_member["content_hash"] = planner_member_hash(variant)
        _resign(cross_release)
        with self.assertRaises(IntegrityFailure):
            verify_distribution_envelope(
                cross_release,
                trusted_public_keys={FIXTURE_KEY_ID: self.public_key},
                trusted_key_id=FIXTURE_KEY_ID,
                supported_distribution_capabilities={DISTRIBUTION_CAPABILITY},
                supported_planner_capabilities={PLANNER_CAPABILITY},
            )

    def test_unknown_capabilities_and_signing_identity_fail_closed(self) -> None:
        unknown_outer = copy.deepcopy(self.envelope)
        unknown_outer["manifest"]["required_capabilities"].append("starhelp.unknown.v9")
        _resign(unknown_outer)
        with self.assertRaises(UnsupportedCapability):
            verify_distribution_envelope(
                unknown_outer,
                trusted_public_keys={FIXTURE_KEY_ID: self.public_key},
                trusted_key_id=FIXTURE_KEY_ID,
                supported_distribution_capabilities={DISTRIBUTION_CAPABILITY},
                supported_planner_capabilities={PLANNER_CAPABILITY},
            )
        self._assert_b_rejects(unknown_outer)

        unknown_inner = copy.deepcopy(self.envelope)
        view = unknown_inner["objects"][f"planner-view:{self.created['release_id']}"]["bundle"]
        view["manifest"]["required_capabilities"].append("starhelp.unknown.planner.v9")
        _resign(unknown_inner)
        with self.assertRaises(UnsupportedCapability):
            verify_distribution_envelope(
                unknown_inner,
                trusted_public_keys={FIXTURE_KEY_ID: self.public_key},
                trusted_key_id=FIXTURE_KEY_ID,
                supported_distribution_capabilities={DISTRIBUTION_CAPABILITY},
                supported_planner_capabilities={PLANNER_CAPABILITY},
            )
        with self.assertRaises(IntegrityFailure):
            verify_distribution_envelope(
                self.envelope,
                trusted_public_keys={FIXTURE_KEY_ID: self.public_key},
                trusted_key_id="untrusted-production-key",
                supported_distribution_capabilities={DISTRIBUTION_CAPABILITY},
                supported_planner_capabilities={PLANNER_CAPABILITY},
            )

    def test_planner_schemas_and_profile_capabilities_are_mandatory(self) -> None:
        release_id = self.created["release_id"]
        mutations = (
            lambda envelope: envelope["manifest"].update(required_capabilities=[]),
            lambda envelope: envelope["objects"][f"planner-view:{release_id}"]["bundle"]["manifest"].update(
                object_schemas={}
            ),
            lambda envelope: envelope["objects"][f"planner-view:{release_id}"]["bundle"]["manifest"].update(
                required_capabilities=[]
            ),
        )
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                invalid = copy.deepcopy(self.envelope)
                mutate(invalid)
                _resign(invalid)
                with self.assertRaises(UnsupportedCapability):
                    verify_distribution_envelope(
                        invalid,
                        trusted_public_keys={FIXTURE_KEY_ID: self.public_key},
                        trusted_key_id=FIXTURE_KEY_ID,
                        supported_distribution_capabilities={DISTRIBUTION_CAPABILITY},
                        supported_planner_capabilities={PLANNER_CAPABILITY},
                    )

    def test_revocation_blocks_distribution_export(self) -> None:
        service, release_id = _fixture_service(Path(self.tempdir.name) / "withdraw.sqlite3")
        maintainer = Principal("fixture:maintainer", frozenset({"admin"}))
        service.disable_record(
            maintainer,
            kind="variant",
            record_id="fixture:variant:main",
            revision=1,
            reason="synthetic revocation test",
        )
        from starhelp_knowledge.distribution import export_distribution_from_service
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        with self.assertRaises(WithdrawnEvidence):
            export_distribution_from_service(
                service,
                release_id,
                producer_version="0.2.0",
                producer_commit="fixture-test",
                signing_private_key=Ed25519PrivateKey.from_private_bytes(_FIXTURE_SEED),
                signing_key_id=FIXTURE_KEY_ID,
            )

    def test_missing_planner_semantics_are_not_inferred_during_export(self) -> None:
        from starhelp_knowledge.distribution import export_distribution_from_service
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

        cases = (
            {"omit_stage_resource_reuse": True},
            {"omit_template_public_goals": True},
            {"invalid_condition_value_type": True},
            {"condition_outside_variant_roster": True},
        )
        for index, options in enumerate(cases):
            with self.subTest(options=options):
                service, release_id = _fixture_service(
                    Path(self.tempdir.name) / f"missing-{index}.sqlite3",
                    **options,
                )
                with self.assertRaises(UnsupportedCapability):
                    export_distribution_from_service(
                        service,
                        release_id,
                        producer_version="0.2.0",
                        producer_commit="fixture-test",
                        signing_private_key=Ed25519PrivateKey.from_private_bytes(_FIXTURE_SEED),
                        signing_key_id=FIXTURE_KEY_ID,
                    )


if __name__ == "__main__":
    unittest.main()
