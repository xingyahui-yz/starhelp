# Producer adapter API v0.1

Status: round-2 implementation in progress. Native rules remain 0.2.0; final A commit/output acceptance is pending. Do not interpret the existence of this API as completed A/B/C interoperability.

## Separate versions and entry points

| Constant / interface | Meaning |
|---|---|
| `COMPONENT_VERSION` / wheel | `0.3.0`, includes the producer adapter |
| `PLANNER_VERSION` / native `analyze` | `0.2.0`, native rules and exact version pin retain their existing behavior |
| `ADAPTER_PROFILE` | Native `starhelp.local.v0.2` |
| `PRODUCER_ADAPTER_PROFILE` | New explicit `starhelp.producers.v0.1` |
| `analyze_producers(request)` | Validate original producer outputs, adapt, then invoke native rules |
| `prepare_producer_request(request)` | Same validation/adaptation; expose a distinct normalized request/provenance without running analysis |

The API is pure in memory. It reads no files, accesses no network/GUI/private store and does not call producer code. Test/capture/replay tools live outside the runtime package and perform explicit file operations on synthetic inputs only.

## Input envelope

```python
request = {
    "schema_id": "ProducerAnalysisRequest",
    "schema_version": "0.1",
    "adapter_profile": "starhelp.producers.v0.1",
    "request_id": "fixture:request",
    "public_bundle": {
        "producer": "starhelp_knowledge",
        "producer_commit": "<accepted fixed A commit>",
        "format_profile": "starhelp.b-publicbundle-envelope.v1",
        "expected_release_id": "<exact producer release>",
        "raw_json": "<original UTF-8 JSON text, including original line endings>",
        "sha256": "<pinned SHA-256 of those exact original bytes>",
    },
    "account_snapshot": {
        "producer": "starhelp_desktop",
        "producer_commit": "045965bce4fbc38a3baa79b594535c9dd983d776",
        "format_profile": "starhelp.desktop.snapshot.045965b",
        "raw_json": "<B serializer's original UTF-8 JSON text>",
        "sha256": "<pinned SHA-256 of those original bytes>",
    },
    "authorization_context": {
        "profile_id": "<matching B snapshot UUID>", "active": True, "generation": 7,
    },
    "distribution_trust": {
        "purpose": "synthetic-test",
        "public_keys": {"<pinned fixture signing key ID>": "<32-byte public key in hex>"},
    },
    "task": {"scope": {}, "public_goal": {}, "allow_rearrangement": False},
    "evaluation_time": "2026-10-16T00:10:00Z",
    "latest_known_validity": {"withdrawn_public_refs": []},
}
```

Placeholders are not executable production values. Task/constraints retain native 0.2 semantics. Authorization is separately supplied by B and must match the snapshot; it is not falsely attributed to the serializer. The optional current-task feedback remains local. Producer commit/profile and raw digest must be explicit; schema label `0.1-draft` alone never selects a mapping.

Use `Path(...).read_bytes().decode("utf-8")` in the external loader to preserve the raw text. Text-mode newline conversion changes byte hashes. `interop/**` is marked `-text` in the component's Git attributes so checkout does not rewrite captured producer bytes.

## Validation and conversion boundary

1. Validate materialized JSON shape/limits, original byte SHA-256 and duplicate-key/non-finite-number rejection.
2. Recognize the fixed producer/profile. The old A `313508f` native export is digest/closure checked and explicitly refused for missing executable semantics. A new executable commit is not accepted until its delivery is locked.
3. Verify the original Ed25519 manifest signature against the caller's separately pinned synthetic-test keyring; no `verified: true` shortcut or always-true verifier exists. The `producer-signature` extra supplies the cryptography implementation. Missing optional verification support fails closed. Production trust is not established by a fixture public key.
4. Verify original signed object membership/digests/references, original A release digest/closure, projected C member digests and the original review/publication ledger bound to exactly the same source identities, revisions and hashes.
5. Check explicit field mapping: public goal/stage seats, complete main/alternate teams, condition operator/value/unit/context, tactics/cultivation and evidence identities cannot change during adaptation. `ne` may map to typed `neq`; unsupported `not_in` and team-wide predicates are refused.
6. Build a separate consumption copy. Original entity/evidence scopes omitted from the A projection are retained from the verified native records; contradictory supplied scopes are rejected. Recompute only this new internal view's member digests, preserving declared dependencies. Original bytes, signatures, original member/release hashes and approval ledger remain unchanged and separately reported. Internal hashes are not producer signatures.
7. Adapt B's exact fixed serializer, preserving ownership, revisions, IDs, sources, field states and timestamps. Missing unit/context remains unknown. String scope is retained as producer metadata, not interpreted as a battle phase. Observed field paths never become complete coverage. `source_confirmed` is not silently upgraded to `source_verified`; unknown public item types cannot establish equipment kinds. Raw slot identity is retained.
8. Pass the normalized request to unchanged native rules. Unknown hard fields/ownership cannot enter available plans. Only supported full approved variants are considered.

## Output

`ProducerAnalysisResult` includes `component_version`, adapter profile, status, nested native `analysis`, original producer provenance and compatibility diagnostics. Original public member/evidence provenance, byte hashes, signature key purpose, review/publication source and internal normalization hashes remain distinguishable. A preparation result uses `status: ready` and exposes `native_request`; this is not a claim that the user's task has a feasible plan.

Adapter failures have `status: error`, `analysis: null`, and `{code, message, details, retryable: false}`. Codes include `unsupported_adapter_profile`, `unsupported_producer_version`, `producer_digest_mismatch`, `producer_integrity_failed`, `producer_dependency_missing`, `producer_semantics_missing`, `producer_provenance_mismatch`, `producer_approval_unproven`, `projection_semantics_mismatch`, `signature_trust_unavailable`, `unknown_signing_key`, `invalid_signature`, `signature_verification_unavailable`, `authorization_context_required`, and fixed-snapshot schema/ownership/revision errors. Native task errors remain inside `analysis.error`. No expected failure triggers repair, relabelling or rehashing of an original damaged input.

## Current evidence and outstanding acceptance

`interop/baseline/producer-locks.json` identifies actual A CLI output and B serializer output. The baseline A release contains no C-required seat/goal/registry/approval view, so it is not an executable interoperability sample. `tools/replay_baseline.py` reproduces the precise refusal and B measurement degradation. `tools/check_producer_source.py` compares temporary source copies against immutable Git objects before producer execution. Capture tools refuse to overwrite locked outputs.

A's new signed distribution is under development. Its final producer commit/profile/release/raw SHA, actual B verifier acceptance, installed-wheel positive main/alternate/no-match and remaining negative replays are not yet accepted. Shared M0, real source permissions, production signing trust, real accounts and complete MVP acceptance remain outside this technical round's completion claim.
