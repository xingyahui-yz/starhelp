# S3 implementation evidence

Date: 2026-10-21. Frozen technical scope: `starhelp.interop-min.v0.1`, raw SHA-256 `1e62607b9ab5af686f8d63ac067e8a061b0bb61064ffc09c3f58172c4cd31f7a`; reviewed semantic candidate `8116030eb600d58a091a52711b99d7788d45fed71fdbc1bfe02a01ca25233f68`. The shared MVP remains draft. This document records C implementation and observed gates, not production acceptance.

## Fixed C wheel and isolated replay

- Source commit: `f627590468154cc8622dad8647fefe9f6fd3c4ee`.
- Wheel: `artifacts/starhelp_planner-0.4.0-py3-none-any.whl`, 45,152 bytes, SHA-256 `3b5b8de8f2ef71cd07f1cfb7724cb0a1564f316860232b58728386d52c47aea2`.
- `artifacts/starhelp_planner-0.4.0.lock.json` fixes A/B1/C tuples, raw file hashes, dependency versions, report hashes and all 16 runtime Python file hashes. Every wheel runtime file was compared byte for byte with its exact source Git blob, and every isolated installed runtime file with the wheel.
- Installed suite: `interop/reports/c-0.4.0-installed-suite.json`: **88 passed, 0 failures/errors/skips**.
- New A/B1 installed replay: `c-0.4.0-b1-s3-installed.json`: **204 checks passed, 0 failed**, 21 actual requests, three modes, 12 separately recorded B1 builder refusals.
- Separate old A/B1 installed measurement replay: `c-0.4.0-b1-measurement-installed.json`: **78 checks passed, 0 failed**, seven actual requests, four B1 builder refusals. This does not relabel the old A release as new S3 data.

The wheel was built once with offline `pip wheel --no-deps --no-build-isolation` and installed with `pip install --no-index --no-deps --no-compile --target .tmp/installed-c-0.4.0-final`. An initial install used the sandbox OS temporary directory and failed with WinError 5; that process reached a terminal state before retry. Setting TEMP/TMP to C's existing `.tmp` directory resolved it. The final wheel was unchanged and was not rebuilt. No system permissions or external temporary files were modified.

Installed replay command (use a new report filename):

```powershell
python -I -B tools/replay_b1_capture.py --installed-root .tmp/installed-c-0.4.0-final --wheel artifacts/starhelp_planner-0.4.0-py3-none-any.whl --wheel-sha256 3b5b8de8f2ef71cd07f1cfb7724cb0a1564f316860232b58728386d52c47aea2 --source-commit f627590468154cc8622dad8647fefe9f6fd3c4ee --capture interop/b-103741e-s3-v1 --dependency-root .tmp/interop-deps --report '<new report path>'
```

The report leaves B2 host/worker and complete material/final-panel positive coverage unexercised. Its condition-free new-A statistical gap is covered only by the explicitly separate old-A measurement report. Full three-party/M0 acceptance remains false.

## Source changes for component 0.4.0

- Task scope requires exactly the six keys, five nonempty strings and a positive integer revision excluding bool. Public scope fields are type checked without rejecting unrelated producer metadata such as entity `release_status` or evidence `fixture_only`. Full goal matching compares canonical JSON values so Python's `True == 1` cannot accept a different goal.
- Every variant team slot explicitly declares its equipment array. Requirement keys are closed to kind, opaque slot, one mutually exclusive exact/list type restriction, and optional revisioned evidence metadata. Empty/null/malformed filters cannot become wildcards. Duplicate `(kind,slot)` seats are refused. Type references must close through the same release and match the public entity kind. No global slot enum or alias is introduced.
- Existing condition, ownership, resource allocation, final-panel and cultivation execution rules retain their meaning and version 0.2.0. Shape corrections intentionally change `validation.py` and matching/variant validation in `engine.py`; the historical claim that five native modules were byte-identical to 3133 applies only to the published 0.3.0 baseline.
- A admission is an explicit commit-to-package registry: the two retained old commits use package 0.2.0; new `dcb1e3ee220b85229bedc6c79d72ebe495825f37` uses package 0.3.0. Other source or documentation commits are not aliases.

Source suite: **88 tests passed, zero skipped**, with Python standard-library unittest plus the optional cryptography 46.0.7 dependency for signed-producer cases. This includes the retained 62 tests, 14 native frozen-boundary tests, 4 actual-B1 old-A tests and 8 new A/B1 tests. Native unit fixtures are explicitly synthetic; their publisher helper never edits producer captures or establishes A review approval.

