"""S3-only synthetic delivery for the frozen A/B/C interoperability profile."""

from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from collections import defaultdict
from pathlib import Path
from typing import Any
from unittest.mock import patch

from starhelp_knowledge import __version__
from starhelp_knowledge.database import KnowledgeDatabase
from starhelp_knowledge.distribution import export_distribution_from_service
from starhelp_knowledge.fixture import FIXTURE_KEY_ID, _FIXTURE_SEED, _FIXTURE_TIME
from starhelp_knowledge.interop import B_SNAPSHOT_COMMIT, write_pinned_b_synthetic_snapshot
from starhelp_knowledge.policy import Principal
from starhelp_knowledge.service import KnowledgeService

S3_RELEASE_ID = "rel_fixture_s3_0001"
S3_ARTIFACT_DIRECTORY = "interop-min-v0.1-s3"
S3_BUNDLE_NAME = "starhelp-interop-min-v0.1-s3.bpublic.json"
S3_LIGHT_CONE_ID = "fixture:s3:alpha:equipment:light-cone"
S3_RELIC_ID = "fixture:s3:alpha:equipment:relic"
S3_EQUIPMENT_TYPE_TABLE = [
    {
        "kind": "light_cone",
        "slot": "light_cone",
        "public_type_id": S3_LIGHT_CONE_ID,
        "entity_type": "light_cone",
    },
    {
        "kind": "relic",
        "slot": "body",
        "public_type_id": S3_RELIC_ID,
        "entity_type": "relic",
    },
]
S3_EQUIPMENT_SNAPSHOT = (
    {
        "local_instance_id": "33333333-3333-4333-8333-333333333333",
        "public_type_id": S3_LIGHT_CONE_ID,
        "slot": "light_cone",
        "identity": "player_confirmed",
        "owner_character_id": "fixture:s3:alpha:character:b",
    },
    {
        "local_instance_id": "44444444-4444-4444-8444-444444444444",
        "public_type_id": S3_LIGHT_CONE_ID,
        "slot": "light_cone",
        "identity": "ambiguous",
        "owner_character_id": "fixture:s3:alpha:character:d",
    },
    {
        "local_instance_id": "55555555-5555-4555-8555-555555555555",
        "public_type_id": S3_RELIC_ID,
        "slot": "body",
        "identity": "player_confirmed",
        "owner_character_id": "fixture:s3:alpha:character:d",
    },
    {
        "local_instance_id": "66666666-6666-4666-8666-666666666666",
        "public_type_id": S3_RELIC_ID,
        "slot": "body",
        "identity": "source_confirmed",
        "owner_character_id": "fixture:s3:alpha:character:d",
    },
)

_S3_MAINTAINER = Principal(
    "fixture:s3:maintainer", frozenset({"updater", "reviewer", "publisher"})
)
_SOURCE_ADMIN = Principal("fixture:s3:source-admin", frozenset({"admin"}))
_MODES = ("alpha", "beta", "gamma")


def _fixture_id_factory() -> Any:
    counters: defaultdict[str, int] = defaultdict(int)

    def fixed_id(prefix: str) -> str:
        counters[prefix] += 1
        if prefix == "rel":
            return S3_RELEASE_ID
        return f"{prefix}_fixture_s3_{counters[prefix]:04d}"

    return fixed_id


