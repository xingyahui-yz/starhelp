from __future__ import annotations

import hashlib
import json
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .bundles import BundleValidator, Ed25519Keyring, ValidatedBundle
from .imports import confirm_import
from .models import AccountSnapshot, ImportProposal, SourceKind
from .producer_request import build_producer_analysis_request, select_public_task
from .profiles import ProfileRepository, ProfileSummary, _snapshot_from_dict


_A_PRODUCER_COMMIT = "dcb1e3ee220b85229bedc6c79d72ebe495825f37"
_A_FORMAT_PROFILE = "starhelp.b-publicbundle-envelope.v1"
_B_SNAPSHOT_COMMIT = "103741e02c90ac672017f783058bdd8dacae982e"
_B_SNAPSHOT_PROFILE = "starhelp.desktop.snapshot.interop-min.v0.1"
_SIGNING_KEY_ID = "starhelp-fixture-ed25519-v1"
_EXPECTED_HASHES = {
    "starhelp-interop-min-v0.1-s3.bpublic.json":
        "f777d05bdb269b2e92a612e4fc96a9ad076f9d5b2bc36760c34c1209ff323772",
    "synthetic-b-snapshot-045965b.json":
        "e7269a57b83e3145bd647262c4a88d1663718d4078c502f0cd4829108d9b3b58",
    "equipment-type-table.json":
        "7ffda486ef1b00683d3b3279fb3f2bf802075c46a5f04dbe563fc60f6ed75380",
    "fixture-ed25519-public.pem":
        "7fe277b94d7e7d57dd3fceeaad77495fdff04861c02c3b1cc624c736aac8a29e",
}


@dataclass(frozen=True, slots=True)
class SyntheticDemoContext:
    profile: ProfileSummary
    snapshot: AccountSnapshot
    bundle: ValidatedBundle
    signing_public_key: bytes
    task: dict[str, Any]
    request: dict[str, Any]


def prepare_synthetic_demo(
    profiles: ProfileRepository, *, feedback: dict[str, Any] | None = None
) -> SyntheticDemoContext:
    """Load only pinned synthetic fixtures and create/reuse a separate synthetic profile.

    The embedded key is explicitly test-only. This function has no network client and must never
    be used to verify production bundles.
    """
    root = _fixture_root()
    fixture_bytes = {
        name: _read_pinned_fixture(root, name, expected_hash)
        for name, expected_hash in _EXPECTED_HASHES.items()
    }
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except ImportError as exc:
        raise RuntimeError("the synthetic producer demo requires the desktop crypto extra") from exc

    public_key_object = serialization.load_pem_public_key(
        fixture_bytes["fixture-ed25519-public.pem"]
    )
    if not isinstance(public_key_object, Ed25519PublicKey):
        raise ValueError("the synthetic demo trust fixture is not an Ed25519 public key")
    public_key = public_key_object.public_bytes(
        serialization.Encoding.Raw, serialization.PublicFormat.Raw
    )
    keyring = Ed25519Keyring({_SIGNING_KEY_ID: public_key})
    bundle = BundleValidator().validate(
        fixture_bytes["starhelp-interop-min-v0.1-s3.bpublic.json"],
        supported_capabilities=frozenset({
            "starhelp.knowledge-distribution.v1", "starhelp.local-profile.v0.2",
        }),
        expected_release_id="rel_fixture_s3_0001",
        signature_verifier=keyring,
    )
    payload = bundle.payload()
    table = json.loads(fixture_bytes["equipment-type-table.json"].decode("utf-8"))
    native = payload["objects"].get(f"native-release:{bundle.release_id}", {}).get("bundle")
    entities = native.get("entities") if isinstance(native, dict) else None
    entity_by_id = {
        item.get("entity_id"): item for item in entities if isinstance(item, dict)
    } if isinstance(entities, list) else {}
    table_items = table.get("items") if isinstance(table, dict) else None
    if (
        not isinstance(table_items, list)
        or table.get("release_id") != bundle.release_id
        or not table_items
        or any(
            not isinstance(item, dict)
            or not isinstance(item.get("public_type_id"), str)
            or not isinstance(item.get("kind"), str)
            or not isinstance(item.get("entity_type"), str)
            or item["kind"] != item["entity_type"]
            or not isinstance(item.get("slot"), str)
            or (entity := entity_by_id.get(item.get("public_type_id"))) is None
            or entity.get("entity_type") != item["entity_type"]
            for item in table_items
        )
    ):
        raise ValueError("the pinned equipment type table does not match the signed release")
    fixture_snapshot = _snapshot_from_dict(json.loads(
        fixture_bytes["synthetic-b-snapshot-045965b.json"].decode("utf-8")
    ))
    profile, snapshot = _get_or_create_demo_profile(profiles, fixture_snapshot)

    planner_view = payload["objects"][f"planner-view:{bundle.release_id}"]["bundle"]
    stages = planner_view["stages"]
    templates = planner_view["templates"]
    selected = next((
        (stage, template, goal)
        for stage in stages
        for template in templates
        if stage["stage_id"] in template["stage_ids"]
        for goal in template["public_goals"]
    ), None)
    if selected is None:
        raise ValueError("the pinned synthetic bundle has no executable stage/template/goal mapping")
    stage, template, goal = selected
    task = select_public_task(
        payload,
        stage_id=stage["stage_id"],
        template_id=template["id"],
        goal_kind=goal["kind"],
        allow_rearrangement=True,
    )
    request = build_producer_analysis_request(
        validated_bundle=bundle,
        task=task,
        snapshot=snapshot,
        authorization_generation=profile.generation,
        distribution_trust_purpose="synthetic-test",
        distribution_public_keys={_SIGNING_KEY_ID: public_key},
        bundle_producer_commit=_A_PRODUCER_COMMIT,
        bundle_format_profile=_A_FORMAT_PROFILE,
        snapshot_producer_commit=_B_SNAPSHOT_COMMIT,
        snapshot_format_profile=_B_SNAPSHOT_PROFILE,
        evaluation_time=datetime.now(UTC),
        feedback=feedback,
    )
    return SyntheticDemoContext(
        profile=profile,
        snapshot=snapshot,
        bundle=bundle,
        signing_public_key=public_key,
        task=task,
        request=request,
    )