## Actual new A delivery and S3 capture

Producer code `dcb1e3ee220b85229bedc6c79d72ebe495825f37`, package 0.3.0; artifact commit `4610573ee9720f2b5e4760a9336263362446b800`; release `rel_fixture_s3_0001`. C ran the actual `build-s3-interop-fixture` and independent `verify-distribution` commands from a detached source copy. All five regenerated files exactly match their artifact Git blobs. A's exporter itself reads Git status/HEAD, so an actual detached Git clone was required: sandbox MSYS IPC initially blocked local clone; a scoped approved local clone succeeded without network, A edits or system-setting changes. The entire A package was checked against immutable Git objects before and after execution.

| Raw artifact | SHA-256 |
|---|---|
| `starhelp-interop-min-v0.1-s3.bpublic.json` | `f777d05bdb269b2e92a612e4fc96a9ad076f9d5b2bc36760c34c1209ff323772` |
| `equipment-type-table.json` | `7ffda486ef1b00683d3b3279fb3f2bf802075c46a5f04dbe563fc60f6ed75380` |
| `fixture-ed25519-public.pem` | `7fe277b94d7e7d57dd3fceeaad77495fdff04861c02c3b1cc624c736aac8a29e` |
| A-supplied historical-045965b snapshot | `e7269a57b83e3145bd647262c4a88d1663718d4078c502f0cd4829108d9b3b58` |
| `SHA256SUMS.txt` | `1dd544e4974c38420cad1337ddcd365b59054f666eaf11bc404176fc9ea1188e` |

Locks: `interop/a-dcb1e3e-s3/consumer-capture-locks.json`. The finite table has exactly two tuples: light_cone / light_cone / fixture:s3:alpha:equipment:light-cone / light_cone and relic / body / fixture:s3:alpha:equipment:relic / relic. Tests check every restricted requirement against it and the same-release entities. Other slot strings are not inferred aliases.

`interop/b-103741e-s3-v1/` contains **21 actual B1 builder requests and serializer snapshots** for the fixed new A. **12 malformed submissions** stop at the B1 builder. Its lock separately records the original 045965b model-input bytes and actual B1 serializer/encoder source; the newly emitted snapshot is never labelled as old-045 producer output. The three modes are synthetic alpha/beta/gamma. Only alpha declares equipment constraints; all three modes have complete main/alternate cases and consumer no-template checks.

The final source replay `c-0.4.0-dev-b1-s3-source-v3.json` has **204 checks passed, 0 failed**. It explicitly asserts per-case expected status/complete variant identity, complete team membership, current main with zero moves, exclusive UUID allocation, ownership/hard restrictions, real move versus the same snapshot under lock, unlocked distinct-copy allocation, ambiguous/source-confirmed pending results and exact negative gates. The first 134-check report lacked several explicit acceptance predicates; it is preliminary. v2 retained two failed harness expectations for scope errors (expected native invalid_payload, observed adapter invalid_producer_payload). v3 fixes the expected layer to match the existing preparation boundary; runtime behavior was not relaxed.

Negative gate evidence is separated: original-byte tamper keeps its expected digest and stops at producer_digest_mismatch; unknown/wrong key stops at signature handling; requested release mismatch stops at producer_release_mismatch; withdrawal reaches native withdrawn_public_object. Missing signed native object uses a **separate C-constructed negative transport**, not A output: object omitted, signed manifest/member hashes untouched, fresh digest identifying that negative input, original capture/hash retained. It reaches producer_dependency_missing after signature verification. No signed artifact is repaired or approved. Consumer no-template tasks reach no_reviewed_template for each mode; B1 separately rejects those undeclared goals before C, so that result is not claimed as a normal desktop-selector submission.

The S3 A release has no statistical conditions. Separate actual B1/old-A capture `interop/b-103741e-legacy-a-v2/` adds real FieldFact confirmed/conflicting cases to the old A statistical rules. `c-0.4.0-dev-b1-measurement-source.json`: **78 checks passed, 0 failed**; missing unit and conflicting field remain unknown. This remains a separately pinned old-A evidence set. `b1-duplicate-instance-model-refusal.json` confirms actual B1 `AccountSnapshot.__post_init__` rejects duplicate UUIDs before serialization/C; native duplicate allocation/identity behavior is independently tested. It is not represented as serializer-produced malformed bytes.

