# Local planner handoff

## Fixed S3 C delivery (2026-10-21)

Source commit `f627590468154cc8622dad8647fefe9f6fd3c4ee` and artifact/report commit `8208c6c8611d6b7e471ed93816c7cf025b134331` were successfully pushed to the existing `codex/mvp-local-planner` branch at `https://github.com/xingyahui-yz/starhelp.git`. Local HEAD/upstream both matched 8208c6c after push. Initial automatic approval rejected the unverified destination; read-only GitHub connector checks established the authenticated owner xingyahui-yz, matching repository/clone URL and admin/push permission, after which the same scoped push was approved and succeeded. No alternative write path was used.

**C 0.4.0 wheel is fixed and isolated-installed verification passed.** Build source `f627590468154cc8622dad8647fefe9f6fd3c4ee`; wheel `packages/starhelp-planner/artifacts/starhelp_planner-0.4.0-py3-none-any.whl`; SHA-256 `3b5b8de8f2ef71cd07f1cfb7724cb0a1564f316860232b58728386d52c47aea2`. All 16 runtime Python files match exact source Git blobs and the isolated installation. Native rules/profile remain 0.2.0; producer profile remains starhelp.producers.v0.1.

**Installed verification:** 88 tests pass, zero failures/errors/skips; new A/B1 S3 replay 204 checks pass; separate old-A/B1 measurement replay 78 checks pass. Artifact lock: `packages/starhelp-planner/artifacts/starhelp_planner-0.4.0.lock.json`; reports: `interop/reports/c-0.4.0-installed-suite.json`, `c-0.4.0-b1-s3-installed.json`, `c-0.4.0-b1-measurement-installed.json` under the package. They pin the same A source/artifact, actual B1 serializer/encoder and C wheel. Raw captures and old wheel/report baselines remain unchanged.

B can now vendor this exact wheel without changing its fixed B1 serializer/encoder blobs. **Remaining:** actual B2 host/worker and vendor loading replay; complete material inventory/final-loadout panel positive coverage is unavailable in the current snapshot representation; real sources/IDs, human content review and production trust remain outside this synthetic technical acceptance. Full Goal/M0 is not complete. Detailed evidence and reproduction: [interop-s3-evidence.md](../../packages/starhelp-planner/docs/interop-s3-evidence.md). The earlier checkpoints below remain historical.

Prepared `tools/verify_b2_host.py` checks an explicitly supplied immutable B2 source against Git, the five models/profiles/producer_request/bundles/storage seam files against B1, the exact vendored C wheel, and actual isolated `_load_planner` module origin/version/hash. Only its Python syntax and child-program syntax have been checked; no B2 host is filled in or claimed executed yet. This tool reports source/load evidence separately from subsequent request/worker replay and candidate provenance. It does not rebuild C or change the fixed wheel/source tuple.

## S3 implementation checkpoint (2026-10-21)

Latest source checkpoint: actual new A `dcb1e3ee220b85229bedc6c79d72ebe495825f37` / package 0.3.0 / artifact `4610573ee9720f2b5e4760a9336263362446b800` is explicitly admitted after actual export, independent verification and five-file Git blob equality. Release `rel_fixture_s3_0001`, raw SHA `f777d05bdb269b2e92a612e4fc96a9ad076f9d5b2bc36760c34c1209ff323772`. B1 newly emitted 21 requests/snapshots and rejected 12 malformed submissions. **88 source tests pass; final source S3 replay 204/204; separate B1/old-A measurement replay 78/78**. The reports assert expected status, full variant/team identity and actual lock-driven allocation change. Preliminary 134-check and v2 harness-layer failures are retained and superseded by v3. Final wheel build/isolated replay is the next step; B2 host remains a distinct subsequent pin. Full details and raw hashes are in the evidence document below.

### Earlier S3 checkpoint (retained)