def _get_or_create_demo_profile(
    profiles: ProfileRepository, fixture_snapshot: AccountSnapshot
) -> tuple[ProfileSummary, AccountSnapshot]:
    for profile in profiles.list_profiles():
        if profile.provider_id != "synthetic-demo":
            continue
        try:
            snapshot = profiles.load_snapshot(profile.profile_id, profile.generation)
        except (FileNotFoundError, PermissionError, ValueError):
            continue
        if _same_synthetic_content(snapshot, fixture_snapshot):
            return profile, snapshot

    proposal = ImportProposal.create(
        source_kind=SourceKind.STRUCTURED_IMPORT,
        source_id="synthetic-fixture:interop-min-v0.1-s3",
        observed_at=fixture_snapshot.generated_at,
        fields=dict(fixture_snapshot.fields),
        ownership=dict(fixture_snapshot.ownership),
        equipment=fixture_snapshot.equipment,
        coverage=fixture_snapshot.coverage,
        warnings=("仅用于本机生产者联调的合成数据，不代表真实账号或游戏资料。",),
    )
    occupied_labels = {item.label for item in profiles.list_profiles()}
    label = "合成演示档案（仅 fixture）"
    suffix = 2
    while label in occupied_labels:
        label = f"合成演示档案（仅 fixture，{suffix}）"
        suffix += 1
    profile = profiles.create_from_confirmed_import(
        label=label,
        provider_id="synthetic-demo",
        server_label="fixture-only",
        proposal=confirm_import(proposal),
    )
    snapshot = profiles.load_snapshot(profile.profile_id, profile.generation)
    return profile, snapshot


def _same_synthetic_content(left: AccountSnapshot, right: AccountSnapshot) -> bool:
    return (
        left.fields == right.fields
        and left.ownership == right.ownership
        and left.equipment == right.equipment
        and left.coverage == right.coverage
    )


def _fixture_root() -> Path:
    frozen_root = getattr(sys, "_MEIPASS", None)
    if getattr(sys, "frozen", False) and isinstance(frozen_root, str):
        return Path(frozen_root) / "demo-fixtures"
    return Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "producer-interop-s3"


def _read_pinned_fixture(root: Path, name: str, expected_hash: str) -> bytes:
    try:
        data = (root / name).read_bytes()
    except OSError as exc:
        raise RuntimeError("the bundled synthetic producer demo fixture is unavailable") from exc
    if hashlib.sha256(data).hexdigest() != expected_hash:
        raise ValueError("the bundled synthetic producer demo fixture checksum does not match")
    return data