## B1 source, encoder and builder

Admitted tuple: `103741e02c90ac672017f783058bdd8dacae982e` / `starhelp.desktop.snapshot.interop-min.v0.1`. The legacy `045965bce4fbc38a3baa79b594535c9dd983d776` / `starhelp.desktop.snapshot.045965b` tuple and raw files remain independent regressions. Metadata commit aef35e46 is not an alias for B1.

`interop/b-103741e-legacy-a-v1/producer-locks.json` records all 38 B1 package file hashes, immutable Git tree, actual imported models/profiles/producer_request module hashes, cryptography dependency version, every input/output raw hash and source verification before and after execution. The sources were extracted with `git archive` into C's ignored temporary directory and compared byte for byte with Git objects. The actual B1 builder was called; a second direct `_snapshot_to_dict` invocation independently proves its snapshot bytes. Sorted compact UTF-8 plus one LF is B1's encoder, distinct from the historical native-order compact encoding.

Four actual builder requests and snapshots were emitted using the retained A code 00d4a58 / artifact 31e2665. Four malformed submissions (revision zero, extra scope key, boolean scope revision, undeclared full goal) stop in the **B1 request builder**, before C. The normal B1 request produces the two complete old-A variants; unknown ownership leaves a pending main while the independent alternate remains available. This old A has one mode and no equipment entities/requirements: **no three-mode or equipment positive acceptance is claimed**. Equality of the baseline B1 bytes with an older fixture is compatibility evidence only; B1 provenance is established by the independently checked source tree and loaded modules.

Reproduce from the component directory with the bundled Python executable:

```powershell
python -I -B tools/extract_fixed_source.py --repository '<B repository>' --commit 103741e02c90ac672017f783058bdd8dacae982e --package-subdir packages/starhelp-desktop --destination .tmp/producer-snapshots/b-103741e
python -I -B tools/capture_b1_inputs.py --b-repository '<B repository>' --b-source .tmp/producer-snapshots/b-103741e/packages/starhelp-desktop --dependency-root .tmp/interop-deps --a-capture interop/a-00d4a58 --output '<new C capture directory>'
$env:PYTHONPATH='.tmp/interop-deps;src;tests'
python -B -m unittest discover -s tests -p 'test_*.py' -q
```

Each capture requires a new output directory; historical raw inputs are never overwritten. B's typed model also rejects duplicate instance UUIDs before serialization; a separately malformed transport test must report that distinction rather than call it actual serializer output.

## Minimal B1/B2 seam and remaining delivery

`tools/verify_b2_host.py` is prepared for an explicitly fixed B2 commit. It verifies the whole source copy, compares models/profiles/producer_request/bundles/storage bytes to the independent B1 source proof, checks vendor wheel equality, and invokes the actual isolated B worker loader to verify C's origin and version. Syntax checks passed; actual B2 execution remains pending. Its output deliberately does not claim request replay or binary build provenance. The fixed C artifact/report delivery commit is `8208c6c8611d6b7e471ed93816c7cf025b134331`, source commit f627590 as above; both were pushed to C's existing branch.

The actual seam is `profiles._snapshot_to_dict` plus `producer_request.build_producer_analysis_request`, importing `models`, `bundles`, and their fixed package dependencies. B2 can change its worker/vendor loading and fixture inputs while retaining these B1 Git blobs. C will compare B2 serializer/encoder and transitively loaded source files to B1, record the B2 host commit separately, verify the actual loaded C module against the final wheel, and inspect actual worker output. A matching fixture byte string alone does not establish the current program's source identity. A changed seam requires a new explicit producer tuple; the registry has no wildcard, caller-supplied allowlist or metadata-commit alias.

New A, B1 and the final C 0.4.0 wheel are locked and isolated-installed replay has passed. B2 host/worker validation follows this delivery. Current B representation cannot express complete material inventory or final loadout panels; their positive coverage remains **not exercised**, even if native-only unit tests pass or an empty cultivation list totals zero. A statistical condition cannot be invented in the condition-free S3 release; the separate old-A measurement replay remains clearly identified.

Full M0/Goal acceptance also still requires real sources/IDs, human content review and production trust. No real account, UID, game input, remote model, public private-data log, main update, merge, rebase or PR is part of this delivery.