S3 is explicitly authorized after technical freeze SHA-256 `1e62607b9ab5af686f8d63ac067e8a061b0bb61064ffc09c3f58172c4cd31f7a`. Component 0.4.0 is in development; the published wheel remains 0.3.0 until new A admission and final installed-wheel replay. Scope closed shape/types, full JSON goal matching, equipment key/type/one-of/duplicate-seat checks and same-release kind validation are implemented. Native rule/profile identifiers remain 0.2.0; no new execution semantics or guessed slot aliases are added. **80 source tests pass, zero skipped**, including all 62 retained regressions.

C explicitly admits actual B1 producer `103741e02c90ac672017f783058bdd8dacae982e` / `starhelp.desktop.snapshot.interop-min.v0.1`. All 38 B1 package files and loaded serializer/builder modules were checked against immutable Git objects before and after execution. `interop/b-103741e-legacy-a-v1/` contains 4 actual B1 requests/snapshots, every raw hash and 4 builder-boundary rejection results. Independent serializer bytes equal actual builder bytes. The old A 00d4a58/31e2665 input used here still has no equipment and one mode; no new three-mode/equipment acceptance is claimed. Legacy 045965b/profile and original captures remain unchanged; aef35e46 is metadata, not an admitted producer alias.

Implementation details, exact B1/B2 source seam, commands and remaining matrix: [interop-s3-evidence.md](../../packages/starhelp-planner/docs/interop-s3-evidence.md). A new committed export/package/release and B2 final host remain pending; final wheel will be fixed once, after those actual identities are locked. Current B units/material completeness/final panels remain unavailable and positive coverage unexercised. Full Goal/M0 completion is not claimed. Coordinator reads this chat/handoff directly; no forwarding or cross-thread message is required.

## S2 minimum-interface review receipt

Reviewed coordination candidate `starhelp.interop-min.v0.1` (`docs/contracts/interop-min-v0.1.md`) against C baseline `939818c` / wheel 0.3.0 / native rules 0.2.0. **Final semantic confirmation uses SHA-256 `8116030eb600d58a091a52711b99d7788d45fed71fdbc1bfe02a01ca25233f68`. C agreed in this chat to freeze that limited technical scope; implementation differences are delivered in S3.** Intermediate 6f21ac / 1bed5b comments are superseded by this confirmation. Full section-by-section response, exact fields, version requirements and future replay matrix: [interop-min-v0.1-review.md](../../packages/starhelp-planner/docs/contract-proposals/interop-min-v0.1-review.md).

**Disposition: the 811603 semantic revision is confirmed with no remaining C semantic blocker for the limited target.** It specifies scope closed shape/types, equipment allowed keys/types/opaque slots, mutually exclusive S3 type filters, the exact `requirement` field and A/C predicate/subject intersection. Current C scope/equipment validation and producer-admission gaps belong in §7's finite adaptation list before S3 replay. This is contract confirmation, not a claim that C 0.3.0 already implements every stricter check or that S3 has started.

- **D1 scope:** exactly six keys; five nonempty strings plus positive integer `stage_revision` excluding bool. Current C checks presence/value matching but lacks a closed key/type check. B's selection-boundary review identifies the corresponding gap.
- **D2 equipment:** final S3 shape permits `public_type_id` or nonempty deduplicated `public_type_ids`, mutually exclusively; unrestricted type omits both. Old C's OR/empty-list behavior is an implementation difference to tighten. Allowed keys/types, same-release entity kind and opaque exact slot matching are defined; B's `relic:<type>` strings are not mapped to demo `body` by guessing.
- **D3 predicates:** confirm the revision's native-versus-A intersection. The exact hard/soft key is `requirement`, attribute metadata lives in `manifest.attribute_definitions`, and raw A character subjects use `kind=entity/entity_id` before mapping to C `kind=character/character_id`.
- **D4 unknowns:** confirm the revised partial-inventory lock and revision-0 boundaries. Fields lacking units/context/material completeness/loadout panels stay unknown/not_calculated. Empty cultivation aggregates do not count as positive cost coverage.
- **D5 producer/trust:** current C accepts only the two recorded A code commits, A package 0.2.0, and B serializer 045965b. The next A commit/package requires explicit consumer admission and a new C wheel. C currently mandates mathematical signature verification with `synthetic-test` trust. New measurement/material schema or new executable semantics require explicit profile/capability negotiation.
- **D6 stdio:** correlation tuple is guaranteed after the B worker fills only missing fields from its validated wrapper; raw native/adapter errors may omit snapshot/generation. The fix remains in B S1 `aa2a2b152a6b961e4f547488ff3c9afc3701fc68` by static inspection. Existing C runtime replay evidence is pinned to c4def3b, not a fresh S1 replay. Outer UTF-8 byte limits, C's own node/depth/text limits and error layers are distinct. B's current builder has no feedback argument.

