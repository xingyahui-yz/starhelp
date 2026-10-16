"""Capture actual fixed producer outputs; this tool is not part of the pure API."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

A_COMMIT = "313508f895cb422d4a309743eb7f8b99f45a7a91"
B_COMMIT = "045965bce4fbc38a3baa79b594535c9dd983d776"


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8", newline="\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--a-source", required=True, type=Path)
    parser.add_argument("--b-source", required=True, type=Path)
    parser.add_argument("--a-repository", required=True, type=Path)
    parser.add_argument("--b-repository", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    if not output.is_relative_to(root):
        raise SystemExit("capture output must stay inside this C package")
    output.mkdir(parents=True, exist_ok=True)
    if (output / "producer-locks.json").exists():
        raise SystemExit("capture is already locked; use a new output directory")
    sys.dont_write_bytecode = True
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    a_root, b_root = args.a_source.resolve(), args.b_source.resolve()
    from check_producer_source import check_source
    source_proofs = {
        "a": check_source(args.a_repository, A_COMMIT, "packages/starhelp-knowledge", a_root),
        "b": check_source(args.b_repository, B_COMMIT, "packages/starhelp-desktop", b_root),
    }
    sys.path[:0] = [str(a_root / "src"), str(a_root / "tests"), str(b_root / "src")]
    from test_public_pipeline import PublicPipelineTests, PUBLISHER
    from starhelp_knowledge.cli import main as a_cli
    from starhelp_knowledge.bundle import verify_public_bundle
    from starhelp_desktop.models import AccountSnapshot, FieldFact, FieldStatus, Ownership, SourceKind
    from starhelp_desktop.profiles import _snapshot_to_dict

    case = PublicPipelineTests("test_explicit_review_publication_and_release_scoped_complete_fetch")
    case.setUp()
    try:
        release = case.build_synthetic_release()
        release_id = release["index_release_id"]
        case.service.validate_release(PUBLISHER, release_id, idempotency_key="c-baseline-validate")
        case.service.activate_release(PUBLISHER, release_id, expected_active_release_id=None, idempotency_key="c-baseline-activate")
        a_file = output / "a-313508f-native-export.json"
        database = Path(case.tempdir.name) / "knowledge.sqlite3"
        assert a_cli(["export-bundle", "--database", str(database), "--release", release_id, "--output", str(a_file)]) == 0
        a_bundle = json.loads(a_file.read_bytes())
        original_content_hash = verify_public_bundle(a_bundle)
    finally:
        case.tearDown()

    time = datetime(2026, 10, 16, 0, 0, tzinfo=UTC)
    character_ids = [item["id"] for item in a_bundle["records"]["entity"] if item["payload"]["entity_type"] == "character"]
    snapshot = AccountSnapshot(
        profile_id=UUID("00000000-0000-4000-8000-000000000001"),
        snapshot_id=UUID("00000000-0000-4000-8000-000000000002"),
        revision=1, generated_at=time,
        ownership={identifier: Ownership.OWNED for identifier in character_ids},
        fields={f"character:{character_ids[0]}.stat:speed": FieldFact(105, FieldStatus.CONFIRMED, SourceKind.MANUAL, "fixture:manual", time, time, "synthetic-panel-with-unspecified-unit")},
        coverage=frozenset({f"ownership:{identifier}" for identifier in character_ids}),
    )
    b_file = output / "b-045965b-snapshot.json"
    write_json(b_file, _snapshot_to_dict(snapshot))
    # Caller authorization is intentionally separate from B's serialized payload.
    write_json(output / "caller-context.json", {"synthetic_only": True, "profile_id": str(snapshot.profile_id), "active": True, "generation": 7, "created_by": "C synthetic caller; not serialized by B"})
    metadata = {
        "synthetic_only": True,
        "a": {"commit": A_COMMIT, "entry_point": "starhelp_knowledge.cli.main export-bundle", "fixture_builder": "test_public_pipeline.PublicPipelineTests.build_synthetic_release", "release_id": release_id, "content_hash": original_content_hash, "raw_sha256": hashlib.sha256(a_file.read_bytes()).hexdigest(), "file": a_file.name},
        "b": {"commit": B_COMMIT, "entry_point": "starhelp_desktop.profiles._snapshot_to_dict", "raw_sha256": hashlib.sha256(b_file.read_bytes()).hexdigest(), "file": b_file.name},
        "source_files": {producer: {str(path.relative_to(source)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sorted(source.rglob("*.py"))} for producer, source in (("a", a_root), ("b", b_root))},
        "baseline_result": "capture only; not positive interoperability acceptance",
        "source_proofs": source_proofs,
    }
    write_json(output / "producer-locks.json", metadata)
    print(json.dumps({"a_release": release_id, "a_raw_sha256": metadata["a"]["raw_sha256"], "b_raw_sha256": metadata["b"]["raw_sha256"]}))


if __name__ == "__main__":
    main()
