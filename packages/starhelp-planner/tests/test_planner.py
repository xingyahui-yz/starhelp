from __future__ import annotations

import ast
from pathlib import Path

from starhelp_planner import analyze as analyze_raw
from starhelp_planner.validation import refresh_fixture_members


def analyze(request):
    # Semantic cases explicitly republish their synthetic objects. Integrity cases use analyze_raw.
    refresh_fixture_members(request["public_bundle"])
    return analyze_raw(request)
from starhelp_planner.demo_data import fresh_synthetic_request


def test_complete_reviewed_variant_returns_current_plan_and_citations() -> None:
    request = fresh_synthetic_request()
    result = analyze(request)

    assert result["status"] == "plans_available"
    main = next(p for p in result["current_equipment_plans"] if p["variant"]["id"] == "fixture:variant:main")
    assert main["condition_results"][0]["match_status"] == "satisfied"
    assert main["evidence_refs"] == [{"id": "fixture:evidence:1", "revision": 1}]
    assert result["citations"][0]["id"] == "fixture:evidence:1"
    assert main["ranking"]["meaning"] == "仅用于适配顺序，不是通关概率"
    assert [step["order"] for step in main["strategy"]["steps"]] == [1, 2]
    assert all(main["strategy"][key] for key in ("mechanics", "failure_conditions", "risks"))


def test_rearrangement_plan_reports_actual_moves_and_respects_allow_flag() -> None:
    request = fresh_synthetic_request()
    use_level_condition(request)
    request["account_snapshot"]["equipment_instances"][0]["equipped_by"] = "fixture:char:b"
    result = analyze(request)

    plan = next(p for p in result["rearrangement_plans"] if p["variant"]["id"] == "fixture:variant:main")
    assert plan["equipment"]["actions"] == [{
        "local_instance_id": "fixture:gear:1", "from_character_id": "fixture:char:b", "to_character_id": "fixture:char:a"
    }]
    assert "fixture:variant:main" not in [p["variant"]["id"] for p in result["current_equipment_plans"]]

    request["task"]["allow_rearrangement"] = False
    result = analyze(request)
    assert "fixture:variant:main" not in [p["variant"]["id"] for p in result["rearrangement_plans"]]


def test_allocator_uses_a_consistent_minimum_move_mapping_for_multiple_slots() -> None:
    request = fresh_synthetic_request()
    use_level_condition(request)
    request["public_bundle"]["stages"][0]["partitions"][1]["slots"].append({"slot_id": "fixture:lower:2"})
    request["public_bundle"]["variants"][0]["teams"]["fixture:lower"].append({
        "slot_id": "fixture:lower:2", "character_id": "fixture:char:c",
        "equipment_requirements": [{"kind": "relic", "slot": "body", "public_type_id": "fixture:relic:type"}],
    })
    request["public_bundle"]["variants"][0]["teams"]["fixture:upper"][0]["equipment_requirements"] = [
        {"kind": "relic", "slot": "body", "public_type_id": "fixture:relic:type"}
    ]
    request["account_snapshot"]["equipment_instances"] = [
        {"local_instance_id": "fixture:gear:2", "public_type_id": "fixture:relic:type", "kind": "relic", "slot": "body", "identity_state": "player_confirmed", "equipped_by": "fixture:char:b"},
        {"local_instance_id": "fixture:gear:1", "public_type_id": "fixture:relic:type", "kind": "relic", "slot": "body", "identity_state": "player_confirmed", "equipped_by": "fixture:char:c"},
        {"local_instance_id": "fixture:gear:old", "public_type_id": "fixture:other:type", "kind": "relic", "slot": "body", "identity_state": "player_confirmed", "equipped_by": "fixture:char:a"},
    ]

    result = analyze(request)

    plan = next(p for p in result["rearrangement_plans"] if p["variant"]["id"] == "fixture:variant:main")
    assert len(plan["equipment"]["actions"]) == 2
    assert any(action["local_instance_id"] == "fixture:gear:2" and action["to_character_id"] == "fixture:char:a" for action in plan["equipment"]["actions"])
    assert any(action.get("action") == "unequip" and action["local_instance_id"] == "fixture:gear:old" for action in plan["equipment"]["actions"])


