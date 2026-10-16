"""Construct synthetic B models and call its pinned serializer, never its store."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from dataclasses import replace
from pathlib import Path
from uuid import UUID

B_COMMIT = "045965bce4fbc38a3baa79b594535c9dd983d776"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--b-source", required=True, type=Path)
    parser.add_argument("--b-repository", required=True, type=Path)
    parser.add_argument("--base", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--equipment-type", default="fixture:relic:type")
    parser.add_argument("--slot", default="relic:1")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if not output.is_relative_to(root):
        raise SystemExit("output must stay in C's package")
    output.mkdir(parents=True, exist_ok=True)
    if (output / "producer-locks.json").exists():
        raise SystemExit("capture is already locked; use a new output directory")
    from check_producer_source import check_source
    source_proof = check_source(args.b_repository, B_COMMIT, "packages/starhelp-desktop", args.b_source.resolve())
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(args.b_source.resolve() / "src"))
    from starhelp_desktop.models import EquipmentIdentity, EquipmentInstance, Ownership
    from starhelp_desktop.profiles import _snapshot_from_dict, _snapshot_to_dict

    base = _snapshot_from_dict(json.loads(args.base.read_bytes()))
    characters = list(base.ownership)
    instance = EquipmentInstance(UUID("00000000-0000-4000-8000-000000000010"), args.equipment_type, args.slot, EquipmentIdentity.PLAYER_CONFIRMED, characters[-1])
    cases = {
        "normal": base,
        "missing_fields": replace(base, fields={}),
        "unknown_ownership": replace(base, ownership={**base.ownership, characters[0]: Ownership.UNKNOWN}),
        "not_owned": replace(base, ownership={**base.ownership, characters[0]: Ownership.NOT_OWNED}),
        "ambiguous_equipment": replace(base, equipment=(replace(instance, identity=EquipmentIdentity.AMBIGUOUS),)),
        "source_confirmed_equipment": replace(base, equipment=(replace(instance, identity=EquipmentIdentity.SOURCE_CONFIRMED),)),
        "player_confirmed_equipment": replace(base, equipment=(instance,)),
        "zero_revision": replace(base, revision=0),
    }
    locks = {"synthetic_only": True, "producer_commit": B_COMMIT, "entry_point": "starhelp_desktop.profiles._snapshot_to_dict", "base_sha256": hashlib.sha256(args.base.read_bytes()).hexdigest(), "source_proof": source_proof, "cases": {}}
    for index, (name, snapshot) in enumerate(cases.items(), start=100):
        snapshot = replace(snapshot, snapshot_id=UUID(int=index))
        raw = (json.dumps(_snapshot_to_dict(snapshot), sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
        file = output / f"{name}.json"
        file.write_bytes(raw)
        locks["cases"][name] = {"file": file.name, "sha256": hashlib.sha256(raw).hexdigest()}
    (output / "producer-locks.json").write_text(json.dumps(locks, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"serialized_cases": len(cases), "producer_commit": B_COMMIT}))


if __name__ == "__main__":
    main()