S3 matrix preparation covers each of three modes, actual gear moves, lock-driven availability changes, distinct versus duplicated instances, identity/ownership/field degradation, rule incompatibility, transport/signature/dependency/release/withdrawal gates, late authorization results and report correlation. The original immutable samples remain regression baselines; unavailable cost/panel positive cases remain unexecuted. The review explains the smallest changes and when a new schema/profile is necessary.

This S2 receipt is documentation/static inspection only: no S3 implementation, new test run, build, source change, shared-document edit, real account use or Goal replacement. B's reported 63 tests remain B's evidence. Coordinator can consume this receipt directly; no user forwarding is required. The old full Goal's production/M0 requirements remain uncompleted.

## Round 2 — fixed producer adaptation, partial acceptance

The user approved the round-2 A/C plan on 2026-10-16. The registered Goal still has the old objective and its production/M0 requirements remain unfulfilled. It was blocked, then resumed with the old objective unchanged; current Goal tools cannot edit or clear it. Registering the new Goal requires the user to edit/clear the old Goal in the progress panel. Authorized round-2 implementation proceeds independently of that registration.

Baseline C is `3133eda8ce571e4a58d217e52e28d6e3d3aa6bff` / native 0.2.0. B is pinned to `045965bce4fbc38a3baa79b594535c9dd983d776`, not its newer working HEAD. Old A `313508f895cb422d4a309743eb7f8b99f45a7a91` remains a verified refusal case. The official A producer code is exactly `00d4a5844e74050359227c274de712878bf9187c` / package 0.2.0 / profile `starhelp.b-publicbundle-envelope.v1`; its artifact delivery Git commit is separately pinned to `31e2665cfb9ce1100856d72ebca086b39a603ee8`. Earlier producer `b790a52aea4fabdb362d35c37d9b511b737e1fe4` remains a separate regression capture.

Compatibility matrix: [producer-compatibility-v0.1.md](../../packages/starhelp-planner/docs/producer-compatibility-v0.1.md). B's serializer has no independent unit/context metadata, authorization context or completeness claims. These remain unknown or separately supplied caller context. `source_confirmed` is not promoted to `source_verified`. New A conditional metadata stamps are checked against the exact supported release/schema/capability values; predicate meaning is unchanged.

The official raw A bundle SHA-256 is `cd848169254d78586d9ae197f944688463fb72a513d2b38aba7e888feed4d13b`, release `rel_fixture_0001`. B snapshot SHA-256 is `a0c9fd982bd78e11e2ead2460b08b4ed13b4cb52afbe7f9274a6ecd35bd0cbd5`. `interop/a-00d4a58/consumer-capture-locks.json` records the exact sources and files. A's real export/verify command and B's actual `BundleValidator`/`Ed25519Keyring` accepted it. The regenerated bundle/key/snapshot/checksum bytes exactly matched the official artifact Git blobs at `31e2665`. The key is `starhelp-fixture-ed25519-v1`, synthetic test trust only.

