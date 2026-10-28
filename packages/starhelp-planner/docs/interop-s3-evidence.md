# S3 implementation evidence

Date: 2026-10-21. Frozen technical scope: `starhelp.interop-min.v0.1`, raw SHA-256 `1e62607b9ab5af686f8d63ac067e8a061b0bb61064ffc09c3f58172c4cd31f7a`; reviewed semantic candidate `8116030eb600d58a091a52711b99d7788d45fed71fdbc1bfe02a01ca25233f68`. The shared MVP remains draft. This document records C implementation and observed gates, not production acceptance.

## Final fixed packaged replay (run 2026-10-21, receipt 2026-10-28)

The interrupted delivery was reconciled on 2026-10-28 by checking existing hashes, all captured input files, report checks/cases and the exact current 920-file candidate. **No implementation tests were rerun and no artifacts rebuilt.** Original reports, run dates and raw bytes are preserved.

| Set | Checks | Worker case executions | Final report SHA-256 |
|---|---:|---:|---|
| New A/B1 S3 through B2 | **83 passed, 0 failed** | **62: 31 source + 31 packaged** | `daf0924c8740a789422a6299fade1f5821f67748bc7272e12f45d1909efb77ea` |
| Separate old-A/B1 measurement set | **37 passed, 0 failed** | **30: 15 source + 15 packaged** | `0177ccf9ea10c27458ab6685f85a86cc9db8178fdfd640efa2acca55b444e73e` |

Reports: `interop/reports/c-0.4.0-b2-c248daa-packaged-comparison-v2.json` and `c-0.4.0-b2-c248daa-measurement-packaged-comparison-v2.json`. Final lock `interop/b2-c248daa/packaged-lock.json` has raw SHA `850428ffad5d388d0d25358e7f38f7509433745dd0e26d516628efac2f8a671c`; it fixes source host c248daa, B1 serializer 103741e, C wheel source f627590 / delivery 8208c6c, A source dcb1e3e / artifact 4610573e and final harness `79215ee8cba61a4a738e9f3e8aee152791e17636`. Original artifact/capture/source locks are not rewritten.

| Candidate identity independently checked by C | SHA-256 / count |
|---|---|
| Raw manifest, copied as `interop/b2-c248daa/candidate-manifest.sha256` | `30e4820db6b3a97b193b29b225591758a1e424828b8f55be6094c68046bc19c3` |
| Exact manifest file set | 920 files; checked before and after each replay |
| Main executable | `0370b6f93e095dbb59d22758c5fa1d50abfce7989ab9971d03726acbbdd91dc9` |
| Worker executable | `989c0a8ee1abf73bd99db9b50722990d3a4e728ec6b038814b44dcdd7a260f9a` |

The first packaged reports (77 checks / 56 case executions and 35 / 28) are retained. v2 adds the three S3 per-mode no-template protocol negatives on each transport and one corresponding old-A case per transport. These are **C-constructed protocol negatives**, not B-builder output: outer/inner goals change together, original A/B raw bytes stay fixed, and the normal builder rejects undeclared goals before C. Both workers return correlated no_reviewed_template without creating reports. The unchanged 21/7 builder captures, complete variant/allocation/pending results, locks, confirmed/unreliable identities, error context, report staging and deterministic post-worker revoke rejection all pass; private persistence calls are zero. Check/case counts are not counts of independent game stages.

C's finite synthetic interoperability checks have passed. Independent binary source-build attestation and publisher trust remain false. C's worker observations do not claim B-owned GUI/installer acceptance. Full Goal/M0 and production source/ID/content/trust acceptance remain open, as do positive complete-material/final-panel coverage and B's feedback-builder wiring. No source/profile expansion or S4 implementation is implied.

## Fixed B2 source and actual worker replay

B2 host `c248daab22255a069464a6d277757d01df5d49f3` was extracted from Git into C's new `.tmp/producer-snapshots/b2-c248daa/` directory. All **45 package files** match that exact Git tree before/after execution. Models, profiles, producer_request, bundles and storage match the five independently pinned B1 file hashes. The actual isolated B2 `_load_planner` loads the exact 0.4.0 vendor wheel (SHA 3b5b8de8…52c47aea2), with native rule 0.2.0 and producer profile starhelp.producers.v0.1. B2 remains host identity; B1 `103741e` remains actual serializer/encoder identity.

| Independent C observation | Result | Report raw SHA-256 |
|---|---|---|
| B2 source/load proof | 45 source files, 5 unchanged seam files, actual vendor load | `98378443779cabb2e1c594757c37e18c93a459411705b89089cfe6afac7a10af` |
| New A/B1 set through B2 builder, LocalPlannerProcess, source worker and ReportLifecycle | **49 checks passed, 0 failed; 28 worker cases** | `8f3f1d6ab197401b8055667e3b376cf1eef9d157baba53f4cf05d47cdccad771` |
| Separate old-A measurement set through the same B2 host | **21 checks passed, 0 failed; 14 worker cases** | `8aa238e6f036ebe4ed623f1c546f0e679da9f7e27861caf6b6158681fb965293` |