def test_hard_unknown_condition_is_pending_not_satisfied() -> None:
    request = fresh_synthetic_request()
    request["account_snapshot"]["characters"][0]["fields"]["fixture:stat:speed"]["state"] = "stale"

    result = analyze(request)

    assert "fixture:variant:main" not in [p["variant"]["id"] for p in result["current_equipment_plans"]]
    candidate = next(p for p in result["pending_confirmation_candidates"] if p["variant"]["id"] == "fixture:variant:main")
    assert candidate["condition_results"][0]["match_status"] == "unknown"
    assert candidate["condition_results"][0]["reason_code"] == "stale_field"


def test_hard_condition_failure_rejects_variant_while_evidence_status_stays_separate() -> None:
    request = fresh_synthetic_request()
    request["account_snapshot"]["characters"][0]["fields"]["fixture:stat:speed"]["value"] = 80
    result = analyze(request)
    rejected = {entry["variant_id"]: entry for entry in result["rejected_variants"]}
    assert rejected["fixture:variant:main"]["code"] == "hard_condition_failed"

    request = fresh_synthetic_request()
    request["public_bundle"]["variants"][0]["conditions"][0]["evidence_status"] = "suggested"
    result = analyze(request)
    condition = next(p for p in result["current_equipment_plans"] if p["variant"]["id"] == "fixture:variant:main")["condition_results"][0]
    assert condition["evidence_status"] == "suggested"
    assert condition["match_status"] == "satisfied"


def test_condition_comparison_does_not_treat_boolean_as_numeric() -> None:
    request = fresh_synthetic_request()
    request["account_snapshot"]["characters"][0]["fields"]["fixture:stat:speed"]["value"] = 1
    condition = request["public_bundle"]["variants"][0]["conditions"][0]
    condition["operator"] = "eq"
    condition["value"] = True

    result = analyze(request)

    rejected = {entry["variant_id"]: entry for entry in result["rejected_variants"]}
    assert rejected["fixture:variant:main"]["code"] == "invalid_variant"


def test_unknown_ownership_only_enters_pending_candidate() -> None:
    request = fresh_synthetic_request()
    request["account_snapshot"]["characters"][2]["ownership"] = "unknown"

    result = analyze(request)

    assert "fixture:variant:alternate" not in [p["variant"]["id"] for p in result["current_equipment_plans"]]
    assert "fixture:variant:alternate" in [p["variant"]["id"] for p in result["pending_confirmation_candidates"]]


def test_unobserved_character_in_partial_roster_is_pending_not_not_owned() -> None:
    request = fresh_synthetic_request()
    request["account_snapshot"]["coverage"]["roster"] = "partial"
    request["account_snapshot"]["characters"] = request["account_snapshot"]["characters"][:1]

    result = analyze(request)

    assert not result["current_equipment_plans"]
    reasons = [reason for c in result["pending_confirmation_candidates"] for reason in c["pending_reasons"]]
    assert any(reason.get("reason") == "character_not_observed_in_partial_roster" for reason in reasons)


def test_confirmed_not_owned_role_and_fixed_character_conflict_are_rejected() -> None:
    request = fresh_synthetic_request()
    request["account_snapshot"]["characters"][0]["ownership"] = "not_owned"
    request["task"]["fixed_character_ids"] = ["fixture:char:a"]

    result = analyze(request)

    rejected = {entry["variant_id"]: entry for entry in result["rejected_variants"]}
    assert rejected["fixture:variant:main"]["code"] == "hard_constraint_conflict"
    assert "fixture:variant:main" not in [p["variant"]["id"] for p in result["current_equipment_plans"]]


def test_locked_equipment_is_never_moved_to_another_character() -> None:
    request = fresh_synthetic_request()
    request["account_snapshot"]["equipment_instances"][0]["equipped_by"] = "fixture:char:b"
    request["task"]["locked_local_instance_ids"] = ["fixture:gear:1"]

    result = analyze(request)

    rejected = {entry["variant_id"]: entry for entry in result["rejected_variants"]}
    assert rejected["fixture:variant:main"]["code"] == "equipment_conflict"
    assert result["rearrangement_plans"] == []