`interop/baseline/` retains actual old producer outputs and refusal evidence. `interop/b-045965b-cases/` contains nine actual fixed B serializer outputs for the official A replay. Earlier `interop/b-baseline-cases/` and `interop/b-b790a52-cases/` remain separate regression inputs. `interop/reports/*source-proof.json` and the capture locks compare producer files against immutable Git objects. **62 tests** pass against both source and the isolated installed wheel, including five tests each for the official and earlier signed A captures. Native 0.2 engine/condition/allocation/cost/validation files are unchanged.

Producer API contract: [producer-adapter-api-v0.1.md](../../packages/starhelp-planner/docs/producer-adapter-api-v0.1.md). The new component version is 0.3.0 while its native rule version stays 0.2.0. Signature support is optional and uses caller-pinned test public keys with mathematical Ed25519 verification; absence of verification support has no bypass. The isolated verification dependency installation uses cryptography 46.0.7, within B's declared `<47` range, and does not change A/B or the shared Python runtime.

Reproduction commands: [producer-replay-commands.md](../../packages/starhelp-planner/docs/producer-replay-commands.md). The current producer has **one** synthetic mode, two complete variants, soft statistical conditions and **zero** equipment requirements. Missing fields/units produce unknown warnings; available plans do not claim those soft conditions are satisfied. Three-mode data and nontrivial equipment-lock/ambiguous-instance replay are not accepted. A must provide another explicitly versioned fixture delivery with those authored/public equipment and mode semantics; C will not edit this payload to manufacture coverage.

### Delivered 0.3.0 artifact and replay evidence

- Wheel: `packages/starhelp-planner/artifacts/starhelp_planner-0.3.0-py3-none-any.whl`.
- Wheel SHA-256: `f7b6c5c221e2491c9399ed76656945175961ac94188b11ad2fe4d4160d0aa0ca`.
- Built runtime source commit: `b87e963c195acb236918b579d76d74a2853cc623`.
- Isolated installed-wheel tests: **62 passed, 0 skipped**; import path and all runtime module bytes were checked against the wheel. Native 0.2 source files remain identical to the baseline.
- Official installed-wheel replay: **12 passed, 0 failed, 3 not exercised**. Normal/full-alternate/no-match, missing field/measurement degradation, unknown versus explicitly not-owned characters, cross-release, transport tamper, unknown/wrong signature key and withdrawal paths passed.
- Unexercised: equipment lock, ambiguous-instance allocation, and three-mode coverage. The actual producer data has no equipment requirement and only one mode, so these cases cannot establish nontrivial interoperability.
- Human report: [c-0.3.0-compatibility.md](../../packages/starhelp-planner/interop/reports/c-0.3.0-compatibility.md).
- Machine reports: `interop/reports/c-0.3.0-wheel-replay.json`, `c-0.3.0-installed-tests.json`, `c-0.3.0-baseline-refusal.json`. Earlier A regression is separately recorded in `c-0.3.0-b790a52-regression.json` (also 12 passed / 3 not exercised); independent B and actual A regeneration evidence are alongside them.

Full round-2 technical acceptance remains **false** until A supplies the additional explicitly versioned mode/equipment fixtures and the missing cases are replayed. Current available plans retain unknown soft statistical conditions as warnings; no missing panel metadata is promoted to satisfaction. The old Goal's M0/production-source/real-account/full-MVP requirements remain uncompleted and are not redefined as this technical round.

### Historical B bridge validation (2026-10-17, host 86fafdd)

B has now delivered a real stdio worker consuming C's pinned 0.3.0 wheel. C independently replayed the immutable B host code at `86fafdddb9183c42408d8c6e71d8ce5de65c4ff3`, separately from the unchanged `045965b` snapshot producer. B's actual signature verifier, byte-preserving public cache, lifecycle gate, process bridge and worker were exercised with original synthetic A/B bytes. No B checkout or private account data was modified/read.