def _s3_fixture_service(database: Path) -> tuple[KnowledgeService, str, tuple[str, ...]]:
    import starhelp_knowledge.service as service_module

    with patch.object(service_module, "_new_id", _fixture_id_factory()), patch.object(
        service_module, "now_iso", lambda: _FIXTURE_TIME
    ):
        service = KnowledgeService(KnowledgeDatabase(database))
        service.add_source(
            _SOURCE_ADMIN,
            source_id="fixture:s3:source:public",
            name="S3 synthetic fixture source",
            platform="synthetic",
            source_role="reference",
        )
        service.set_source_policy(
            _SOURCE_ADMIN,
            source_id="fixture:s3:source:public",
            permission_status="allowed",
            terms_reference="https://example.invalid/s3-fixture-terms",
            allowed_domains=["example.invalid"],
            allowed_paths=["/public"],
            rate_policy={"mode": "synthetic_no_requests"},
            storage_policy={"mode": "minimal_excerpt", "max_excerpt_chars": 200},
            checked_at=_FIXTURE_TIME,
        )
        evidence_id = service.add_public_evidence(
            _SOURCE_ADMIN,
            source_id="fixture:s3:source:public",
            external_content_id="fixture:s3:doc:one",
            canonical_url="https://example.invalid/public/s3-fixture",
            content_kind="synthetic_fixture",
            title="S3 synthetic fixture evidence",
            author_id=None,
            excerpt="Synthetic protocol fixture only; no real game facts or guide content.",
            locator={"kind": "fixture", "value": "s3"},
            license_status="allowed",
            published_at=None,
            relation="supports",
            evidence_status="confirmed",
            scope={"fixture_only": True},
        )
        evidence_refs = [{"id": evidence_id, "revision": 1}]
        entity_refs: dict[str, dict[str, Any]] = {}
        members: list[dict[str, Any]] = []
        ownership_ids: list[str] = []

        def create_entity(
            identifier: str, entity_type: str, name: str, scope: dict[str, str]
        ) -> dict[str, Any]:
            candidate = service.create_candidate(
                _S3_MAINTAINER,
                kind="entity",
                record_id=identifier,
                scope=scope,
                payload={"entity_type": entity_type, "canonical_name": name},
                evidence_refs=evidence_refs,
                dependency_refs=[],
            )
            service.review_candidate(
                _S3_MAINTAINER,
                kind="entity",
                record_id=identifier,
                revision=candidate["revision"],
                expected_content_hash=candidate["content_hash"],
                decision="approved",
                note="Explicit synthetic S3 review bound to the immutable content hash.",
            )
            ref = {"kind": "entity", "id": identifier, "revision": candidate["revision"]}
            entity_refs[identifier] = ref
            members.append(ref)
            return ref

        def approve(kind: str, record_id: str, candidate: dict[str, Any]) -> None:
            service.review_candidate(
                _S3_MAINTAINER,
                kind=kind,
                record_id=record_id,
                revision=candidate["revision"],
                expected_content_hash=candidate["content_hash"],
                decision="approved",
                note="Explicit synthetic S3 review bound to the immutable content hash.",
            )

        for mode in _MODES:
            stage_id = f"fixture:s3:{mode}:stage"
            scope = {
                "game_version": "fixture:game:v1",
                "environment": "live",
                "release_status": "released",
                "mode_id": f"fixture:mode:{mode}",
                "cycle_id": f"fixture:cycle:{mode}",
                "stage_id": stage_id,
            }
            character_ids = {
                letter: f"fixture:s3:{mode}:character:{letter}"
                for letter in ("a", "b", "c")
            }
            if mode == "alpha":
                character_ids["d"] = f"fixture:s3:{mode}:character:d"
            for letter, identifier in character_ids.items():
                ownership_ids.append(identifier)
                create_entity(
                    identifier,
                    "character",
                    f"Synthetic {mode.title()} Character {letter.upper()}",
                    scope,
                )

            type_ids: list[str] = []
            if mode == "alpha":
                type_ids = [S3_LIGHT_CONE_ID, S3_RELIC_ID]
                create_entity(S3_LIGHT_CONE_ID, "light_cone", "Synthetic Light Cone Type", scope)
                create_entity(S3_RELIC_ID, "relic", "Synthetic Relic Type", scope)

            upper_partition = f"fixture:s3:{mode}:upper"
            lower_partition = f"fixture:s3:{mode}:lower"
            upper_slot = f"fixture:s3:{mode}:upper:slot-1"
            lower_slot = f"fixture:s3:{mode}:lower:slot-1"
            stage_payload = {
                "title": f"Synthetic {mode.title()} two-partition stage",
                "partitions": [
                    {"partition_id": upper_partition, "slots": [{"slot_id": upper_slot}]},
                    {"partition_id": lower_partition, "slots": [{"slot_id": lower_slot}]},
                ],
                "resource_reuse": {"characters": "exclusive", "equipment": "exclusive"},
            }
            stage = service.create_candidate(
                _S3_MAINTAINER,
                kind="stage",
                record_id=stage_id,
                scope=scope,
                payload=stage_payload,
                evidence_refs=evidence_refs,
                dependency_refs=[],
            )
            approve("stage", stage_id, stage)
            stage_ref = {"kind": "stage", "id": stage_id, "revision": stage["revision"]}
            members.append(stage_ref)

            variant_refs: list[dict[str, Any]] = []
            for variant_kind, upper_character in (("main", "a"), ("alternate", "c")):
                variant_id = f"fixture:s3:{mode}:variant:{variant_kind}"
                dependencies = [entity_refs[character_ids[upper_character]], entity_refs[character_ids["b"]]]
                if mode == "alpha":
                    dependencies.extend(entity_refs[identifier] for identifier in type_ids)
                upper_requirements = (
                    [{"kind": "light_cone", "slot": "light_cone", "public_type_id": S3_LIGHT_CONE_ID}]
                    if mode == "alpha" else []
                )
                lower_requirements = (
                    [{"kind": "relic", "slot": "body", "public_type_ids": [S3_RELIC_ID]}]
                    if mode == "alpha" else []
                )
                variant = service.create_candidate(
                    _S3_MAINTAINER,
                    kind="variant",
                    record_id=variant_id,
                    scope=scope,
                    payload={
                        "title": f"Synthetic {mode.title()} {variant_kind}",
                        "team": [
                            {
                                "slot_id": upper_slot,
                                "partition": upper_partition,
                                "entity_id": character_ids[upper_character],
                                "equipment_requirements": upper_requirements,
                            },
                            {
                                "slot_id": lower_slot,
                                "partition": lower_partition,
                                "entity_id": character_ids["b"],
                                "equipment_requirements": lower_requirements,
                            },
                        ],
                        "conditions": [],
                        "steps": [{"order": 1, "text": "Synthetic-only action step."}],
                    },
                    evidence_refs=evidence_refs,
                    dependency_refs=dependencies,
                )
                approve("variant", variant_id, variant)
                ref = {"kind": "variant", "id": variant_id, "revision": variant["revision"]}
                variant_refs.append(ref)
                members.append(ref)

            template_id = f"fixture:s3:{mode}:template"
            template = service.create_candidate(
                _S3_MAINTAINER,
                kind="template",
                record_id=template_id,
                scope=scope,
                payload={
                    "title": f"Synthetic {mode.title()} complete planner template",
                    "primary_variant_id": variant_refs[0]["id"],
                    "alternate_variant_ids": [variant_refs[1]["id"]],
                    "public_goals": [{"kind": "fixture:goal:clear"}],
                },
                evidence_refs=evidence_refs,
                dependency_refs=[stage_ref, *variant_refs],
            )
            approve("template", template_id, template)
            members.append({"kind": "template", "id": template_id, "revision": template["revision"]})

        release = service.build_release(
            _S3_MAINTAINER,
            members=sorted(members, key=lambda item: (item["kind"], item["id"], item["revision"])),
            coverage={"status": "synthetic", "reason": "s3_fixture_only_no_game_facts"},
            required_capabilities=[],
            attribute_definitions={},
        )
        service.validate_release(_S3_MAINTAINER, release["index_release_id"], idempotency_key="s3-fixture-validate")
        service.activate_release(
            _S3_MAINTAINER,
            release["index_release_id"],
            expected_active_release_id=None,
            idempotency_key="s3-fixture-activate",
        )
        return service, release["index_release_id"], tuple(sorted(ownership_ids))


