from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid4

from .bundles import ValidatedBundle
from .profiles import _snapshot_to_dict
from .models import AccountSnapshot


def select_public_task(
    bundle: dict[str, Any],
    *,
    stage_id: str,
    template_id: str,
    goal_kind: str,
    fixed_character_ids: Sequence[str] = (),
    excluded_character_ids: Sequence[str] = (),
    locked_local_instance_ids: Sequence[str] = (),
    allow_rearrangement: bool = False,
) -> dict[str, Any]:
    """Select an exact stage scope and goal from a validated planner view.

    User-facing labels are deliberately not translated here. The selected scope and goal must
    already exist in the bundle, so an unreviewed UI string cannot become public semantics.
    """
    if not isinstance(bundle, dict) or not isinstance(stage_id, str) or not stage_id:
        raise ValueError("a validated public bundle and stage ID are required")
    if not isinstance(template_id, str) or not template_id or not isinstance(goal_kind, str) or not goal_kind:
        raise ValueError("a public template and goal are required")
    if not isinstance(allow_rearrangement, bool):
        raise ValueError("rearrangement must be an explicit boolean")

    objects = bundle.get("objects")
    release_id = bundle.get("manifest", {}).get("index_release_id")
    if not isinstance(objects, dict) or not isinstance(release_id, str) or not release_id:
        raise ValueError("validated bundle is missing its object graph or release ID")
    view_object = objects.get(f"planner-view:{release_id}")
    view = view_object.get("bundle") if isinstance(view_object, dict) else None
    if not isinstance(view, dict):
        raise ValueError("validated bundle has no planner view for its release")

    stages = view.get("stages")
    templates = view.get("templates")
    if not isinstance(stages, list) or not isinstance(templates, list):
        raise ValueError("planner view has no selectable stages or templates")
    stage_matches = [
        item for item in stages if isinstance(item, dict) and item.get("stage_id") == stage_id
    ]
    template_matches = [
        item for item in templates if isinstance(item, dict) and item.get("id") == template_id
    ]
    if len(stage_matches) != 1 or len(template_matches) != 1:
        raise ValueError("selected stage or template is missing or ambiguous in the public bundle")
    stage = stage_matches[0]
    template = template_matches[0]
    if stage_id not in template.get("stage_ids", []):
        raise ValueError("selected template does not include the selected public stage")
    if stage.get("index_release_id") != release_id or template.get("index_release_id") != release_id:
        raise ValueError("selected public mapping does not belong to the active bundle release")
    scope = stage.get("scope")
    goals = template.get("public_goals")
    if not isinstance(scope, dict) or not isinstance(goals, list):
        raise ValueError("selected stage scope or public goals are malformed")
    goal_matches = [item for item in goals if isinstance(item, dict) and item.get("kind") == goal_kind]
    if len(goal_matches) != 1:
        raise ValueError("selected public goal is missing or ambiguous in the template")

    return {
        "scope": dict(scope),
        "public_goal": dict(goal_matches[0]),
        "fixed_character_ids": _validated_ids(fixed_character_ids, "fixed characters"),
        "excluded_character_ids": _validated_ids(excluded_character_ids, "excluded characters"),
        "locked_local_instance_ids": _validated_ids(locked_local_instance_ids, "locked equipment"),
        "allow_rearrangement": allow_rearrangement,
    }


