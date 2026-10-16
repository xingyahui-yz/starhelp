"""Read-only test harness for the pinned B snapshot serializer.

This module is only used by the explicit synthetic fixture command. It never
constructs a profile repository, opens B's encrypted store, calls a provider, or
uses a real account. It loads source files from the requested immutable Git
commit into a temporary directory under A's test workspace.
"""

from __future__ import annotations

from datetime import UTC, datetime
import importlib
import io
import json
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path
from typing import Any
from uuid import UUID

B_SNAPSHOT_COMMIT = "045965bce4fbc38a3baa79b594535c9dd983d776"
_B_ARCHIVE_PREFIX = "packages/starhelp-desktop/src/starhelp_desktop/"
_FIXTURE_TIME = datetime(2026, 10, 16, 0, 0, tzinfo=UTC)


def serialize_pinned_b_synthetic_snapshot(b_root: Path, *, temp_root: Path) -> dict[str, Any]:
    """Call B's `_snapshot_to_dict` from exactly the pinned commit on fixture data."""
    b_root = b_root.resolve()
    commit_result = subprocess.run(
        ["git", "rev-parse", f"{B_SNAPSHOT_COMMIT}^{{commit}}"],
        cwd=b_root,
        check=True,
        capture_output=True,
        text=True,
    )
    if commit_result.stdout.strip() != B_SNAPSHOT_COMMIT:
        raise ValueError("B snapshot source does not resolve to the pinned commit")
    archive = subprocess.run(
        [
            "git", "archive", "--format=tar", B_SNAPSHOT_COMMIT,
            "packages/starhelp-desktop/src/starhelp_desktop",
        ],
        cwd=b_root,
        check=True,
        capture_output=True,
    ).stdout
    with tempfile.TemporaryDirectory(prefix=".pinned-b-", dir=temp_root) as temp:
        source_root = Path(temp) / "packages" / "starhelp-desktop" / "src"
        expected_prefix = _B_ARCHIVE_PREFIX.rstrip("/")
        with tarfile.open(fileobj=io.BytesIO(archive), mode="r:") as bundle:
            for member in bundle.getmembers():
                member_name = member.name.rstrip("/")
                if member.isdir() and (expected_prefix.startswith(member_name + "/") or member_name == expected_prefix):
                    continue
                if not member_name.startswith(expected_prefix + "/"):
                    raise ValueError("pinned B source archive contains an unexpected path") from None
                relative = Path(member_name[len(expected_prefix) + 1 :])
                if not member.isfile() or relative.is_absolute() or ".." in relative.parts:
                    raise ValueError("pinned B source archive contains an unexpected member")
                source = bundle.extractfile(member)
                if source is None:
                    raise ValueError("pinned B source archive member could not be read")
                destination = source_root / "starhelp_desktop" / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(source.read())
        sys.path.insert(0, str(source_root))
        prior_modules = {name for name in sys.modules if name == "starhelp_desktop" or name.startswith("starhelp_desktop.")}
        for name in prior_modules:
            del sys.modules[name]
        try:
            models = importlib.import_module("starhelp_desktop.models")
            profiles = importlib.import_module("starhelp_desktop.profiles")
            profile_id = UUID("11111111-1111-4111-8111-111111111111")
            snapshot = models.AccountSnapshot(
                profile_id=profile_id,
                snapshot_id=UUID("22222222-2222-4222-8222-222222222222"),
                revision=4,
                generated_at=_FIXTURE_TIME,
                fields={},
                ownership={
                    "fixture:character:a": models.Ownership.OWNED,
                    "fixture:character:b": models.Ownership.OWNED,
                    "fixture:character:c": models.Ownership.OWNED,
                },
                equipment=(),
                coverage=frozenset({
                    "ownership:fixture:character:a",
                    "ownership:fixture:character:b",
                    "ownership:fixture:character:c",
                }),
            )
            serialized = profiles._snapshot_to_dict(snapshot)
            # Round-trip through JSON to match the serializer's public byte boundary.
            return json.loads(json.dumps(serialized, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
        finally:
            for name in [name for name in sys.modules if name == "starhelp_desktop" or name.startswith("starhelp_desktop.")]:
                del sys.modules[name]
            sys.path.remove(str(source_root))


def write_pinned_b_synthetic_snapshot(b_root: Path, *, temp_root: Path, output: Path) -> bytes:
    snapshot = serialize_pinned_b_synthetic_snapshot(b_root, temp_root=temp_root)
    body = json.dumps(snapshot, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8") + b"\n"
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_bytes(body)
    temporary.replace(output)
    return body
