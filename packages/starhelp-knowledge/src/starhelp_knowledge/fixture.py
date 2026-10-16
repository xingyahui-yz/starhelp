"""Deterministic, explicitly synthetic end-to-end fixture publisher."""

from __future__ import annotations

import hashlib
import json
import subprocess
from collections import defaultdict
from pathlib import Path
import tempfile
from unittest.mock import patch

from starhelp_knowledge.database import KnowledgeDatabase
from starhelp_knowledge.distribution import export_distribution_from_service
from starhelp_knowledge.interop import B_SNAPSHOT_COMMIT, write_pinned_b_synthetic_snapshot
from starhelp_knowledge.policy import Principal
from starhelp_knowledge.service import KnowledgeService
from starhelp_knowledge import __version__

FIXTURE_KEY_ID = "starhelp-fixture-ed25519-v1"
_FIXTURE_SEED = bytes.fromhex("5f8a08cc63c14b9723a9c44a70c142e9133b1825adf0a9478d26582144e9c701")
_FIXTURE_TIME = "2026-10-16T00:00:00+00:00"
_ACTOR = Principal("fixture:maintainer", frozenset({"admin"}))
_REVIEWER = Principal("fixture:reviewer", frozenset({"reviewer"}))
_PUBLISHER = Principal("fixture:publisher", frozenset({"publisher"}))


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _fixture_service(
    database: Path,
    *,
    omit_stage_resource_reuse: bool = False,
    omit_template_public_goals: bool = False,
    invalid_condition_value_type: bool = False,
    condition_outside_variant_roster: bool = False,
) -> tuple[KnowledgeService, str]:
    import starhelp_knowledge.service as service_module

    counters: defaultdict[str, int] = defaultdict(int)

    def fixed_id(prefix: str) -> str:
        counters[prefix] += 1
        return f"{prefix}_fixture_{counters[prefix]:04d}"

    with patch.object(service_module, "_new_id", fixed_id), patch.object(service_module, "now_iso", lambda: _FIXTURE_TIME):
        service = KnowledgeService(KnowledgeDatabase(database))
        service.add_source(
            _ACTOR,
            source_id="fixture:source:public",
            name="Synthetic fixture source",
            platform="synthetic",
            source_role="reference",
        )
        service.set_source_policy(
            _ACTOR,
            source_id="fixture:source:public",
            permission_status="allowed",
            terms_reference="https://example.invalid/fixture-terms",
            allowed_domains=["example.invalid"],
            allowed_paths=["/public"],
            rate_policy={"mode": "synthetic_no_requests"},
            storage_policy={"mode": "minimal_excerpt", "max_excerpt_chars": 200},
            checked_at=_FIXTURE_TIME,
        )
        evidence_id = service.add_public_evidence(
            _ACTOR,
            source_id="fixture:source:public",
            external_content_id="fixture:doc:one",
            canonical_url="https://example.invalid/public/fixture",
            content_kind="synthetic_fixture",
            title="Synthetic fixture evidence",
            author_id=None,
            excerpt="Synthetic test evidence; no game facts or real guide content.",
            locator={"kind": "fixture", "value": "one"},
            license_status="allowed",
            published_at=None,
            relation="supports",
            evidence_status="confirmed",
            scope={"fixture_only": True},
        )
        evidence_refs = [{"id": evidence_id, "revision": 1}]
        scope = {
            "game_version": "fixture:game:v1",
            "environment": "live",
            "release_status": "released",
            "mode_id": "fixture:mode:duo",
            "cycle_id": "fixture:cycle:one",
            "stage_id": "fixture:stage:one",
        }
        entity_refs: dict[str, dict[str, object]] = {}
        for identifier, name in (
            ("fixture:character:a", "Synthetic Character A"),
            ("fixture:character:b", "Synthetic Character B"),
            ("fixture:character:c", "Synthetic Character C"),
        ):
            candidate = service.create_candidate(
                _ACTOR,
                kind="entity",
                record_id=identifier,
                scope=scope,
                payload={"entity_type": "character", "canonical_name": name},
                evidence_refs=evidence_refs,
                dependency_refs=[],
            )
            service.review_candidate(
                _REVIEWER,
                kind="entity",
                record_id=identifier,
                revision=candidate["revision"],
                expected_content_hash=candidate["content_hash"],
                decision="approved",
                note="Explicit synthetic fixture review; not game-content approval.",
            )
            entity_refs[identifier] = {"kind": "entity", "id": identifier, "revision": candidate["revision"]}

        stage_payload = {
            "title": "Synthetic two-partition stage",
            "partitions": [
                {"partition_id": "fixture:upper", "slots": [{"slot_id": "fixture:upper:slot-1"}]},
                {"partition_id": "fixture:lower", "slots": [{"slot_id": "fixture:lower:slot-1"}]},
            ],
        }
        if not omit_stage_resource_reuse:
            stage_payload["resource_reuse"] = {"characters": "exclusive", "equipment": "exclusive"}
        stage = service.create_candidate(
            _ACTOR,
            kind="stage",
            record_id=scope["stage_id"],
            scope=scope,
            payload=stage_payload,
            evidence_refs=evidence_refs,
            dependency_refs=[],
        )
        service.review_candidate(
            _REVIEWER,
            kind="stage",
            record_id=scope["stage_id"],
            revision=stage["revision"],
            expected_content_hash=stage["content_hash"],
            decision="approved",
            note="Explicit synthetic fixture review; not game-content approval.",
        )

        variant_members: list[dict[str, object]] = []
        for identifier, title, upper_character in (
            ("fixture:variant:main", "Synthetic main", "fixture:character:a"),
            ("fixture:variant:alternate", "Synthetic complete alternate", "fixture:character:c"),
        ):
            dependencies = [entity_refs[upper_character], entity_refs["fixture:character:b"]]
            condition_subject = {"kind": "team_slot", "slot_id": "fixture:upper:slot-1"}
            if condition_outside_variant_roster and identifier == "fixture:variant:main":
                condition_subject = {"kind": "entity", "entity_id": "fixture:character:c"}
            condition_value: object = 100
            if invalid_condition_value_type:
                condition_value = "not-a-number"
            variant = service.create_candidate(
                _ACTOR,
                kind="variant",
                record_id=identifier,
                scope=scope,
                payload={
                    "title": title,
                    "team": [
                        {"slot_id": "fixture:upper:slot-1", "partition": "fixture:upper", "entity_id": upper_character, "equipment_requirements": []},
                        {"slot_id": "fixture:lower:slot-1", "partition": "fixture:lower", "entity_id": "fixture:character:b", "equipment_requirements": []},
                    ],
                    "conditions": [{
                        "condition_id": f"fixture:condition:{identifier}",
                        "subject": condition_subject,
                        "attribute": "fixture:attack",
                        "operator": "gte",
                        "value": condition_value,
                        "unit": "points",
                        "measurement_context": {"phase": "pre_battle", "assumptions": []},
                        "requirement": "soft",
                        "evidence_status": "confirmed",
                        "evidence_refs": evidence_refs,
                    }],
                    "steps": [{"order": 1, "text": "Synthetic-only action step."}],
                },
                evidence_refs=evidence_refs,
                dependency_refs=dependencies,
            )
            service.review_candidate(
                _REVIEWER,
                kind="variant",
                record_id=identifier,
                revision=variant["revision"],
                expected_content_hash=variant["content_hash"],
                decision="approved",
                note="Explicit synthetic fixture review; not game-content approval.",
            )
            variant_members.append({"kind": "variant", "id": identifier, "revision": variant["revision"]})

        template_id = "fixture:template:one"
        template_payload = {
            "title": "Synthetic complete planner fixture",
            "primary_variant_id": "fixture:variant:main",
            "alternate_variant_ids": ["fixture:variant:alternate"],
        }
        if not omit_template_public_goals:
            template_payload["public_goals"] = [{"kind": "fixture:goal:clear"}]
        template = service.create_candidate(
            _ACTOR,
            kind="template",
            record_id=template_id,
            scope=scope,
            payload=template_payload,
            evidence_refs=evidence_refs,
            dependency_refs=[
                {"kind": "stage", "id": scope["stage_id"], "revision": stage["revision"]},
                *variant_members,
            ],
        )
        service.review_candidate(
            _REVIEWER,
            kind="template",
            record_id=template_id,
            revision=template["revision"],
            expected_content_hash=template["content_hash"],
            decision="approved",
            note="Explicit synthetic fixture review; not game-content approval.",
        )

        release = service.build_release(
            _PUBLISHER,
            members=[
                *[{"kind": "entity", "id": key, "revision": 1} for key in sorted(entity_refs)],
                {"kind": "stage", "id": scope["stage_id"], "revision": stage["revision"]},
                *variant_members,
                {"kind": "template", "id": template_id, "revision": template["revision"]},
            ],
            coverage={"status": "synthetic", "reason": "fixture_only_no_game_facts"},
            required_capabilities=[],
            attribute_definitions={
                "fixture:attack": {
                    "value_type": "number",
                    "unit": "points",
                    "phases": ["pre_battle"],
                    "loadout_dependent": False,
                }
            },
        )
        service.validate_release(_PUBLISHER, release["index_release_id"], idempotency_key="fixture-validate")
        service.activate_release(
            _PUBLISHER,
            release["index_release_id"],
            expected_active_release_id=None,
            idempotency_key="fixture-activate",
        )
        return service, release["index_release_id"]