def build_producer_analysis_request(
    *,
    validated_bundle: ValidatedBundle,
    task: dict[str, Any],
    snapshot: AccountSnapshot,
    authorization_generation: int,
    distribution_trust_purpose: str,
    distribution_public_keys: dict[str, bytes],
    bundle_producer_commit: str,
    bundle_format_profile: str,
    snapshot_producer_commit: str,
    snapshot_format_profile: str,
    evaluation_time: datetime | None = None,
    withdrawn_public_refs: Sequence[dict[str, Any]] = (),
    request_id: str | None = None,
) -> dict[str, Any]:
    """Build the immutable-source wrapper consumed by the pinned local planner worker.

    All producer provenance and trust inputs are explicit. This function does not select
    production trust, infer source commits, access the network, or persist private data.
    """
    if authorization_generation < 1:
        raise ValueError("authorization generation must be positive")
    if (
        not isinstance(task, dict)
        or not isinstance(task.get("scope"), dict)
        or not isinstance(task.get("public_goal"), dict)
    ):
        raise ValueError("task must contain an exact public scope and goal")
    if not distribution_trust_purpose.strip():
        raise ValueError("distribution trust purpose must be stated explicitly")
    if not distribution_public_keys:
        raise ValueError("at least one explicitly provisioned public signing key is required")
    if any(not key_id or len(key) != 32 for key_id, key in distribution_public_keys.items()):
        raise ValueError("distribution public keys must have IDs and 32-byte Ed25519 values")
    for name, value in (
        ("A producer commit", bundle_producer_commit),
        ("A format profile", bundle_format_profile),
        ("B snapshot producer commit", snapshot_producer_commit),
        ("B snapshot format profile", snapshot_format_profile),
    ):
        if not value.strip():
            raise ValueError(f"{name} must be explicit")

    profile_id = str(snapshot.profile_id)
    current_request_id = request_id or f"desktop:{uuid4()}"
    if not current_request_id.strip():
        raise ValueError("request ID must not be empty")
    bundle_bytes = validated_bundle.payload_json
    bundle = validated_bundle.payload()
    manifest = bundle.get("manifest")
    if not isinstance(manifest, dict):
        raise ValueError("validated bundle has no manifest")
    if manifest.get("index_release_id") != validated_bundle.release_id:
        raise ValueError("validated bundle release ID does not match its immutable bytes")
    signing_key_id = manifest.get("signing_key_id")
    if not isinstance(signing_key_id, str) or signing_key_id not in distribution_public_keys:
        raise ValueError("distribution trust does not include the bundle's signing key")
    snapshot_bytes = json.dumps(
        _snapshot_to_dict(snapshot), ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    snapshot_wrapper = {
        "profile_id": profile_id,
        "snapshot_revision": snapshot.revision,
        "authorization_generation": authorization_generation,
        "authorization_state": "active",
    }
    producer_task = json.loads(json.dumps(task, ensure_ascii=False, allow_nan=False))
    timestamp = evaluation_time or datetime.now(UTC)
    if timestamp.tzinfo is None:
        raise ValueError("evaluation time must be timezone aware")
    timestamp_text = timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if any(not isinstance(item, Mapping) for item in withdrawn_public_refs):
        raise ValueError("withdrawn public references must be objects")
    withdrawn_refs = [dict(item) for item in withdrawn_public_refs]
    if any(not isinstance(item.get("id"), str) or not isinstance(item.get("revision"), int)
           or isinstance(item.get("revision"), bool) for item in withdrawn_refs):
        raise ValueError("withdrawn public references must have string IDs and integer revisions")

    producer_request = {
        "schema_id": "ProducerAnalysisRequest",
        "schema_version": "0.1",
        "adapter_profile": "starhelp.producers.v0.1",
        "request_id": current_request_id,
        "public_bundle": {
            "producer": "starhelp_knowledge",
            "producer_commit": bundle_producer_commit,
            "format_profile": bundle_format_profile,
            "expected_release_id": validated_bundle.release_id,
            "raw_json": bundle_bytes.decode("utf-8"),
            "sha256": hashlib.sha256(bundle_bytes).hexdigest(),
        },
        "account_snapshot": {
            "producer": "starhelp_desktop",
            "producer_commit": snapshot_producer_commit,
            "format_profile": snapshot_format_profile,
            "raw_json": snapshot_bytes.decode("utf-8"),
            "sha256": hashlib.sha256(snapshot_bytes).hexdigest(),
        },
        "authorization_context": {
            "profile_id": profile_id,
            "active": True,
            "generation": authorization_generation,
        },
        "distribution_trust": {
            "purpose": distribution_trust_purpose,
            "public_keys": {key_id: key.hex() for key_id, key in distribution_public_keys.items()},
        },
        "task": producer_task,
        "evaluation_time": timestamp_text,
        "latest_known_validity": {"withdrawn_public_refs": withdrawn_refs},
    }
    return {
        "contract_version": "0.1-draft",
        "schema_id": "AnalysisRequest",
        "schema_version": "0.1-draft",
        "request_id": current_request_id,
        "authorization_generation": authorization_generation,
        "public_bundle": bundle,
        "account_snapshot": snapshot_wrapper,
        "task": producer_task,
        "producer_request": producer_request,
    }


def _validated_ids(values: Sequence[str], label: str) -> list[str]:
    if not isinstance(values, Sequence) or isinstance(values, (str, bytes)):
        raise ValueError(f"{label} must be a sequence of identifiers")
    if any(
        not isinstance(value, str)
        or not value.strip()
        or value != value.strip()
        or len(value) > 160
        or any(ord(char) < 32 for char in value)
        for value in values
    ):
        raise ValueError(f"{label} contains an invalid identifier")
    if len(values) > 64 or len(values) != len(set(values)):
        raise ValueError(f"{label} is duplicated or exceeds the 64-item limit")
    return list(values)