def _producer_commit(root: Path) -> str:
    try:
        dirty = subprocess.run(
            [
                "git", "status", "--porcelain", "--",
                "packages/starhelp-knowledge/src", "packages/starhelp-knowledge/pyproject.toml",
            ],
            cwd=root,
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
        if dirty:
            return "uncommitted-source"
        return subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return "uncommitted-source"


def build_s3_fixture_artifacts(output_dir: Path, *, b_root: Path) -> dict[str, Any]:
    """Build the frozen S3 synthetic release and its pinned B serializer input."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / S3_BUNDLE_NAME
    public_key_path = output_dir / "fixture-ed25519-public.pem"
    type_table_path = output_dir / "equipment-type-table.json"
    b_snapshot_path = output_dir / f"synthetic-b-snapshot-{B_SNAPSHOT_COMMIT[:7]}.json"
    sums_path = output_dir / "SHA256SUMS.txt"
    destinations = (bundle_path, public_key_path, type_table_path, b_snapshot_path, sums_path)
    if any(path.exists() for path in destinations):
        raise FileExistsError("S3 fixture artifacts already exist; use a new immutable output directory")

    root = Path(__file__).resolve().parents[4]
    producer_commit = _producer_commit(root)
    private_key = Ed25519PrivateKey.from_private_bytes(_FIXTURE_SEED)
    with tempfile.TemporaryDirectory(prefix=".fixture-s3-work-", dir=output_dir) as work:
        service, release_id, ownership_ids = _s3_fixture_service(Path(work) / "fixture.sqlite3")
        envelope = export_distribution_from_service(
            service,
            release_id,
            producer_version=__version__,
            producer_commit=producer_commit,
            signing_private_key=private_key,
            signing_key_id=FIXTURE_KEY_ID,
        )

    bundle_bytes = json.dumps(
        envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8") + b"\n"
    public_key_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    type_table = {
        "release_id": release_id,
        "items": S3_EQUIPMENT_TYPE_TABLE,
    }
    type_table_bytes = json.dumps(
        type_table, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    ).encode("utf-8") + b"\n"
    for path, body in (
        (bundle_path, bundle_bytes),
        (public_key_path, public_key_bytes),
        (type_table_path, type_table_bytes),
    ):
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(body)
        temporary.replace(path)
    b_snapshot_bytes = write_pinned_b_synthetic_snapshot(
        b_root,
        temp_root=output_dir,
        output=b_snapshot_path,
        ownership_ids=ownership_ids,
        equipment=S3_EQUIPMENT_SNAPSHOT,
    )
    file_hashes = {
        path.name: hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (bundle_path, public_key_path, type_table_path, b_snapshot_path)
    }
    sums_path.write_text(
        "".join(f"{digest}  {name}\n" for name, digest in sorted(file_hashes.items())),
        encoding="ascii",
        newline="\n",
    )
    return {
        "artifact": str(bundle_path),
        "public_key": str(public_key_path),
        "equipment_type_table": str(type_table_path),
        "b_snapshot": str(b_snapshot_path),
        "release_id": release_id,
        "producer_commit": producer_commit,
        "producer_version": __version__,
        "b_snapshot_source_commit": B_SNAPSHOT_COMMIT,
        "bundle_sha256": file_hashes[bundle_path.name],
        "public_key_sha256": file_hashes[public_key_path.name],
        "equipment_type_table_sha256": file_hashes[type_table_path.name],
        "b_snapshot_sha256": file_hashes[b_snapshot_path.name],
        "signing_key_id": FIXTURE_KEY_ID,
        "coverage": "synthetic-test-only",
    }