def test_rearrangement_does_not_displace_ambiguous_or_locked_occupant() -> None:
    request = fresh_synthetic_request()
    request["account_snapshot"]["equipment_instances"] = [
        {"local_instance_id": "fixture:gear:old", "public_type_id": "fixture:other:type", "kind": "relic", "slot": "body", "identity_state": "ambiguous", "equipped_by": "fixture:char:a"},
        {"local_instance_id": "fixture:gear:new", "public_type_id": "fixture:relic:type", "kind": "relic", "slot": "body", "identity_state": "player_confirmed", "equipped_by": "fixture:char:b"},
    ]

    result = analyze(request)

    rejected = {entry["variant_id"]: entry for entry in result["rejected_variants"]}
    assert rejected["fixture:variant:main"]["code"] == "equipment_conflict"
    assert not result["rearrangement_plans"]


def test_ambiguous_equipment_can_stay_current_but_cannot_be_used_for_rearrangement() -> None:
    request = fresh_synthetic_request()
    request["account_snapshot"]["equipment_instances"][0]["identity_state"] = "ambiguous"

    result = analyze(request)

    assert result["current_equipment_plans"]
    assert result["rearrangement_plans"] == []


def test_unreviewed_variant_is_not_used_or_composed_from_individual_alternatives() -> None:
    request = fresh_synthetic_request()
    request["public_bundle"]["variants"][1]["approval_status"] = "pending"

    result = analyze(request)

    result_variant_ids = {
        p["variant"]["id"] for p in result["current_equipment_plans"] + result["rearrangement_plans"]
    }
    assert "fixture:variant:alternate" not in result_variant_ids
    assert all({s["character_id"] for s in p["team"]} in (
        {"fixture:char:a", "fixture:char:b"}, {"fixture:char:c", "fixture:char:b"}
    ) for p in result["current_equipment_plans"] + result["rearrangement_plans"])


def test_variant_without_evidence_is_not_executable() -> None:
    request = fresh_synthetic_request()
    request["public_bundle"]["variants"][0]["evidence_refs"] = []
    request["public_bundle"]["variants"][0]["teams"]["fixture:upper"][0]["evidence_refs"] = []
    request["public_bundle"]["variants"][0]["conditions"][0]["evidence_refs"] = []
    request["public_bundle"]["variants"][0]["cultivation_requirements"][0]["evidence_refs"] = []
    request["public_bundle"]["variants"][0]["cultivation_requirements"][0]["cost_rule"]["evidence_refs"] = []
    for key in ("steps", "mechanics", "failure_conditions", "risks"):
        for item in request["public_bundle"]["variants"][0][key]:
            item["evidence_refs"] = []

    result = analyze(request)

    rejected = {entry["variant_id"]: entry for entry in result["rejected_variants"]}
    assert rejected["fixture:variant:main"]["code"] == "invalid_variant"


def test_material_cost_requires_complete_material_coverage() -> None:
    request = fresh_synthetic_request()
    result = analyze(request)
    plan = next(p for p in result["current_equipment_plans"] if p["variant"]["id"] == "fixture:variant:main")
    step = plan["cultivation"][0]
    assert step["gap"] == 5
    assert step["cost"]["status"] == "calculated"
    assert plan["cultivation_cost"]["materials"][0]["net_shortage"] == 5

    request["account_snapshot"]["coverage"]["materials"] = "partial"
    result = analyze(request)
    plan = next(p for p in result["current_equipment_plans"] if p["variant"]["id"] == "fixture:variant:main")
    step = plan["cultivation"][0]
    assert step["cost"]["status"] == "calculated"
    assert plan["cultivation_cost"]["net_status"] == "not_calculated"
    assert plan["cultivation_cost"]["materials"][0]["net_shortage"] is None


def test_supported_reviewed_feedback_rule_only_suggests_complete_published_variant() -> None:
    request = fresh_synthetic_request()
    request["feedback"] = {"fields": {"fixture:failure_kind": {"value": "fixture:survival", "state": "user_reported", "unit": "fixture:label", "measurement_context": {"phase": "fixture:reported", "assumptions": []}}}}

    result = analyze(request)

    assert result["troubleshooting"]["status"] == "suggestions_available"
    assert result["troubleshooting"]["suggestions"][0]["suggested_variant_id"] == "fixture:variant:alternate"


