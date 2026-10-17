# Supplemental B desktop bridge evidence

Date: 2026-10-17. Synthetic inputs only. This supplements C's producer replay;
it does not replace the fixed B snapshot producer or establish full M0/MVP acceptance.

## Pinned identities

| Role | Identity |
|---|---|
| B bridge/worker host code | `86fafdddb9183c42408d8c6e71d8ce5de65c4ff3` |
| B original snapshot producer | `045965bce4fbc38a3baa79b594535c9dd983d776` |
| A producer code / delivery | `00d4a5844e74050359227c274de712878bf9187c` / `31e2665cfb9ce1100856d72ebca086b39a603ee8` |
| C wheel / native rules | `0.3.0` / `0.2.0` |
| C wheel SHA-256 | `f7b6c5c221e2491c9399ed76656945175961ac94188b11ad2fe4d4160d0aa0ca` |

The host commit is a separately versioned consumer of C's delivered artifact. The
snapshot descriptor continues to identify its actual fixed `045965b` producer;
the replay neither relabels a newer serializer nor changes an original payload.
The copied B host's 35 committed files are checked against immutable Git blobs
before and after execution. Its vendored C wheel is byte-identical to C's delivery.

## Actual path and results

The replay uses B's actual `BundleValidator` and `Ed25519Keyring`, activates and
reloads B's public cache, then calls its actual `LocalPlannerProcess` and worker.
The original signed A bytes survive cache activation/reload unchanged. Synthetic
authorization uses B's real lifecycle gate. An isolated store rejects any account
read/write attempt; no real account store or DPAPI protector is opened.

[Fixed-source machine report](../interop/reports/c-0.3.0-b-86fafdd-source-bridge.json):
**8 passed, 1 failed**, all request objects unchanged, account persistence calls zero.

| Case | Result |
|---|---|
| Main and complete alternate available | Passed |
| Fix character c: complete alternate only | Passed |
| No matching public goal: references, no plans | Passed |
| Missing fields retain unknown conditions | Passed |
| Corrupted transport retains original expected hash | Passed; explicit adapter refusal |
| Different request ID | Passed; worker/bridge refusal |
| Different snapshot revision | Passed; worker/bridge refusal |
| Different producer authorization generation | Passed; worker/bridge refusal |
| Latest-known withdrawn evidence | **Failed structured-error delivery** |

### Withdrawn-evidence failure

The worker exits successfully and returns native `error.code =
withdrawn_public_object`, with zero available plans and the correct request ID.
Its response lacks `snapshot_revision` and `authorization_generation`. B's bridge
therefore raises `PlannerUnavailable` with the static message
`local planner result belongs to a different account snapshot`. The intended
domain error does not reach the bridge caller.

This does not allow a withdrawn plan to execute. It is a real loss of structured
error semantics at the desktop boundary. The diagnostic direct-worker call is
recorded separately and never turns the failing bridge case into a passing one.

Minimal B-side requirement: after its wrapper has validated the producer request,
retain that validated request/snapshot/generation context for **all** responses,
including nested native errors. Preserve the original error code and empty plans.
Refuse contradictory declared correlation fields; do not weaken the bridge's
generation checks or fabricate a successful analysis. C's native 0.2 error and
rule behavior remain unchanged. B owns this wrapper; C has not edited B.

### Delivered executable observation

An earlier replay also exercised the delivered Windows worker: **8 passed, 1
failed**, with the same withdrawn-evidence diagnostic. Combined source/executable
observations are in [the earlier machine report](../interop/reports/c-0.3.0-b-86fafdd-bridge.json).
Its candidate manifest SHA-256 was
`34166dd07074293f3c1a8f5d9993f9151cde19672ea6a0543fa061ab90f9b00a`, with
827 files verified before and after execution; worker SHA-256 was
`ce4e65bed5827243d8a036d7a5be07451e81fba8fa0f00d1a9025176778cf11c`.

B subsequently replaced that candidate at the same local path. The new candidate
was refused under the old manifest pin. The earlier observations retain their
own hashes and are not attributed to the replacement. Executable build-source
attestation and publisher trust are not established by this local file manifest.
The immutable-source replay above is the current reproducible evidence.

## Reproduce from C's package directory

Use the existing C-only `cryptography 46.0.7` dependency target. Extraction refuses
to overwrite a directory; choose a new component-local destination when necessary.

```powershell
$TaskPython = 'C:\Users\admin\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $TaskPython -I -B tools/extract_fixed_source.py --repository 'C:/Users/admin/Documents/ChatGPT/星铁/parallel/desktop-account' --commit 86fafdddb9183c42408d8c6e71d8ce5de65c4ff3 --package-subdir packages/starhelp-desktop --destination .tmp/reproduced-b-86fafdd
& $TaskPython -I -B tools/replay_b_bridge.py --b-repository 'C:/Users/admin/Documents/ChatGPT/星铁/parallel/desktop-account' --b-source .tmp/reproduced-b-86fafdd/packages/starhelp-desktop --dependency-root .tmp/interop-deps --capture-dir interop/a-00d4a58 --b-cases interop/b-045965b-cases --wheel artifacts/starhelp_planner-0.3.0-py3-none-any.whl --report interop/reports/reproduced-b-86fafdd-source-bridge.json
```

The replay currently exits **1** because the withdrawn-evidence bridge case fails.
An optional `--candidate <retained-candidate-root>` requires a matching explicit
`--candidate-manifest-sha256 <pinned-sha256>`; a changed manifest or file set is
refused before that executable runs.

## Remaining gates

The B error-context issue, A's missing three-mode/equipment fixtures, agreed M0
semantics, real source/content approval and production TaskPage request building
remain open. Positive synthetic subprocess loading is now demonstrated; full
desktop or producer interoperability is not claimed. The original 62 C component
tests and 12-pass/3-unexercised producer replay remain separate evidence.
