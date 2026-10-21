"""Conservative mapping of explicitly pinned B serializer/encoder tuples."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from .common import B_COMMIT, fail, original

B_PROFILE = "starhelp.desktop.snapshot.045965b"
B_INTEROP_COMMIT = "103741e02c90ac672017f783058bdd8dacae982e"
B_INTEROP_PROFILE = "starhelp.desktop.snapshot.interop-min.v0.1"
B_PRODUCERS = {B_COMMIT: B_PROFILE, B_INTEROP_COMMIT: B_INTEROP_PROFILE}
STATES = {"confirmed": "confirmed", "needs_review": "unknown", "conflict": "conflict", "stale": "stale"}
IDENTITIES = {"player_confirmed": "player_confirmed", "source_confirmed": "unconfirmed", "ambiguous": "ambiguous", "unconfirmed": "unconfirmed"}


def _time(value: Any) -> None:
    if type(value) is not str or datetime.fromisoformat(value.replace("Z", "+00:00")).tzinfo is None:
        fail("invalid_snapshot_time", "producer timestamps require a timezone")


def _field(raw: Any, path: str, diagnostics: list[dict[str, Any]]) -> dict[str, Any]:
    expected = {"value", "status", "source_kind", "source_id", "observed_at", "confirmed_at", "scope"}
    if type(raw) is not dict or set(raw) != expected or raw["status"] not in STATES or raw["source_kind"] not in {"public_profile", "structured_import", "ocr", "manual"} or type(raw["source_id"]) is not str or raw["scope"] is not None and type(raw["scope"]) is not str:
        fail("unsupported_snapshot_field", "B field does not match the fixed serializer profile", [{"path": path}])
    _time(raw["observed_at"])
    if raw["confirmed_at"] is not None:
        _time(raw["confirmed_at"])
    diagnostics.append({"path": path, "reason": "producer_unit_and_measurement_context_unavailable"})
    return {
        "value": raw["value"], "state": STATES[raw["status"]],
        "observed_at": raw["observed_at"], "confirmed_at": raw["confirmed_at"],
        "sources": [{"source_kind": raw["source_kind"], "local_source_id": raw["source_id"], "producer_path": path}],
        "producer_scope": raw["scope"], "producer_status": raw["status"],
        # The serializer has no unit/context. Do not manufacture either one.
    }


def adapt_snapshot(envelope: Any, authorization: Any, entities: list[dict[str, Any]]) -> tuple[dict[str, Any], dict[str, Any], list[dict[str, Any]]]:
    commit = envelope.get("producer_commit") if type(envelope) is dict else None
    if type(commit) is not str or commit not in B_PRODUCERS:
        fail("unsupported_producer_version", "B snapshot producer commit/profile is not supported")
    snapshot, proof = original(envelope, "starhelp_desktop", commit, B_PRODUCERS[commit])
    expected = {"schema_id", "schema_version", "profile_id", "snapshot_id", "revision", "generated_at", "fields", "ownership", "coverage", "equipment"}
    if set(snapshot) != expected or snapshot["schema_id"] != "AccountSnapshot" or snapshot["schema_version"] != "0.1-draft":
        fail("unsupported_snapshot_schema", "B snapshot keys/schema do not match the pinned serializer")
    UUID(snapshot["profile_id"])
    UUID(snapshot["snapshot_id"])
    if type(snapshot["revision"]) is not int or snapshot["revision"] < 1:
        fail("unsupported_snapshot_revision", "B revision zero cannot be represented without changing native C semantics")
    _time(snapshot["generated_at"])
    if type(authorization) is not dict or authorization.get("profile_id") != snapshot["profile_id"] or authorization.get("active") is not True or type(authorization.get("generation")) is not int or authorization["generation"] < 1:
        fail("authorization_context_required", "explicit active caller authorization for this profile/generation is required")
    ownership = snapshot["ownership"]
    if type(ownership) is not dict or any(type(key) is not str or value not in {"owned", "not_owned", "unknown"} for key, value in ownership.items()):
        fail("unsupported_ownership", "ownership semantics are unknown")
    if type(snapshot["fields"]) is not dict or type(snapshot["equipment"]) is not list or type(snapshot["coverage"]) is not list or any(type(path) is not str for path in snapshot["coverage"]):
        fail("unsupported_snapshot_schema", "invalid fixed-profile snapshot collections")
    diagnostics: list[dict[str, Any]] = []
    characters = {identifier: {"entity_id": identifier, "ownership": state, "fields": {}} for identifier, state in ownership.items()}
    for path, raw in snapshot["fields"].items():
        field = _field(raw, path, diagnostics)
        candidates = [(identifier, path.removeprefix(f"character:{identifier}.")) for identifier in characters if path.startswith(f"character:{identifier}.")]
        if len(candidates) == 1:
            identifier, attribute = candidates[0]
            characters[identifier]["fields"][attribute] = field
        else:
            diagnostics.append({"path": path, "reason": "unmapped_flat_field_path"})
    types = {entity["id"]: entity for entity in entities}
    items, seen = [], set()
    for raw in snapshot["equipment"]:
        if type(raw) is not dict or set(raw) != {"local_instance_id", "public_type_id", "slot", "identity", "owner_character_id", "facts"} or raw["identity"] not in IDENTITIES or type(raw["facts"]) is not dict or type(raw["slot"]) is not str:
            fail("unsupported_equipment_schema", "B equipment does not match the fixed serializer")
        UUID(raw["local_instance_id"])
        if raw["local_instance_id"] in seen:
            fail("snapshot_conflict", "duplicate B instance identity")
        seen.add(raw["local_instance_id"])
        public_type = types.get(raw["public_type_id"], {})
        kind = public_type.get("entity_type")
        if kind not in {"light_cone", "relic"}:
            diagnostics.append({"local_instance_id": raw["local_instance_id"], "reason": "unresolved_public_equipment_kind"})
            continue
        if raw["identity"] == "source_confirmed":
            diagnostics.append({"local_instance_id": raw["local_instance_id"], "reason": "source_confirmed_is_not_source_verified"})
        items.append({
            "local_instance_id": raw["local_instance_id"], "public_type_id": raw["public_type_id"],
            "kind": kind, "slot": raw["slot"], "identity_state": IDENTITIES[raw["identity"]],
            "equipped_by": raw["owner_character_id"],
            "fields": {attribute: _field(field, f"equipment/{raw['local_instance_id']}/{attribute}", diagnostics) for attribute, field in raw["facts"].items()},
        })
    proof.update(snapshot_id=snapshot["snapshot_id"], snapshot_revision=snapshot["revision"], generated_at=snapshot["generated_at"], original_coverage=snapshot["coverage"], authorization_basis="separate caller context; not serialized in B snapshot")
    normalized = {
        "schema_id": "AccountSnapshot", "schema_version": "0.1-draft",
        "profile_id": snapshot["profile_id"], "snapshot_id": snapshot["snapshot_id"], "snapshot_revision": snapshot["revision"],
        "authorization_state": "active", "authorization_generation": authorization["generation"],
        "characters": list(characters.values()), "equipment_instances": items,
        "coverage": {"roster": "partial", "inventory": "partial", "materials": "unknown"},
    }
    return normalized, proof, diagnostics
