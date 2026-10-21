"""Capture B1's actual typed serializer and request builder, with fixed sources.

Only synthetic model inputs are used. No desktop store, account import, network,
GUI or worker is started. New A deliveries get a new output directory.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from copy import deepcopy
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parent))
from check_producer_source import check_source

B1 = "103741e02c90ac672017f783058bdd8dacae982e"
PROFILE = "starhelp.desktop.snapshot.interop-min.v0.1"


def encode(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"


def read_locked(root, name, expected):
    if Path(name).name != name:
        raise ValueError("locked filenames must stay in their directory")
    raw = (root / name).read_bytes()
    if hashlib.sha256(raw).hexdigest() != expected:
        raise ValueError("input raw bytes differ from the capture lock")
    return raw


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--b-repository", required=True, type=Path)
    parser.add_argument("--b-source", required=True, type=Path)
    parser.add_argument("--dependency-root", required=True, type=Path)
    parser.add_argument("--a-capture", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    source, output = args.b_source.resolve(), args.output.resolve()
    if not source.is_relative_to(root) or not output.is_relative_to(root) or output.exists():
        raise SystemExit("use a fixed source copy and a new output directory inside C")
    proof = check_source(args.b_repository, B1, "packages/starhelp-desktop", source)
    locks = json.loads((args.a_capture / "consumer-capture-locks.json").read_bytes())
    if locks.get("synthetic_only") is not True:
        raise SystemExit("only a locked synthetic A delivery may be used")
    a_raw = read_locked(args.a_capture, locks["a_artifact"], locks["a_raw_sha256"])
    key_raw = read_locked(args.a_capture, locks["fixture_public_key"], locks["files"][locks["fixture_public_key"]])
    base_raw = read_locked(args.a_capture, locks["b_snapshot"], locks["files"][locks["b_snapshot"]])
    sys.path[:0] = [str(source / "src"), str(args.dependency_root.resolve())]
    sys.dont_write_bytecode = True
    import cryptography
    from cryptography.hazmat.primitives import serialization
    from starhelp_desktop import models, profiles, producer_request
    from starhelp_desktop.bundles import BundleValidator, Ed25519Keyring

    loaded = {}
    for module in (models, profiles, producer_request):
        path = Path(module.__file__).resolve()
        if not path.is_relative_to(source):
            raise SystemExit("B module did not load from the fixed source copy")
        loaded[module.__name__] = {"path": path.relative_to(source).as_posix(), "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
    key = serialization.load_pem_public_key(key_raw).public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    validated = BundleValidator().validate(a_raw, supported_capabilities=frozenset({"starhelp.knowledge-distribution.v1", "starhelp.local-profile.v0.2"}), signature_verifier=Ed25519Keyring({locks["fixture_key_id"]: key}))
    public = validated.payload()
    view = public["objects"][f"planner-view:{validated.release_id}"]["bundle"]
    base = profiles._snapshot_from_dict(json.loads(base_raw))
    output.mkdir(parents=True)
    files, cases, rejected = {}, {}, {}

    def write(name, raw):
        (output / name).write_bytes(raw)
        files[name] = hashlib.sha256(raw).hexdigest()
        return name

    # This independent invocation is kept separate from every builder invocation.
    baseline = encode(profiles._snapshot_to_dict(base))
    write("baseline-b1-snapshot.json", baseline)
    for index, stage in enumerate(view["stages"]):
        template = next(item for item in view["templates"] if stage["stage_id"] in item["stage_ids"])
        task = producer_request.select_public_task(public, stage_id=stage["stage_id"], template_id=template["id"], goal_kind=template["public_goals"][0]["kind"], allow_rearrangement=True)
        characters = [item["id"] for item in view["entities"] if item["entity_type"] in {"character", "character_entity"}]
        ownership = {identifier: models.Ownership.OWNED for identifier in characters}
        snapshot = replace(base, snapshot_id=UUID(int=1000 + index), ownership=ownership)
        main = next(item for item in view["variants"] if item["template_id"] == template["id"] and item["variant_kind"] == "main")
        seats = [seat for team in main["teams"].values() for seat in team]
        first = seats[0]["character_id"]
        variants = [("normal", snapshot, task), ("missing_fields", replace(snapshot, fields={}), task), ("unknown_ownership", replace(snapshot, ownership={**ownership, first: models.Ownership.UNKNOWN}), task), ("not_owned", replace(snapshot, ownership={**ownership, first: models.Ownership.NOT_OWNED}), task)]
        if snapshot.fields:
            path = next(iter(snapshot.fields))
            variants.append(("conflicting_field", replace(snapshot, fields={**snapshot.fields, path: replace(snapshot.fields[path], status=models.FieldStatus.CONFLICT)}), task))
        if main.get("conditions"):
            condition = main["conditions"][0]
            subject = condition["subject"]
            character = subject.get("character_id")
            if subject.get("kind") == "team_slot":
                character = next(seat["character_id"] for seat in seats if seat["slot_id"] == subject["slot_id"])
            if character:
                value = condition["value"][0] if condition["operator"] == "in" else condition["value"]
                path = f"character:{character}.{condition['attribute']}"
                fact = models.FieldFact(value, models.FieldStatus.CONFIRMED, models.SourceKind.MANUAL, "fixture:S3-local-model-input", base.generated_at, base.generated_at, "synthetic-measurement-metadata-unavailable")
                variants.append(("confirmed_field_without_measurement", replace(snapshot, fields={path: fact}), task))
                variants.append(("conflicting_condition_field", replace(snapshot, fields={path: replace(fact, status=models.FieldStatus.CONFLICT)}), task))
        requirements = [(seat, requirement) for seat in seats for requirement in seat["equipment_requirements"]]
        if requirements:
            items = []
            for position, (seat, requirement) in enumerate(requirements):
                type_id = requirement.get("public_type_id") or requirement.get("public_type_ids", [None])[0]
                if type_id is None:
                    type_id = next(entity["id"] for entity in view["entities"] if entity["entity_type"] == requirement["kind"])
                items.append(models.EquipmentInstance(UUID(int=2000 + index * 100 + position), type_id, requirement["slot"], models.EquipmentIdentity.PLAYER_CONFIRMED, seat["character_id"]))
            snapshot = replace(snapshot, equipment=tuple(items))
            variants.append(("main_current_equipment", snapshot, task))
            target = requirements[0][0]["character_id"]
            donor = next(identifier for identifier in characters if identifier != target)
            moved = replace(snapshot, equipment=(replace(items[0], owner_character_id=donor), *items[1:]))
            move_task = {**task, "fixed_character_ids": [target]}
            variants.append(("player_confirmed_move", moved, move_task))
            variants.append(("locked_move", moved, {**move_task, "locked_local_instance_ids": [str(items[0].local_instance_id)]}))
            for label, identity in (("ambiguous_move", models.EquipmentIdentity.AMBIGUOUS), ("source_confirmed_move", models.EquipmentIdentity.SOURCE_CONFIRMED)):
                variants.append((label, replace(moved, equipment=(replace(moved.equipment[0], identity=identity), *moved.equipment[1:])), move_task))
            spare = replace(moved.equipment[0], local_instance_id=UUID(int=9000 + index), owner_character_id=None)
            variants.append(("same_type_distinct_instance", replace(moved, equipment=(*moved.equipment, spare)), {**move_task, "locked_local_instance_ids": [str(items[0].local_instance_id)]}))
        alternatives = [item for item in view["variants"] if item["template_id"] == template["id"] and item["variant_kind"] == "complete_alternate"]
        if alternatives:
            alternative = alternatives[0]
            alternate_seats = [seat for team in alternative["teams"].values() for seat in team]
            alternate_items = []
            for position, seat in enumerate(alternate_seats):
                for requirement in seat["equipment_requirements"]:
                    type_id = requirement.get("public_type_id") or requirement.get("public_type_ids", [None])[0]
                    if type_id is None:
                        type_id = next(entity["id"] for entity in view["entities"] if entity["entity_type"] == requirement["kind"])
                    alternate_items.append(models.EquipmentInstance(UUID(int=20000 + index * 100 + position * 10 + len(alternate_items)), type_id, requirement["slot"], models.EquipmentIdentity.PLAYER_CONFIRMED, seat["character_id"]))
            main_ids = {seat["character_id"] for seat in seats}
            alternate_ids = {seat["character_id"] for seat in alternate_seats}
            variants.append(("complete_alternate", replace(snapshot, equipment=tuple(alternate_items)), {**task, "excluded_character_ids": sorted(main_ids - alternate_ids)}))
        for name, model, selected_task in variants:
            label = f"stage-{index}-{name}"
            standalone = encode(profiles._snapshot_to_dict(model))
            wrapper = producer_request.build_producer_analysis_request(validated_bundle=validated, task=deepcopy(selected_task), snapshot=model, authorization_generation=7, distribution_trust_purpose="synthetic-test", distribution_public_keys={locks["fixture_key_id"]: key}, bundle_producer_commit=locks["a_producer_commit"], bundle_format_profile=locks["distribution_profile"], snapshot_producer_commit=B1, snapshot_format_profile=PROFILE, evaluation_time=datetime(2026, 10, 21, tzinfo=UTC), request_id=f"fixture:b1:{label}")
            actual = wrapper["producer_request"]["account_snapshot"]["raw_json"].encode("utf-8")
            if actual != standalone or wrapper["producer_request"]["account_snapshot"]["sha256"] != hashlib.sha256(actual).hexdigest():
                raise SystemExit("actual B builder encoding differs from independent B serialization")
            cases[label] = {"stage_id": stage["stage_id"], "mode_id": stage["scope"]["mode_id"], "snapshot": write(label + ".snapshot.json", actual), "wrapper": write(label + ".request.json", encode(wrapper)), "builder_bytes_equal_independent_serializer": True}
        for name, bad_snapshot, bad_task in (("zero_revision", replace(snapshot, revision=0), task), ("extra_scope_key", snapshot, {**task, "scope": {**task["scope"], "unknown": "value"}}), ("boolean_scope_revision", snapshot, {**task, "scope": {**task["scope"], "stage_revision": True}}), ("undeclared_goal", snapshot, {**task, "public_goal": {"kind": "fixture:undeclared"}})):
            try:
                producer_request.build_producer_analysis_request(validated_bundle=validated, task=bad_task, snapshot=bad_snapshot, authorization_generation=7, distribution_trust_purpose="synthetic-test", distribution_public_keys={locks["fixture_key_id"]: key}, bundle_producer_commit=locks["a_producer_commit"], bundle_format_profile=locks["distribution_profile"], snapshot_producer_commit=B1, snapshot_format_profile=PROFILE)
            except ValueError as exc:
                rejected[f"stage-{index}-{name}"] = {"actual_gate": "B1 request builder", "exception": type(exc).__name__, "message": str(exc), "C_reached": False}
            else:
                raise SystemExit("B1 accepted a deliberately malformed submission")
    after = check_source(args.b_repository, B1, "packages/starhelp-desktop", source)
    if after != proof:
        raise SystemExit("B source changed during capture")
    result = {"synthetic_only": True, "producer_commit": B1, "format_profile": PROFILE, "serializer_entry_point": "starhelp_desktop.profiles._snapshot_to_dict", "builder_entry_point": "starhelp_desktop.producer_request.build_producer_analysis_request", "encoding": {"ensure_ascii": False, "sort_keys": True, "separators": [",", ":"], "allow_nan": False, "trailing_newline": True}, "legacy_base_raw_sha256": hashlib.sha256(base_raw).hexdigest(), "baseline_b1_raw_sha256": hashlib.sha256(baseline).hexdigest(), "baseline_bytes_equal_legacy": baseline == base_raw, "a_producer_commit": locks["a_producer_commit"], "a_raw_sha256": locks["a_raw_sha256"], "a_release_id": validated.release_id, "loaded_modules": loaded, "dependency_versions": {"cryptography": cryptography.__version__}, "source_proof": proof, "source_verified_before_and_after": True, "files": files, "cases": cases, "builder_rejections": rejected, "equipment_positive_coverage_present": any(seat["equipment_requirements"] for item in view["variants"] for team in item["teams"].values() for seat in team), "full_three_party_acceptance": False}
    write("producer-locks.json", json.dumps(result, indent=2, sort_keys=True).encode("utf-8") + b"\n")
    print(json.dumps({"producer_commit": B1, "cases": len(cases), "builder_rejections": len(rejected), "equipment_positive_coverage_present": result["equipment_positive_coverage_present"], "source_files_verified": len(proof["file_sha256"])}))


if __name__ == "__main__":
    main()
