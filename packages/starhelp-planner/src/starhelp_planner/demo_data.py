"""Synthetic, explicitly unapproved example data for the local demo and tests."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .validation import refresh_fixture_members


def synthetic_request() -> dict[str, Any]:
    """Return a complete but fictional request; it is not game or approved content."""
    entities = [
        {"id": entity_id, "revision": 1, "entity_type": "character", "name": entity_id}
        for entity_id in ("fixture:char:a", "fixture:char:b", "fixture:char:c")
    ]
    entities.extend({"id": identifier, "revision": 1, "entity_type": kind} for identifier, kind in (("fixture:relic:type", "relic"), ("fixture:material:1", "material")))
    stage = {
        "stage_id": "fixture:stage:1",
        "revision": 1,
        "scope": {
            "game_version": "fixture:game:v1",
            "environment": "fixture:environment",
            "mode_id": "fixture:mode:alpha",
            "cycle_id": "fixture:cycle:1",
            "stage_id": "fixture:stage:1",
            "stage_revision": 1,
        },
        "partitions": [
            {"partition_id": "fixture:upper", "slots": [{"slot_id": "fixture:upper:1"}]},
            {"partition_id": "fixture:lower", "slots": [{"slot_id": "fixture:lower:1"}]},
        ],
        "resource_reuse": {"characters": "exclusive", "equipment": "exclusive"},
        "evidence_refs": [{"id": "fixture:evidence:1", "revision": 1}],
    }
    template = {
        "id": "fixture:template:1", "revision": 1, "title": "Synthetic complete template",
        "approval_status": "approved", "publication_status": "published",
        "stage_ids": [stage["stage_id"]], "scope": dict(stage["scope"]),
        "public_goals": [{"kind": "fixture:goal:clear"}],
    }
    condition = {
        "condition_id": "fixture:condition:speed", "subject": {"kind": "team_slot", "slot_id": "fixture:upper:1"},
        "attribute": "fixture:stat:speed", "operator": "gte", "value": 100, "unit": "fixture:flat",
        "measurement_context": {"phase": "fixture:pre_battle", "assumptions": []},
        "requirement": "hard", "evidence_status": "confirmed",
        "evidence_refs": [{"id": "fixture:evidence:1", "revision": 1}],
    }
    main = {
        "id": "fixture:variant:main", "revision": 1, "template_id": template["id"], "title": "Synthetic main",
        "approval_status": "approved", "publication_status": "published", "variant_kind": "main",
        "evidence_refs": [{"id": "fixture:evidence:1", "revision": 1}],
        "teams": {
            "fixture:upper": [{
                "slot_id": "fixture:upper:1", "character_id": "fixture:char:a",
                "equipment_requirements": [{"kind": "relic", "slot": "body", "public_type_id": "fixture:relic:type"}],
                "evidence_refs": [{"id": "fixture:evidence:1", "revision": 1}],
            }],
            "fixture:lower": [{"slot_id": "fixture:lower:1", "character_id": "fixture:char:b"}],
        },
        "conditions": [condition],
        "steps": [
            {"order": 1, "text": "Synthetic opening step", "evidence_refs": [{"id": "fixture:evidence:1", "revision": 1}]},
            {"order": 2, "text": "Synthetic follow-up step", "evidence_refs": [{"id": "fixture:evidence:1", "revision": 1}]},
        ],
        "mechanics": [{"text": "Synthetic mechanic only", "evidence_refs": [{"id": "fixture:evidence:1", "revision": 1}]}],
        "failure_conditions": [{"text": "Synthetic failure condition only", "evidence_refs": [{"id": "fixture:evidence:1", "revision": 1}]}],
        "risks": [{"text": "Synthetic risk only", "evidence_refs": [{"id": "fixture:evidence:1", "revision": 1}]}],
        "cultivation_requirements": [{
            "requirement_id": "fixture:cultivation:level", "subject": {"kind": "character", "character_id": "fixture:char:a"},
            "current_field": "fixture:level", "category": "character", "target_value": 15,
            "unit": "level", "measurement_context": {"phase": "progression", "assumptions": []},
            "priority": 1, "reason": "synthetic target only", "evidence_refs": [{"id": "fixture:evidence:1", "revision": 1}],
            "cost_rule": {
                "id": "fixture:cost:character-level", "revision": 1, "category": "character",
                "scope": {"game_version": "fixture:game:v1", "environment": "fixture:environment"},
                "subject_entity_id": "fixture:char:a", "attribute": "fixture:level", "unit": "level",
                "evidence_refs": [{"id": "fixture:evidence:1", "revision": 1}],
                "transitions": [{"from": level, "to": level + 1, "materials": [{"material_id": "fixture:material:1", "amount": 2}]} for level in range(10, 15)],
            },
        }],
    }
    alternative = {
        "id": "fixture:variant:alternate", "revision": 1, "template_id": template["id"], "title": "Synthetic alternate",
        "approval_status": "approved", "publication_status": "published", "variant_kind": "complete_alternate",
        "evidence_refs": [{"id": "fixture:evidence:1", "revision": 1}],
        "teams": {
            "fixture:upper": [{"slot_id": "fixture:upper:1", "character_id": "fixture:char:c"}],
            "fixture:lower": [{"slot_id": "fixture:lower:1", "character_id": "fixture:char:b"}],
        },
        "conditions": [],
    }
    evidence = {
        "id": "fixture:evidence:1", "revision": 1, "title": "Synthetic evidence",
        "source_url": "https://example.invalid/fixture", "locator": "synthetic-only",
        "excerpt": "Synthetic fixture, not game evidence.", "status": "confirmed",
    }
    troubleshooting = {
        "id": "fixture:troubleshooting:1", "revision": 1, "approval_status": "approved", "publication_status": "published",
        "scope": dict(stage["scope"]), "stage_ids": [stage["stage_id"]],
        "trigger_conditions": [{
            "condition_id": "fixture:failure-kind", "subject": {"kind": "feedback"}, "attribute": "fixture:failure_kind",
            "operator": "eq", "value": "fixture:survival", "unit": "fixture:label",
            "measurement_context": {"phase": "fixture:reported", "assumptions": []}, "requirement": "hard", "evidence_status": "confirmed",
            "evidence_refs": [{"id": "fixture:evidence:1", "revision": 1}],
        }],
        "suggested_variant_id": alternative["id"], "evidence_refs": [{"id": "fixture:evidence:1", "revision": 1}],
    }
    bundle = {
        "adapter_profile": "starhelp.local.v0.2",
        "contract_version": "0.1-draft", "schema_id": "PublicBundle", "schema_version": "0.1-draft",
        "manifest": {
            "index_release_id": "fixture:release:1", "required_capabilities": ["starhelp.local-profile.v0.2"],
            "object_schemas": {k: "0.1-draft" for k in ("stage", "entity", "template", "variant", "evidence", "troubleshooting")},
            "coverage": {"status": "synthetic", "reason": "fixture-only"},
            "attribute_definitions": {
                "fixture:stat:speed": {"value_type": "number", "unit": "fixture:flat", "phases": ["fixture:pre_battle"], "loadout_dependent": True},
                "fixture:level": {"value_type": "integer", "unit": "level", "phases": ["progression"], "loadout_dependent": False},
                "fixture:failure_kind": {"value_type": "string", "unit": "fixture:label", "phases": ["fixture:reported"], "loadout_dependent": False},
                "fixture:item:stat": {"value_type": "number", "unit": "fixture:flat", "phases": ["item"], "loadout_dependent": False},
            },
            "members": [],
        },
        "entities": entities, "stages": [stage], "templates": [template], "variants": [main, alternative],
        "evidence": [evidence], "troubleshooting": [troubleshooting],
    }
    refresh_fixture_members(bundle, rebuild=True)
    snapshot = {
        "schema_id": "AccountSnapshot", "schema_version": "0.1-draft",
        "profile_id": "fixture:local-profile:1", "snapshot_id": "fixture:local-snapshot:1", "snapshot_revision": 1,
        "authorization_generation": 7, "authorization_state": "active",
        "coverage": {"roster": "complete", "inventory": "complete", "materials": "complete"},
        "characters": [
            {"entity_id": "fixture:char:a", "ownership": "owned", "fields": {
                "fixture:stat:speed": {"value": 105, "state": "confirmed", "unit": "fixture:flat", "measurement_context": {"phase": "fixture:pre_battle", "assumptions": []}, "observed_at": "2026-10-15T00:00:00Z"},
                "fixture:level": {"value": 10, "state": "confirmed", "unit": "level", "measurement_context": {"phase": "progression", "assumptions": []}},
            }},
            {"entity_id": "fixture:char:b", "ownership": "owned", "fields": {}},
            {"entity_id": "fixture:char:c", "ownership": "owned", "fields": {}},
        ],
        "equipment_instances": [{
            "local_instance_id": "fixture:gear:1", "public_type_id": "fixture:relic:type", "kind": "relic", "slot": "body",
            "identity_state": "player_confirmed", "equipped_by": "fixture:char:a",
        }],
        "materials": [{"material_id": "fixture:material:1", "count": 5, "state": "confirmed", "unit": "item_count", "measurement_context": {"phase": "inventory", "assumptions": []}}],
    }
    request = {
        "adapter_profile": "starhelp.local.v0.2",
        "contract_version": "0.1-draft", "schema_id": "AnalysisRequest", "schema_version": "0.1-draft",
        "request_id": "fixture:request:1", "authorization_generation": 7, "public_bundle": bundle,
        "evaluation_time": "2026-10-15T01:00:00Z",
        "account_snapshot": snapshot,
        "task": {
            "scope": dict(stage["scope"]), "public_goal": {"kind": "fixture:goal:clear"},
            "fixed_character_ids": [], "excluded_character_ids": [], "locked_local_instance_ids": [],
            "allow_rearrangement": True,
        },
        "latest_known_validity": {"withdrawn_public_refs": [], "checked_at": "2026-10-15T00:00:00Z", "online_confirmation_available": False},
        "feedback": None,
    }
    return request


def fresh_synthetic_request() -> dict[str, Any]:
    """A deep-copy helper so examples can be safely modified by a caller."""
    return deepcopy(synthetic_request())