def build_fixture_artifacts(output_dir: Path, *, b_root: Path, overwrite: bool = False) -> dict[str, Any]:
    """Generate deterministic public-only artifacts with a test-only signing key."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

    output_dir.mkdir(parents=True, exist_ok=True)
    bundle_path = output_dir / "knowledge-planner-fixture-v1.bpublic.json"
    public_key_path = output_dir / "fixture-ed25519-public.pem"
    b_snapshot_path = output_dir / "synthetic-b-snapshot-045965b.json"
    sums_path = output_dir / "SHA256SUMS.txt"
    destinations = (bundle_path, public_key_path, b_snapshot_path, sums_path)
    if not overwrite and any(path.exists() for path in destinations):
        raise FileExistsError("fixture artifacts already exist; pass --overwrite to replace them")
    root = Path(__file__).resolve().parents[4]
    try:
        producer_commit = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=root, check=True, capture_output=True, text=True
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        producer_commit = "uncommitted-source"
    private_key = Ed25519PrivateKey.from_private_bytes(_FIXTURE_SEED)
    with tempfile.TemporaryDirectory(prefix=".fixture-work-", dir=output_dir) as work:
        service, release_id = _fixture_service(Path(work) / "fixture.sqlite3")
        envelope = export_distribution_from_service(
            service,
            release_id,
            producer_version=__version__,
            producer_commit=producer_commit,
            signing_private_key=private_key,
            signing_key_id=FIXTURE_KEY_ID,
        )
    bundle_bytes = json.dumps(envelope, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    public_key_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    for path, body in zip((bundle_path, public_key_path), (bundle_bytes, public_key_bytes)):
        temporary = path.with_suffix(path.suffix + ".tmp")
        temporary.write_bytes(body)
        temporary.replace(path)
    b_snapshot_bytes = write_pinned_b_synthetic_snapshot(
        b_root, temp_root=output_dir, output=b_snapshot_path
    )
    bundle_hash = hashlib.sha256(bundle_bytes).hexdigest()
    public_key_hash = hashlib.sha256(public_key_bytes).hexdigest()
    b_snapshot_hash = hashlib.sha256(b_snapshot_bytes).hexdigest()
    sums_path.write_text(
        f"{bundle_hash}  {bundle_path.name}\n{public_key_hash}  {public_key_path.name}\n{b_snapshot_hash}  {b_snapshot_path.name}\n",
        encoding="ascii",
        newline="\n",
    )
    return {
        "artifact": str(bundle_path),
        "public_key": str(public_key_path),
        "b_snapshot": str(b_snapshot_path),
        "release_id": envelope["manifest"]["index_release_id"],
        "b_snapshot_source_commit": B_SNAPSHOT_COMMIT,
        "producer_commit": producer_commit,
        "bundle_sha256": bundle_hash,
        "public_key_sha256": public_key_hash,
        "b_snapshot_sha256": b_snapshot_hash,
        "signing_key_id": FIXTURE_KEY_ID,
    }