Fixed-source result: **8 passed, 1 failed**. Normal, full alternate, no match, missing-field unknowns, transport tamper and three wrapper-context mismatches behaved as expected. On evidence withdrawal, C correctly returns `withdrawn_public_object` with no plans, but B's worker omits snapshot/generation correlation fields from that native error response, so B's bridge discards the domain error as a snapshot mismatch. B must retain its already validated correlation context for error responses while keeping mismatch/generation rejection intact. This is not counted as a passing withdrawal integration case.

An earlier delivered executable gave the same 8/1 outcome with 827 manifest entries verified. Its exact manifest/worker hashes are retained; B later replaced that candidate, and the replay refused its changed manifest under the old pin. Current reproduction uses the immutable source copy, without assuming executable build provenance.

Details and commands: [desktop-bridge-evidence-v0.1.md](../../packages/starhelp-planner/docs/desktop-bridge-evidence-v0.1.md). Reports: `interop/reports/c-0.3.0-b-86fafdd-source-bridge.json` and the separate earlier executable observations in `c-0.3.0-b-86fafdd-bridge.json`. These reports describe the historical host, with its error-context gap resolved in the next pinned host below.

### B error-context fix and report staging verified (2026-10-18)

B fixed the wrapper in `60b7c99`. C independently pinned host `c4def3ba6f59acb73541eb74c912f84192f5a8a9`, verified all 38 committed package files, and replayed its actual bridge/worker with the delivered C 0.3.0 wheel. The same nine bridge cases pass on source and on the then-delivered Windows executable: **18 passed, 0 failed**. Withdrawal now delivers `withdrawn_public_object` and the matching request/snapshot/generation tuple; mismatches remain refused. The executable snapshot has a separate manifest/worker hash and 919 verified files; source-build attestation is not claimed, and its subsequently missing local manifest was not bypassed.

The reproducible source replay also exercises B's actual public-task selector, request builder, analysis runner and temporary-report lifecycle: **2 report-staging cases passed**. Normal plans stage an unsaved report with same-release evidence references; withdrawal stages no report. No account persistence was called. The builder's native-order compact encoding is separately captured by the actual fixed `045965b` serializer, SHA-256 `7bf8f156ea711fb7d426c41d1a9fb6970b8d78c5b09afaee75a5b434a27e5135`; decoded values equal the original snapshot. Original sorted/newline fixture bytes and hashes remain intact.

Current reports: `interop/reports/c-0.3.0-b-c4def3b-bridge.json` and `c-0.3.0-b-c4def3b-source-bridge.json`; encoding proof: `interop/b-045965b-compact-v1/producer-locks.json`. Reproduction commands are in the linked bridge evidence document. The old B failure is closed only for this explicit host. A's three-mode/equipment fixtures, M0 and real source/content approval, and production TaskPage mapping remain open; full Goal completion is not claimed.

## Round 1 handoff (retained)

Status: component 0.2.0 under the **proposed** `starhelp.local.v0.2` adapter profile. The shared `mvp-v0.1` contract is still `0.1-draft`. Local behavior has been checked with synthetic data; this is not real-game integration, human approval of guides, or MVP completion.

## Entry point and current artifact

- Package: `packages/starhelp-planner/`; import: `starhelp_planner`.
- API: `from starhelp_planner import analyze`; `analyze(request) -> dict`.
- Version constants: `PLANNER_VERSION == "0.2.0"`, `ADAPTER_PROFILE == "starhelp.local.v0.2"`.
- Current wheel: `packages/starhelp-planner/artifacts/starhelp_planner-0.2.0-py3-none-any.whl`.
- SHA-256: `b4071619fd3e74e6008e004769583dad3df61f460e07e0c162eba7ef380783ca`.
- Python 3.12+, no runtime dependencies. Install the exact wheel with `python -m pip install --no-index --no-deps <wheel-path>` or add this component's `src` to the caller's import path during development.
- The retained 0.1.0 wheel is historical. Its profile lacks the semantic/integrity corrections below; use the explicitly versioned 0.2.0 artifact for this handoff.
- Detailed JSON semantics, compatibility changes, examples and proposed error enums: [local-profile-v0.2.md](../../packages/starhelp-planner/docs/local-profile-v0.2.md).