Files are `interop/reports/c-0.4.0-b2-c248daa-source-load.json`, `c-0.4.0-b2-c248daa-source-worker.json`, and `c-0.4.0-b2-c248daa-measurement-source-worker.json`. Source lock `interop/b2-c248daa/source-lock.json` (SHA `5b7d5eecb92702dcfc9e493b2c0a1450f5784885aa22b3ef6a0335f7db82186e`) pins these reports, original C wheel source/delivery, actual A/B1 tuples and the independently committed C harness e3562f9. Existing artifact/capture locks are not backfilled or rewritten.

The actual B2 builder reproduces all **21 S3** and, separately, **7 measurement** wrappers/snapshot bytes exactly. Worker results match the fixed installed-C evidence for status, full variant/allocation/pending results, citations and report eligibility. Available plans create unsaved reports; pending/infeasible/errors do not. Confirmed moves and the same snapshot under a lock retain their observed changed result. Native withdrawal, adapter digest tamper and unknown-key errors all preserve request/revision/generation and create no report. Wrong wrapper request/revision/generation is refused. A declared lifecycle test interposer calls actual B revoke at the second require_active check, after the real worker completes; both sets reject that completed result as PlannerCancelled. This is a deterministic synthetic race check, not real-account acceptance. **Private persistence calls: 0.**

The source-only reports above do not establish candidate behavior or binary build attestation. The separately pinned source+packaged results are in the final section above; full M0/production/material/final-panel limitations remain.

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

## B1/B2 seam and replay tooling

`tools/verify_b2_host.py` verifies the whole fixed source copy, compares models/profiles/producer_request/bundles/storage bytes to the independent B1 source proof, checks vendor wheel equality, and invokes the actual isolated B worker loader to verify C's origin and version. It passed on c248daa as above. Its standalone output deliberately does not claim request replay or binary build provenance. The fixed C artifact/report delivery commit is `8208c6c8611d6b7e471ed93816c7cf025b134331`, source commit f627590 as above; both were pushed to C's existing branch.

`tools/replay_b2_host.py` uses that verifier, checks the C-installed expected report against the fixed artifact lock, and rebuilds every captured wrapper through the actual B2 builder. Exact B1 snapshot bytes, source/optional hash-pinned executable worker output, complete variant/equipment/pending results, correlation tuple, temporary-report eligibility and absence of persistence are asserted. Extra cases cover no-template protocol inputs, withdrawal, transport digest tamper, unknown key, wrapper identity/revision/generation mismatch, and an explicit test interposer calling actual B revoke at the post-worker authorization checkpoint. Actual c248daa source and pinned Windows worker replay passed as recorded above. Binary source-build attestation stays false; no uncommitted B code is labelled as B1.

Reproduce after extracting B2's exact Git tree into a new C temporary directory (each report path must be new):

```powershell
python -I -B tools/replay_b2_host.py --b-repository '<B repository>' --b-source '<fixed B2 copy>/packages/starhelp-desktop' --b-host-commit '<actual B2 commit>' --capture interop/b-103741e-s3-v1 --expected-report interop/reports/c-0.4.0-b1-s3-installed.json --dependency-root .tmp/interop-deps --wheel artifacts/starhelp_planner-0.4.0-py3-none-any.whl --report '<new B2 report>'
```

Optional `--candidate` and `--candidate-manifest-sha256` add a separate executable observation after verifying the entire exact file manifest before and after replay. The old-A measurement capture can be replayed separately using its own fixed installed expected report; producer sets are never combined into one raw capture.

The actual seam is `profiles._snapshot_to_dict` plus `producer_request.build_producer_analysis_request`, importing `models`, `bundles`, and their fixed package dependencies. B2 can change its worker/vendor loading and fixture inputs while retaining these B1 Git blobs. C will compare B2 serializer/encoder and transitively loaded source files to B1, record the B2 host commit separately, verify the actual loaded C module against the final wheel, and inspect actual worker output. A matching fixture byte string alone does not establish the current program's source identity. A changed seam requires a new explicit producer tuple; the registry has no wildcard, caller-supplied allowlist or metadata-commit alias.

New A, B1, B2 host/candidate and the C 0.4.0 wheel are locked; isolated-installed and source+packaged replay have passed. Current B representation cannot express complete material inventory or final loadout panels; their positive coverage remains **not exercised**, even if native-only unit tests pass or an empty cultivation list totals zero. A statistical condition cannot be invented in the condition-free S3 release; the separate old-A measurement replay remains clearly identified.

Full M0/Goal acceptance also still requires real sources/IDs, human content review and production trust. No real account, UID, game input, remote model, public private-data log, main update, merge, rebase or PR is part of this delivery.