def test_troubleshooting_rule_cannot_cross_cycle_or_stage() -> None:
    request = fresh_synthetic_request()
    request["feedback"] = {"fields": {"fixture:failure_kind": {"value": "fixture:survival", "state": "user_reported", "unit": "fixture:label", "measurement_context": {"phase": "fixture:reported", "assumptions": []}}}}
    request["public_bundle"]["troubleshooting"][0]["scope"]["cycle_id"] = "fixture:cycle:other"

    result = analyze(request)

    assert result["troubleshooting"]["status"] == "unable_to_determine"
    assert result["troubleshooting"]["suggestions"] == []


def test_cross_scope_or_missing_bundle_member_fails_closed() -> None:
    request = fresh_synthetic_request()
    request["task"]["scope"]["cycle_id"] = "fixture:cycle:other"
    result = analyze(request)
    assert result["error"]["code"] == "scope_mismatch"

    request = fresh_synthetic_request()
    request["public_bundle"]["manifest"]["members"].pop()
    result = analyze(request)
    assert result["error"]["code"] == "invalid_public_bundle"


def test_no_reviewed_template_returns_public_material_and_stage_citation() -> None:
    request = fresh_synthetic_request()
    request["public_bundle"]["templates"] = []
    request["public_bundle"]["variants"] = []
    request["public_bundle"]["troubleshooting"] = []
    refresh_fixture_members(request["public_bundle"], rebuild=True)

    result = analyze(request)

    assert result["status"] == "no_reviewed_template"
    assert result["public_material"]["evidence_refs"] == [{"id": "fixture:evidence:1", "revision": 1}]
    assert result["citations"][0]["index_release_id"] == "fixture:release:1"


def test_partial_inventory_does_not_claim_no_matching_equipment_exists() -> None:
    request = fresh_synthetic_request()
    request["account_snapshot"]["equipment_instances"] = []
    request["account_snapshot"]["coverage"]["inventory"] = "partial"

    result = analyze(request)

    assert any(candidate.get("equipment_status") == "unknown" for candidate in result["pending_confirmation_candidates"])
    assert all(item["code"] != "equipment_conflict" for item in result["rejected_variants"])


def test_withdrawn_evidence_disables_variant() -> None:
    request = fresh_synthetic_request()
    request["latest_known_validity"]["withdrawn_public_refs"] = ["fixture:evidence:1"]

    result = analyze(request)

    assert result["error"]["code"] == "withdrawn_public_object"
    assert all(not plans for plans in (result["current_equipment_plans"], result["rearrangement_plans"]))


def test_withdrawal_is_revision_scoped_when_a_revision_is_supplied() -> None:
    request = fresh_synthetic_request()
    request["latest_known_validity"]["withdrawn_public_refs"] = [{"id": "fixture:evidence:1", "revision": 99}]
    result = analyze(request)
    assert "fixture:variant:main" in [p["variant"]["id"] for p in result["current_equipment_plans"]]

    request["latest_known_validity"]["withdrawn_public_refs"] = [{"id": "fixture:evidence:1", "revision": 1}]
    result = analyze(request)
    assert result["current_equipment_plans"] == []


def test_duplicate_local_instance_identity_fails_closed() -> None:
    request = fresh_synthetic_request()
    request["account_snapshot"]["equipment_instances"].append(dict(request["account_snapshot"]["equipment_instances"][0]))

    result = analyze(request)

    assert result["error"]["code"] == "snapshot_conflict"


def test_planner_package_has_no_network_gui_storage_or_game_input_dependencies() -> None:
    source_root = Path(__file__).parents[1] / "src" / "starhelp_planner"
    forbidden = {"socket", "http", "urllib", "requests", "aiohttp", "websockets", "tkinter", "PySide6", "PyQt6", "PyQt5", "sqlite3", "subprocess", "pyautogui", "pynput", "mss"}
    violations: list[str] = []
    for path in source_root.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                violations.extend(alias.name.split(".")[0] for alias in node.names if alias.name.split(".")[0] in forbidden)
            elif isinstance(node, ast.ImportFrom) and node.module:
                root = node.module.split(".")[0]
                if root in forbidden:
                    violations.append(root)
            elif isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in {"open", "urlopen"}:
                violations.append(node.func.id)

    assert not violations, f"planner source includes forbidden I/O dependencies: {violations}"


def use_level_condition(request):
    condition=request["public_bundle"]["variants"][0]["conditions"][0]
    condition.update(attribute="fixture:level", unit="level", value=10, measurement_context={"phase":"progression", "assumptions":[]})