`analyze` accepts only fully materialized built-in JSON values, validates before copying, and does not mutate inputs. It performs no network, GUI, filesystem/database access, model calls, telemetry, account persistence or game input. B owns reading, authorization, encryption, result-generation checks, display and explicit report save. The demo CLI prints synthetic JSON as a separate caller of this pure API.

## Corrections in 0.2.0

1. **Explicit compatibility.** Request and bundle must select `starhelp.local.v0.2`; the supported mandatory capability is `starhelp.local-profile.v0.2`. Old local 0.1.0 bundles are incompatible. Optional exact `local_rule_version` pins are checked, and results identify the actual implementation version. Shared schemas remain the unmodified `0.1-draft`.
2. **Integrity and dependencies.** Every member's canonical digest is recomputed; manifest membership must exactly match embedded objects. Typed references, explicit and inferred dependencies, nested required capabilities/schema/release declarations, duplicate identities and private identity fields are checked. `sha256-json-v1` is an explicit local proposal, not agreed cross-language canonicalization. B still owns authenticity and whole-package/manifest verification; matching a member hash does not establish trust or approval.
3. **Availability.** Latest-known withdrawals and disabled object statuses propagate through nested evidence and dependency links. Losing an alternative does not disable independent sibling variants merely through a template's alternatives list. A disabled selected stage cannot execute. No online validity check occurs.
4. **Scope and goal.** Object scopes and declared entity game-version/environment must fit the task; derived availability retains object kinds. Stage identity/revision must agree with its scope; request/template scope matches all six fields. `task.public_goal` must exactly match a declared template goal. Approval/publication and full partition/seat rosters remain mandatory. Independent substitutions are not composed into new rosters.
5. **Condition semantics.** Registered typed attributes, explicit units, phase and assumptions are checked. Missing/conflicting/stale/unconfirmed/wrong-unit/wrong-context data remains unknown. Public evidence state stays separate from local match state. Booleans cannot satisfy numeric predicates. Unsupported conditions cannot execute.
6. **Allocation-specific evaluation.** Every examined equipment mapping gets its own condition checks, including equipment-slot predicates. Original loadout-dependent character panels are invalid after moves/removals. A final-loadout fingerprint plus confirmed `loadout_views` fields can provide a new basis; no combat-stat simulator is implied. Otherwise the candidate remains pending. Search is bounded to 50,000 nodes / 256 assignments; truncated failure to find a passing mapping remains unknown rather than proving infeasibility.
7. **Cultivation.** Character/light-cone/trace/relic gaps use confirmed integer progression fields and final item identity. Revisioned scope/entity/attribute-bound transition tables cover the entire requested range. Static `applicable: true` costs are insufficient. Zero gap costs zero; stale/missing progression is never filled with zero. Per-step costs are gross; `plan.cultivation_cost` sums all steps and deducts each material inventory once. Incomplete/conflicting/stale material counts permit valid gross cost but no net shortage. Incomplete step costs produce no aggregate claim.
8. **Troubleshooting.** Reviewed, scope-bound declarative triggers retain their own results. Target complete variants are rechecked against this task's ownership, fixed/excluded roles, locks, equipment, goal and conditions. Infeasible targets are not suggested; unknown targets are explicitly pending. Optional source-variant applicability and supplied feedback scope are checked. No unsupported advice or learning is generated.

## Result and error semantics

Success results include request/profile/snapshot/generation references, actual planner/rule/profile versions, one release, public scope/goal/constraints, stage/template/variant revisions, current plans, rearrangement plans, pending candidates, rejected variants, condition bases, cultivation costs/gaps, tactics/mechanics/risks, troubleshooting, coverage/validity and a same-release citation catalog. Ranking is an adaptation order and never a win probability. Unsupported resource reuse semantics fail closed; this profile supports stage-wide exclusive character/item use only.

Expected errors return `status: "error"`, `{code, message, retryable: false, details}` and empty plan/citation arrays. Proposed codes include `invalid_payload`, `snapshot_conflict`, `invalid_public_bundle`, `unsupported_schema`, `unsupported_profile`, `unsupported_rule_version`, `unsupported_capability`, `authorization_inactive`, `superseded_generation`, `scope_mismatch`, and `withdrawn_public_object`. Inspect `invalid_public_bundle.error.details.issues` for integrity/dependency/reference/schema problems. These are not frozen A/B enums.

## Verification evidence

Verified locally on Python 3.12.14:

- `python -m compileall -q src tests` succeeded.
- `python -m unittest discover -s tests -p 'test_*.py' -v` passed **45 tests**. This is one suite, not a claim of 45 real game scenarios; several tests contain related subcases.
- The suite includes the original 24 synthetic scenarios plus measurement/loadout/allocation truncation, transition/range/version/quantity checks, all four cultivation categories and shared inventory deduction, tamper/missing/orphan/dependency/type checks, nested withdrawal, target eligibility, malformed/non-JSON input, deterministic results and input/result isolation.
- Built the wheel with local setuptools/wheel and `PIP_NO_INDEX=1`; installed it into a separate temporary target with `--no-index --no-deps`.
- Under Python isolated mode (`-I`), explicitly imported from that installed target, asserted the module path/version, and ran the same 45 tests successfully against the installed implementation.
- Ran the installed `starhelp_planner.demo` entry point, parsed its JSON and checked version `0.2.0`, status `plans_available`, and two current synthetic plans. This does not validate real sources, actual item IDs, human-approved content, B loading, or live accounts.

`tests/test_stdlib.py` wraps the original plain scenario functions. The other three unittest modules cover the new behavior. Semantic tests explicitly republish modified **synthetic** objects; integrity tests call the raw API without refreshing damaged hashes/dependencies. `refresh_fixture_members` refuses non-fixture releases and never changes approval flags. No pytest/Ruff installation or claimed lint run was needed for the standard-library suite.

## Local execution

From `packages/starhelp-planner/`:

```powershell
$env:PYTHONPATH = 'src;tests'
python -m unittest discover -s tests -p 'test_*.py' -v
python -m starhelp_planner.demo
```

Sample constructor: `starhelp_planner.demo_data.synthetic_request()`. All `fixture:` IDs/values and approval statuses are fictional. The source-level dependency guard checks for prohibited network/GUI/storage/game-input imports; the actual API remains in-memory. Build with `python -m pip wheel . --no-deps --no-build-isolation --wheel-dir dist` and transfer/pin the resulting version and digest through the agreed handoff process.

## M0 and external dependencies

On 2026-10-16 the user confirmed that no versioned local artifacts exist for the common contract, A's public package or B's snapshot specification. This component therefore records a concrete proposal and cannot claim M0, M5/M6 or B black-box integration has passed.

Required inputs/evidence:

1. An agreed M0 contract/version and shared fixture, including accepted predicate/attribute registry, units/context, field-state/freshness/completeness and error semantics.
2. A versioned published A bundle with verified source permissions, real mode/cycle/stage/entity mappings, complete reviewed/published variants, evidence, dependencies, cost tables and revocation metadata.
3. A versioned B snapshot specification/artifact for ownership, field provenance/context/time, instance identity, locks/material coverage, and any confirmed final-loadout views.
4. Agreed manifest canonicalization/authenticity/verification ownership and supported capability negotiation.
5. Three-mode real fixed samples, release-current coverage, actual B component loading, and black-box acceptance evidence.

No other feature branch was merged, rebased or cherry-picked; no shared contract, root configuration, other component or main change is part of this handoff. The Goal remains incomplete while these integration requirements are unmet.
