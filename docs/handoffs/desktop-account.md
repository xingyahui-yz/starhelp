# Desktop and Account Component Handoff

Status: in progress. This is an implementation log, not an MVP acceptance statement.

Current verification baseline (2026-10-20): the source changes in `imports.py` and its regression
test passed 63 package tests plus `compileall` and `git diff --check`. The candidate was built from
base commit `8aa39937672a03e3c4668f6aacad7a5ca8f26b19` plus the exact package source patch SHA-256
`35edd65ad7a9dd56915b1bcaa8ab63a88388c1076f49ddf445e8c4e3ac11adb9`. PyInstaller 6.22.3 / Python
3.12.14 produced 919 files; manifest SHA-256 is
`1ffb65b7560ade002d4611a518bc83cab1ca2f0048d792035bf5a976a57cf2eb`, `StarHelp.exe` SHA-256 is
`4c5cf94a2b42beddc24eee22f6ceee8dc8c6f26128ab7a384baa4a342b8a7448`, and packaged worker SHA-256
is `ce7b6722b432a12030a88f8610d548f5c6cc25ab7b363a3445552b920266f2aa`. The local verification
record is `packages/starhelp-desktop/build/candidate-verification-2026-10-20.txt` (SHA-256
`01258da05b55e0fe757966cfa54a18fb9f04b8cccb039caa4d5ca4afbd3dd178`); PyInstaller warning logs are
under the corresponding `build/StarHelp/` and `build/StarHelpPlannerWorker/` directories. The
candidate is unsigned. Fixed A/B/C producer versions and artifact digests are recorded below and
in the fixture README; these synthetic profiles are compatibility evidence, not a frozen contract.

## Boundary and current baseline

- Repository: `parallel/desktop-account`; branch: `codex/mvp-desktop-account`.
- Component ownership: `packages/starhelp-desktop/` and this handoff only.
- Shared contract, root dependencies, legacy `src/abyss_ai`, and other components remain unchanged.
- Current implementation is isolated from the legacy offline simulation. The planner and knowledge
  service are not connected; local adapters must display that state.

## Current local B/C exchange used by the synthetic fixture (draft only)

These exact shapes describe the pinned synthetic replay. They are not a proposal to freeze the
shared contract or unlock production TaskPage analysis.

| Boundary | Current exact shape and semantics |
|---|---|
| B snapshot serializer | `AccountSnapshot` / `0.1-draft`: `profile_id`, `snapshot_id`, `revision`, `generated_at`, `fields`, `ownership`, `coverage`, and `equipment`. Each field fact has `value`, `status`, `source_kind`, `source_id`, `observed_at`, nullable `confirmed_at`, and nullable `scope`. Equipment has `local_instance_id`, `public_type_id`, `slot`, `identity`, nullable `owner_character_id`, and its own fact map. The fixture labels this producer profile `starhelp.desktop.snapshot.045965b` and source commit `045965bce4fbc38a3baa79b594535c9dd983d776`; neither is declared as a frozen shared format. |
| B task selection | `select_public_task` reads only the exact release's `planner-view:<release_id>`. It requires exactly one matching stage and template, stage membership in the template, both objects tied to the active release, a stage `scope` object, and exactly one matching `public_goals[].kind`. It copies that scope and goal; it does not map UI labels to IDs or infer unsupported mappings. |
| Producer request | Outer `AnalysisRequest` / `0.1-draft` contains request ID and authorization generation, full validated public bundle, local task, and an account snapshot authorization wrapper. Embedded `ProducerAnalysisRequest` / `0.1` / `starhelp.producers.v0.1` carries exact raw A bundle and B snapshot JSON plus SHA-256, producer commit and format profile, expected release, active local profile/generation, explicitly supplied distribution trust purpose/key material, task, UTC evaluation time, and latest-known withdrawn evidence refs. It is passed only to the local worker; the B adapter itself does not contact A or a remote model. |
| Worker stdio | Protocol `starhelp-local-planner` / `0.1-draft`: one UTF-8 JSON `AnalysisRequest` on stdin (8 MiB maximum), one versioned JSON response on stdout (16 MiB maximum), default 30-second timeout. Response has `protocol`, `protocol_version`, `planner_version`, `capabilities`, and `result`. Result correlation requires `request_id`, `snapshot_revision`, and `authorization_generation`; eligible reports additionally require exact release ID and evidence `{id, revision}` references. Authorization revocation cancels/kills the worker and late results are rejected. |
| Worker errors | Domain errors use a normal response with `result.status = error`, adapter `planner_error`/error details, and correlation fields. Malformed input or unexpected exceptions are silent on stderr and exit 3; oversized input exits 2; oversized response exits 4. The parent maps missing/invalid stdout and nonzero process exits to `PlannerUnavailable`; those process failures do not carry structured request correlation. |
| Capabilities | Synthetic A envelope requires `starhelp.knowledge-distribution.v1`. C planner view validates `starhelp.local-profile.v0.2`. The B2 worker reports `starhelp.producers.v0.1` and `starhelp.local-profile.v0.2`; B requires both. Current B2 pin is C package `0.4.0`, native rules `0.2.0`, wheel SHA-256 `3b5b8de8f2ef71cd07f1cfb7724cb0a1564f316860232b58728386d52c47aea2`, source commit `f627590468154cc8622dad8647fefe9f6fd3c4ee`. The 0.3.0 row in earlier dated review notes remains historical. |
| Units and conditions | C requires an attribute definition with value type, unit, phase list, and loadout-dependence. Public conditions must use a registered attribute, supported finite operator, exact registered unit, and a measurement context with an allowed phase and explicit assumptions; unknown unit/context/attribute semantics reject the bundle/condition as unsupported. During matching, absent, unconfirmed, conflicting, stale, unit-mismatched, context-mismatched, or out-of-scope local facts yield `match_status = unknown` with a reason code, not a guessed numeric comparison. B has no production field/unit mapping. |

The earlier S1 review below covered A `rel_fixture_0001` and C 0.3.0. Current B2 evidence also covers A `rel_fixture_s3_0001`, B1 snapshot profile `starhelp.desktop.snapshot.interop-min.v0.1`, and C 0.4.0: source and packaged worker each matched 21 captured cases. This synthetic evidence covers three fixture modes, equipment identity/allocation cases, locks, pending candidates, and withdrawal. The production contract remains `0.1-draft`; real game ID/field mapping, production trust and transport, complete materials and final-loadout panel evidence remain open M0 inputs.

## B review of `starhelp.interop-min.v0.1` (2026-10-20; candidate only)

This is B's implementation review of the shared candidate, not a freeze or an edit to that document.

| Candidate area | B evidence and review | Producer/consumer impact and smallest follow-up |
|---|---|---|
| §1 versions and ownership | Supported for the pinned synthetic exchange: B names the exact A fixture, B serializer commit/profile, and C wheel/rule/profile in its replay test and local verification record. The old B serializer profile has only been exercised on this fixture. | A/C can use this as one reproducible compatibility tuple. It does not establish compatibility of later producer releases or production configuration. Keep any new profile explicit and pin its artifact digest. No new B schema proposed by this review. |
| §2 raw bytes, distribution signature and closure | Supported for the pinned A artifact: B validates the original payload bytes and signature against explicitly supplied test trust, checks release/object/member closure and member digests, and the interop test reaches the packaged C worker. A's `sha256:`/`sha256-json-v1` projection digest remains distinct from B's raw transport SHA-256 and object digest; do not compare those layers as if they were the same digest. | A must keep shipping immutable originals and provenance; B must continue to provision trust out of band. Evidence is synthetic-test-only and does not satisfy production key trust. No format-version change proposed for the current successful fixture. |
| §3 task and equipment semantics | Partly supported. `select_public_task` selects a unique stage/template from the validated same-release planner view, checks stage membership, and copies an explicitly declared goal and scope without UI-label inference. It does not enforce that `scope` has exactly the six candidate keys or validate their value types. The replayed A release has one mode and no equipment requirements, so B has no positive evidence for complete main/alternate or gear allocation semantics. | B's current function can consume a future scope by copying it, but cannot certify the candidate's exact scope semantics. Before accepting a new A release, validate the exact six keys, non-empty ID fields, and positive integer `stage_revision` at the B selection boundary; require C to confirm matching semantics. A's next fixture must exercise actual equipment allocation. No change to an existing signed schema is proposed. |
| §4 snapshot and authorization | Serializer emits the documented `AccountSnapshot` draft fields, fact status/source/timestamps, ownership, coverage and equipment identity/facts; its synthetic fixture replays successfully. The current import confirmation fix confirms equipment facts but deliberately does not confirm the equipment instance identity. B stores authorization separately and checks profile/generation around worker execution. | Supported for the fixed fixture and identity rule. B does not serialize a standalone fact unit or measurement context, structured material completeness, or a final loadout panel; its `scope` string is not a substitute. The repository creates initial revision `0`, and `_validate_request_envelope` only requires an integer, so the candidate's positive-revision requirement is **not** met for that state. Smallest follow-up: do not submit revision 0 to C; first define an honest snapshot revision transition in B, without incrementing only to fit C. If the agreed semantics cannot map directly, propose a new snapshot profile before adding fields. |
| §5 request, response and transport | Supported for the fixed exchange: B builds the producer request with raw A/B JSON, digests, explicit test trust, authorization context, task and withdrawn refs; the packaged worker checks the pinned capabilities and test proves request/revision/generation correlation for success and a withdrawn-evidence domain error. Correlated structured domain errors are distinct from transport failures (which surface as `PlannerUnavailable`). | B/C can replay the current pinned tuple. Production must settle trust provisioning and full error-code compatibility. Keep timeout, size, and transport behavior explicit; do not interpret process failure as a domain result. No schema change proposed by this review. |
| §6 next immutable samples | Agreed as the necessary next fixture, not yet covered by B evidence. The present bundle cannot verify three modes, non-empty requirements, allocation/locks, ambiguous identity, or meaningful equipment-driven feasibility changes. | A must deliver a new immutable release; C must recognize and execute its exact producer shape; B then pins the new wheel/bundle/snapshot digests and replays the full positive and negative matrix. Keep `rel_fixture_0001` intact. |
| §7 freeze and production gates | Agreed. This review does not mark the candidate or the M0 contract frozen. Synthetic keys, unsigned desktop candidate, one-mode fixture, and missing local mapping/trust details do not meet production acceptance. | Coordinator should reconcile A/B/C reviews and publish the effective candidate digest only after the remaining technical differences are addressed. Real-source, production trust, release signing, and real-account acceptance remain separate gates. |

**B disposition:** accept §§1, 2, 5, 6 and 7 as coordination direction for the limited synthetic integration, with the evidence limits above; accept §4's shape and authorization separation but flag revision 0 and absent measurement context; partially accept §3 while requiring exact scope validation and new equipment replay. This is not a freeze vote for the whole MVP, and B has not changed the shared candidate. The next B work depends on the coordinator's fixed S3 A release and C adapter; the current S1 patch/candidate is closed after this review and push.

### S3 B scope and snapshot-revision boundary (2026-10-21)

After the finite technical scope was frozen at `interop-min-v0.1.md` raw SHA-256
`1e62607b9ab5af686f8d63ac067e8a061b0bb61064ffc09c3f58172c4cd31f7a`, B added the agreed
consumer-boundary checks without changing the serializer profile or wire schema. `select_public_task`
now requires exactly the six scope keys, five non-empty string values, and a positive integer
`stage_revision` that excludes booleans; it requires the selected stage and template scopes to match
and the inner stage ID to match the selected stage. `build_producer_analysis_request` repeats scope
validation against the immutable validated bundle and requires the complete public-goal object to be
listed by a same-release template. The stdio envelope and producer request builder both reject a
snapshot revision below 1. B's local uninitialized base may remain at revision 0; the first confirmed
import creates revision 1 through the existing merge transition, with no artificial revision bump.

Synthetic regressions cover missing/extra scope keys, boolean and zero stage revisions, stage/template
scope mismatch, mutated task revision and goal, and snapshot revision 0 at both C submission
boundaries. All 64 package unittest tests, `compileall`, and `git diff --check` passed. No candidate
rebuild was run for this boundary-only patch; the fixed S1 candidate remains the prior unsigned
919-file package. A's new three-mode/equipment release and C's explicitly supporting wheel have not
yet arrived, so full S3 replay, report lifecycle/revocation replay on that set, and the single
post-dependency candidate rebuild remain pending. No real UID or private account data was used.

### S3 B snapshot raw-byte capture for the existing fixture (2026-10-21)

`AccountSnapshot` shape source remains B serializer commit `045965bce4fbc38a3baa79b594535c9dd983d776`
with profile `starhelp.desktop.snapshot.045965b`. The producer builder now emits the snapshot as
UTF-8 JSON with `ensure_ascii=false`, sorted object keys, compact separators, `allow_nan=false`, and
one terminal LF. Its `account_snapshot.raw_json` bytes exactly equal the original existing fixture
`tests/fixtures/producer-interop-v1/synthetic-b-snapshot-045965b.json`, SHA-256
`a0c9fd982bd78e11e2ead2460b08b4ed13b4cb52afbe7f9274a6ecd35bd0cbd5`; the regression compares the
byte arrays and independently checks the request digest. The same request still completes the
packaged C 0.3.0 synthetic replay. This is byte-compatibility evidence for the existing synthetic
shape, not a new three-mode/equipment sample. The B host commit that emits these bytes is recorded
separately from the serializer source in the S3 lock when the new A/C artifact set is pinned.

### S3 B1 producer source pin (2026-10-21)

B1 is commit `103741e02c90ac672017f783058bdd8dacae982e`; the GitHub branch ref was verified to
match. New S3 snapshot requests will identify this actual producer implementation with format
profile `starhelp.desktop.snapshot.interop-min.v0.1`. The existing `starhelp.desktop.snapshot.045965b`
profile remains only on the immutable legacy fixture. The `_snapshot_to_dict` schema implementation
originated at `045965bce4fbc38a3baa79b594535c9dd983d776`; B1 separately pins its current host and
encoding implementation. C must explicitly recognize the B1 commit/profile tuple before the new
sample is replayed. No new schema or profile fields are added to the wire object.

| B1 input | SHA-256 | Git blob at B1 |
|---|---|---|
| `src/starhelp_desktop/models.py` | `432bf4f1c0599e6eee982d949114c50e4849eb4de49e70cdae31873e509af504` | `b102fc58254313e265090332387db0ae01001495` |
| `src/starhelp_desktop/profiles.py` | `d5c3531cdde6e9bd6381578a83374f6dc00be4b5ea5dad1c7bca7eb586134be3` | `1449d8dab100de1d4255cdaf59c3acaab43a5411` |
| `src/starhelp_desktop/producer_request.py` | `c88882dede1e225f21095a7baa13f64ca78b66e745a53c8b0662c6731e573e59` | `5f1a89db3588573537bfce9af09172deb70ba524` |
| `src/starhelp_desktop/planner.py` | `96950c94a1554589e8cdfb7142eb61a08aca3d3dfe2ae5b360794b59d03a88ba` | `fb98ba2a8c6fc980b2ffe33691e590b04138c684` |
| `src/starhelp_desktop/planner_worker.py` | `4a7053e9ff6db1426d83dbdeb9248b344bf68fe68933cf211e0b88b7d7af5930` | `b20c9e746758d358e4eecacd55e5eb7e70ca9509` |
| `pyproject.toml` | `6f1df152d3d34086d5ab4c80cf2c939b9a8789ee45db9be1aafdfadcafd523a3` | `022d94a6393d6d5ab73504e0baee900d37adfa48` |

The current B2 host vendors the legacy C wheel SHA-256
`f7b6c5c221e2491c9399ed76656945175961ac94188b11ad2fe4d4160d0aa0ca`; that is a worker dependency,
not a change to B1 snapshot serialization. When C's B1-compatible wheel and the new A sample arrive,
B2 will update the pinned vendor/worker inputs while preserving the B1 serializer and encoder blobs,
then record the B2 host commit and prove the packaged worker loaded the pinned module. No candidate
rebuild was performed at B1 publication; it will occur once after the fixed S3 source set is complete.

### S3 A immutable input delivery observed (2026-10-21)

A committed its synthetic distribution at `4610573ee9720f2b5e4760a9336263362446b800` in
`parallel/knowledge-backend/packages/starhelp-knowledge/artifacts/interop-min-v0.1-s3/`.
The bundle is `rel_fixture_s3_0001`; its raw SHA-256 is
`f777d05bdb269b2e92a612e4fc96a9ad076f9d5b2bc36760c34c1209ff323772`. The accompanying B snapshot
raw SHA-256 is `e7269a57b83e3145bd647262c4a88d1663718d4078c502f0cd4829108d9b3b58`, and the equipment
type table SHA-256 is `7ffda486ef1b00683d3b3279fb3f2bf802075c46a5f04dbe563fc60f6ed75380`; both match
the delivered `SHA256SUMS.txt`. The planner view contains three distinct synthetic mode scopes,
three templates, and six variants, with a separate equipment type table and synthetic confirmed /
ambiguous equipment identities in the snapshot. These bytes are A inputs only and have not yet been
accepted in a B→C replay.

B ran a read-only compatibility check against those exact files: the current `BundleValidator`
verified the fixture Ed25519 signature, member hashes, object set, references, and supported
capability; `select_public_task` selected all three scopes; and
`build_producer_analysis_request` built one complete request for each mode. The B1-encoded snapshot
SHA-256 was `e7269a57b83e3145bd647262c4a88d1663718d4078c502f0cd4829108d9b3b58`, byte-for-byte equal
to A's delivered snapshot. This confirms B-side loading, task selection, and request construction;
it does not prove C execution, mode/equipment allocation outcomes, report lifecycle, or withdrawal
behavior.

At this check, C's branch still has uncommitted adapter changes and the distributable artifact
directory still contains only wheel 0.3.0 (SHA-256
`f7b6c5c221e2491c9399ed76656945175961ac94188b11ad2fe4d4160d0aa0ca`). Therefore the S3 A/C tuple
is not fixed: B has not changed its vendor, worker, demo input, or B1 serializer, and has not rebuilt
the desktop candidate. Once C's compatible wheel and the matching immutable replay lock are
officially delivered, B will validate the exact mode/equipment matrix, report lifecycle
and withdrawal behavior, then make one candidate rebuild from that fixed set. No real UID or private
account data was used.

#### B2 execution checklist for the fixed S3 tuple

| Gate | Required evidence before closing S3 |
|---|---|
| Input lock | Record the official A commit, every delivered A file SHA-256, release ID, C wheel commit/version/SHA-256, C producer profile/capabilities, and B2 host commit. Keep B1's serializer and encoder source hashes unchanged; require the delivered snapshot raw bytes to match B1 output. |
| B request boundary | Revalidate the signed A envelope and complete same-release dependencies; build requests only from exact stage/template scopes and declared goals for alpha, beta, and gamma. Reject mutated scopes, cross-release references, missing members, and unsupported capabilities. |
| Planner matrix | Replay C's named expected cases for each of the three modes: main result, complete alternate, and no-match/insufficient coverage. Record exact expected and actual status, plan IDs, evidence refs, and reasons; do not derive missing cases from UI labels. |
| Equipment behavior | Verify equipment type/slot requirements against the separate type table; exercise confirmed and ambiguous B instances, explicit locks, a locked allocation conflict, and a confirmed cross-character move. Ambiguous identities may support the current loadout but must not enter rearrangement. Record current-loadout and rearrangement outputs separately. |
| Materials and provenance | Confirm returned cultivation/material quantities, costs, and unknown coverage are displayed with their source refs; absent data stays unknown and is not rendered as zero. Check all planner citations resolve inside the pinned release. |
| Withdrawal and reports | Replay a withdrawn-evidence domain error with request ID, snapshot revision, and authorization generation correlation. Confirm it is not treated as a transport failure and cannot be saved as a plan. For successful output, verify preview is unsaved by default, explicit save persists it, snapshot/release changes mark it for review, and revocation cancels work and removes reports. |
| Packaged worker | Update only the pinned vendor wheel, worker-loading inputs, and S3 demo/replay inputs; prove the packaged worker loaded the pinned C version and ran the same matrix. Keep the legacy fixture unchanged. |
| Candidate and installer | After all prior gates pass, run the full package tests and `compileall`, build one unsigned candidate from the fixed B2 commit, verify the manifest covers the exact file set, smoke the app with isolated `LOCALAPPDATA`, and test synthetic install, upgrade, both rollback directions, and tamper rejection. Record hashes and target-Windows limitations. |

The B-side bundle/signature/task/request checks recorded above are prerequisites only. The C wheel,
named expected planner matrix, packaged-worker replay, report/withdrawal replay, and candidate /
installer checks remain open until C's immutable artifact and replay lock are officially available.

#### C source-only S3 preview (not an accepted artifact)

A read-only preview of C's current working-tree capture lock
`interop/b-103741e-s3-v1/producer-locks.json` (SHA-256
`a6e8620bf242eb9598697de777c0f71d45f4cf7756c326371ad4151e218562d3`) confirms it points to the
official A producer commit `dcb1e3ee220b85229bedc6c79d72ebe495825f37`, release
`rel_fixture_s3_0001`, exact A bundle SHA-256 `f777d05bdb269b2e92a612e4fc96a9ad076f9d5b2bc36760c34c1209ff323772`,
and B1 snapshot SHA-256 `e7269a57b83e3145bd647262c4a88d1663718d4078c502f0cd4829108d9b3b58`. It contains
21 captured per-mode requests and 12 recorded B-builder boundary rejections. The lock and capture
files remain in C's uncommitted working tree; they are not vendored into B.

C's development-only source report
`interop/reports/c-0.4.0-dev-b1-s3-source-v2.json` (SHA-256
`0677163d242de6db4a313557ecdb46babcfa3588ba2558bf99174733477a945f`) reports 202 checks passed
and 2 failed, `full_three_party_acceptance=false`, and no wheel proof. Both failed cases expect an
extra task scope key and boolean `stage_revision` to reach C for `invalid_payload`; B's current
task-selection/request-builder boundary rejects both before C, as covered by the B interop tests.
This is a gate-expectation mismatch in the development report, not evidence that either invalid task
should cross B's boundary. The report also leaves B2 host/worker integration, positive complete
inventory/material calculations, and final-loadout calculations unexercised. No C source report is
treated as final package acceptance; repeat the relevant checks against the officially pinned wheel.

C later refreshed the source-only result as
`interop/reports/c-0.4.0-dev-b1-s3-source-v3.json` (SHA-256
`a86cc11302105ac6ffceefca9d32cc35ea315d187783f4fd7afd91aefabcadd4`), still against the same
capture-lock SHA-256 above. That report has 204 checks passed, 0 failed, all three synthetic modes,
but still sets `full_three_party_acceptance=false` and has no wheel proof. It still lists B2 host/worker
integration, positive complete inventory/material calculations, and final-loadout calculations as
not exercised; those remain open despite the source-only pass.

The S3 preview also exposed the snapshot model's existing rejection of duplicate local equipment
instance UUIDs. B now has an explicit regression constructing two distinct type/slot records with
the same UUID and requiring `AccountSnapshot` to reject the snapshot before serialization. The full
package suite passes 65 tests; `compileall` and `git diff --check` pass. This test-only change does
not alter B1 serializer bytes or trigger a candidate rebuild.

B independently checked all 21 C-captured `stage-*.request.json` files against their paired snapshot
files and the official A bundle bytes. Every embedded snapshot matched its source file and declared
SHA-256, B1 producer commit/profile matched the pinned tuple, every embedded bundle exactly matched
the official A bytes and digest, and request IDs and six-key task scopes were consistent: 21 checked,
0 mismatches. This validates the captured source inputs only; it does not execute or package C's
worker.

## M0 source and contract findings (checked 2026-10-18)

1. March7th's parsed API documents `GET /sr_info_parsed/{uid}` with `language`/`lang` and
   `version` query parameters. Its example shows `player` and a `characters` showcase list. The
   documented character record includes ID, level, rank, skills, light cone, relics, attributes,
   while `player.space_info` includes aggregate counts. Aggregate counts are not item inventories.
   The component normalizes only listed showcase records and treats every unlisted character or
   item as unknown. It does not retain the returned player UID, nickname, signature, or raw body.
   The documented request has no region parameter; its optional `is_force_update` query flag bypasses
   the service cache, so the component does not use it for routine refresh. The UI stores the player's
   selected region label locally. A fresh check confirms the documented request still has no region
   parameter. The Python client constructs the endpoint URL from UID, language, and optional API
   version; this client behavior does not establish how the service routes a UID to a server. Region
   correctness for each of the three supported choices still needs M0 confirmation. The response
   example includes `space_info.memory_data` summary fields such as `chaos_id`, `chaos_level`, and
   `chaos_star_count`; it is not a full inventory. The documentation page says it was last updated
   2025-02-15, so this example does not establish current mode/cycle coverage. Sources:
   [parsed API](https://march7th.xyz/zh/api/parsed.html),
   [Mihomo Python client](https://github.com/Mar-7th/mihomo.py/blob/master/mihomo/client.py).
2. Enka's public documentation describes UID lookup, showcase data, dynamic rate limits and a TTL
   that clients should honor; it also asks clients to send a custom User-Agent and not enumerate UIDs.
   The current top-level API documentation lists Genshin Impact and Zenless Zone Zero, and does not
   establish an HSR-specific schema or UID-to-region mapping for this component, so Enka is not
   enabled as an adapter. Source:
   [Enka API documentation](https://github.com/EnkaNetwork/API-docs/blob/master/api_chs.md).
3. No source inspected proves stable public IDs are unique equipment-copy identities. The component
   leaves imported equipment identity unconfirmed/ambiguous; only player-confirmed or subsequently
   source-verified local identities may be reassigned.
4. The shared MVP contract remains `0.1-draft`. Real mode/cycle/stage IDs, source coverage and
   permissions, region interpretation, transport/error schema, release hash/signature rules,
   capabilities, and condition semantics remain M0 decisions. No shared contract was modified.
5. The official [Mihomo `player.py` model](https://github.com/MetaCubeX/mihomo/blob/008b91bfe8c0e2daca0ab69061efd9ea1ad71bd2/mihomo/models/player.py)
   and its [v1 player model](https://github.com/MetaCubeX/mihomo/blob/008b91bfe8c0e2daca0ab69061efd9ea1ad71bd2/mihomo/models/v1/player.py)
   document `memory_data` / `ChallengeData` as a `ForgottenHall` summary with fields such as
   `level`, `chaos_id`, and `chaos_level` (v1 aliases include `PreMazeGroupIndex`, `MazeGroupIndex`,
   and `MazeGroupID`). They do not establish complete current-cycle history or mappings for all
   three challenge modes. The B adapter now retains only these bounded nonnegative integer fields
   under their provider field names and source scope. The Progress page renders them as a raw source
   summary and keeps Memory of Chaos, Pure Fiction, and Apocalyptic Shadow progress `unknown` until
   source coverage and M0 mappings are verified. Model inspection is not live API verification; no
   real UID was queried.

## Implemented so far

- Isolated PySide6 shell with task, account/import, progress, public cache, reports, and maintenance
  pages; planner, production public transport, service lifecycle, and admin flows are visibly marked
  unavailable. The task form persists the last target and local constraints per profile in the
  encrypted store, restores them after restart, and removes them with profile revocation; until the
  planner is present, created tasks stay in an explicit waiting state.
- Isolated package configuration with optional PySide6 Essentials, PyInstaller, local OCR, and
  Ed25519 verification extras;
  no root dependency changes.
- Typed local facts distinguish field provenance/status, ownership (`owned` / `not_owned` / `unknown`),
  and public equipment type from local item identity.
- Partial merge updates covered fields only, retains uncovered values/timestamps, and surfaces
  conflicting values without choosing silently.
- Structured/manual import preview and an optional local RapidOCR adapter. The UI runs OCR in a
  worker, hides UID-like OCR text, requires a player-selected text-row-to-field mapping, and then
  asks for a separate confirmation. Selected image files are read with a hard byte limit before
  decoding (no stat/read race), then type/dimension checked and not persisted.
- Imported equipment is listed per profile with its current identity. A player can explicitly
  confirm an individual equipment instance; the decision is written to the encrypted snapshot and
  only then becomes eligible for reassignment. The UI does not infer copy identity from a public
  equipment type ID. Same-type duplicate candidates can be linked only after the player confirms
  they are the same physical copy. Conflicting owner/stat values require per-field source choices;
  the existing local identity is retained and the duplicate record is removed from the merged snapshot.
- Public-profile refresh stays manual by default. A separate per-profile opt-in stores the UID only
  in current-user DPAPI storage, queries directly while the app is running (immediately on opt-in,
  then at most once per 24 hours), and keeps results in preview until the player confirms import.
  Disabling refresh or revoking the profile deletes the encrypted UID configuration. A separate
  cancel action marks an active read for cancellation and discards any returned proposal; an HTTP
  request already sent cannot be withdrawn from the service, which the UI states explicitly.
- A consent-gated Mihomo request adapter, public-query allowlist, current-user DPAPI file store,
  encrypted profile catalog/snapshots, profile generation/revocation gate, signature-gated bundle
  validator/cache, and explicit-save report service. UID requests reject redirects, so the UID stays
  on the player-selected HTTPS service. Saving and revocation are serialized to prevent a late write
  after cleanup.
- Mihomo's documented `player.memory_data` summary values (`level`, `chaos_id`, `chaos_level`) are
  imported as bounded, source-scoped fields with observed timestamps and normal field-level merge
  coverage. The Progress page displays these values under their original source names. It shows the
  three challenge modes as unknown and says missing records do not mean uncleared; no cycle, stage,
  star, score, or full-history mapping is inferred from these summary fields.
- Private object saves reject plaintext JSON above 64 MiB; loads bound the encrypted envelope read
  before DPAPI and independently cap decrypted bytes before JSON parsing. This prevents corrupted
  or unexpectedly large local objects from causing unbounded reads or reaching the decryptor/parser.
- Snapshot reads and writes now hold the lifecycle generation gate through the storage operation.
  A concurrency regression pauses a confirmed-import save, triggers lifecycle revocation, and
  verifies revocation waits for the authorized write then erases it; the old generation cannot
  accept results and no snapshot remains afterward.
- The Mihomo response parser rejects duplicate JSON keys, non-finite constants, invalid UTF-8,
  excessive nesting, and non-object roots. Numeric preview fields exclude booleans, NaN, infinities,
  and overflowing integers so malformed service values cannot enter the encrypted snapshot. The
  network path also requires the response's documented `player.uid` to match the requested UID;
  missing or mismatched identity is rejected before an import preview is created, and the UID is
  never included in the error message or normalized proposal.
- The report page lists saved reports per profile, persists snapshot-expired/evidence-withdrawn
  validity, and displays when online withdrawal state is unknown. It does not manufacture a report
  without a planner result. TaskPage exposes a temporary-report signal; the report page previews it
  and saves only after the user clicks the explicit save action. Report writes and task-preference
  writes serialize with revocation. TaskPage emits this signal only from the explicitly confirmed
  synthetic demo; production task submission remains disabled.
- A local planner subprocess bridge accepts only an explicit argument vector (no shell), sends one
  complete `AnalysisRequest` as UTF-8 JSON through stdin, and validates a single stdout envelope
  declaring protocol version, planner version, capabilities, and result. It enforces request and
  response limits and a timeout, discards stderr, uses no temporary files, and registers the process
  with profile lifecycle so revoke kills it and rejects a late result. It also verifies that returned
  request ID, snapshot revision, and authorization generation match the submitted request.
  Synthetic child-process checks cover a compatible result, missing required capability,
  oversized output, and timeout. B now vendors C's `starhelp_planner` 0.3.0 wheel as a black-box
  artifact pinned by SHA-256 `f7b6c5c221e2491c9399ed76656945175961ac94188b11ad2fe4d4160d0aa0ca`.
  A separate stdio worker calls `analyze_producers` under `starhelp.producers.v0.1`; it checks
  profile/generation/request consistency, retains C's adapter metadata/citations, and emits a bounded
  response consumed by the existing bridge. A signed synthetic A bundle and the current B snapshot
  serializer passed through B's signature validator, the subprocess bridge, and C 0.3.0, returning
  two fixture plans. The Windows candidate now includes `planner-worker/StarHelpPlannerWorker.exe`.
  This is black-box synthetic interoperability evidence only. TaskPage still does not construct or
  submit production analysis requests: no production A signing trust, complete request builder, or
  agreed M0 field/task mapping is available. No real account data was used.
- Public bundle activation now retains the exact incoming bytes when a source returns a byte payload.
  Reloading a cached current/previous release re-runs strict JSON, manifest signature, member hash,
  capability, and dependency checks before returning it. The C fixture replay verifies that the
  signed A export bytes survive B validation, cache activation, restart reload, and worker handoff.
- A verify-before-activate public bundle synchronizer interface and two-version atomic local cache.
  Failed signature verification leaves the current release active. No production transport, trust
  key, or final A-side bundle format is available yet.
- An unsigned Windows folder-style candidate packaging script/spec that collects the bundled
  RapidOCR models and ONNX Runtime. PyInstaller is pinned to 6.22.3. A per-user
  installer validates a file manifest, stages changes, keeps rollback folders, and can restore the
  most recent preserved version.

## Remaining work / verification limits

- Verification on 2026-10-17: 32 standard-library `unittest` cases pass with synthetic fixtures;
  `compileall` passes; current-user Windows DPAPI protect/unprotect round-trip passes with synthetic
  bytes; an offscreen PySide6 window was created; RapidOCR loaded its bundled local models and
  recognized a synthetic screenshot. An offscreen task-form smoke confirmed encrypted per-profile
  save/restore and the explicit planner-unavailable status. No real UID was queried.
- After strict Mihomo response parsing, including excessive-nesting rejection, all 32 tests passed
  again. The rebuilt candidate's 827 manifest hashes matched, the packaged worker replay passed the
  signed fixture, and the app passed an 8-second isolated startup smoke with Qt Core and Widgets
  present. Synthetic installer install, upgrade, two-way rollback, and tamper rejection also passed.
  The actual latest candidate was installed from `dist/StarHelp` into a unique temporary install and
  survived an 8-second isolated installed-path startup smoke.
- Profile revocation now writes an encrypted tombstone before removing its catalog entry. Startup
  filters tombstoned profiles before restoring authorization, then retries deletion of their
  private blobs and temporary data. A synthetic catalog-write failure test verifies restart cannot
  resurrect the profile and that successful cleanup removes its tombstone.
- After adding crash-safe revocation, all 677 entries in a fresh PyInstaller 6.22.3 candidate
  manifest validated, and an 8-second isolated startup smoke confirmed Qt Core and Widgets loaded.
- After adding the pinned C artifact and packaged stdio worker, all 31 standard-library tests passed;
  the exact signed A/B fixture replay passed through the current B validator/serializer, cache
  activation/revalidation, and C worker.
  All 827 files in the new candidate manifest validated, the packaged worker passed the same fixture
  replay, and an 8-second isolated application startup loaded Qt Core and Widgets. The installer smoke
  passed install, upgrade, two-way rollback, and tamper rejection with a synthetic candidate in a
  unique temporary directory; this installer smoke was rerun on 2026-10-17 after rebuilding the
  byte-preserving cache candidate and passed again.
- Duplicate equipment linking was exercised in an offscreen AccountsPage with synthetic records:
  only same-type/slot candidates appeared; the flow required player confirmation and two explicit
  source choices, then persisted one merged instance to the encrypted snapshot.
- Public-profile request callbacks now unregister completed lifecycle tasks on success and failure;
  revoke still cancels requests that remain active. Synthetic lifecycle coverage verifies that a
  finished request is forgotten without dropping cancellation for concurrent active work.
- After this callback cleanup, the candidate was rebuilt with PyInstaller 6.22.3; all 677 manifest
  hashes passed and an 8-second isolated startup smoke loaded Qt Core and Widgets. Offscreen
  AccountsPage callbacks for synthetic success and failure both left no completed task registered.
- The equipment confirmation UI and separately opted-in automatic refresh both compile. The
  automatic refresh test uses only synthetic UID data and verifies consent gating, encrypted
  persistence, restart recovery, attempt timestamps, opt-out deletion, and revoke cleanup. An
  additional test confirms UID redirects are rejected. An offscreen window smoke confirms automatic
  refresh defaults off and the scheduler stays idle; no real UID request was made.
- The report browser was exercised offscreen with one synthetic authorized profile and snapshot.
  A temporary result emitted on the task-to-report signal stayed unsaved until the save button was
  clicked, then appeared in the report list as encrypted local data; no recommendation was shown.
- A fresh PyInstaller 6.22.3 candidate containing these changes was built. All 677 manifest entries
  matched their SHA-256 hashes. The executable remained open for an 8-second startup smoke under an
  isolated temporary `LOCALAPPDATA`, so it could not see or query any real saved profile.
- After adding the local planner subprocess bridge, the candidate was rebuilt again with PyInstaller
  6.22.3. All 677 file-manifest entries revalidated, and an 8-second smoke using a fresh isolated
  `LOCALAPPDATA` confirmed the app remained open and loaded `Qt6Core.dll` and `Qt6Widgets.dll`.
  This packaging smoke does not exercise a planner executable, which is not available.
- After adding the duplicate-equipment confirmation flow, the candidate was rebuilt again with
  PyInstaller 6.22.3. All 677 manifest hashes passed, and the app passed another 8-second isolated
  startup smoke with Qt Core and Widgets loaded.
- The Windows candidate builds with PyInstaller 6.22.3 and includes a SHA-256 manifest plus
  per-user install/rollback script. Installer install/upgrade/rollback and tamper rejection passed
  with synthetic v1/v2 fixtures; the actual candidate was copied and upgraded in a component-local
  temporary directory. An earlier candidate failed to start because PyInstaller discovered
  Poppler's ICU 78.3 through the
  inherited `PATH`; Qt 6.10.3 imports unversioned ICU symbols, while that DLL exports `_78`-suffixed
  symbols. Normal Python loads Windows System32 ICU 72, which exports the required symbols. The build
  script now limits PATH to Windows system directories while PyInstaller analyzes dependencies. A
  rebuilt full candidate has a valid manifest and excludes the incompatible ICU. It started on the
  Windows 11 build machine and loaded both `Qt6Core.dll` and `Qt6Widgets.dll` in an 8-second
  isolated-profile smoke. The actual installer copied this candidate into a component-local
  temporary install; the installed manifest had zero errors, and the installed app loaded Qt Core,
  Qt Widgets, and System32 ICU. The synthetic installer flow also passed install, upgrade, two-way
  rollback, and tamper rejection. This candidate relies on the target Windows system ICU and still
  needs compatibility checks on the intended target Windows environment. A `pyside6-deploy`/Nuitka
  2.7.11 fallback was also attempted; MinGW failed on the repository's non-ASCII path, then a minimal ASCII
  build stalled in SCons with ccache. Disabling ccache exposed a MinGW GCC 14.2 header-search failure
  for `<threadpoollegacyapiset.h>` even though the file exists; no Nuitka artifact is accepted. An
  official embeddable Python imports Qt, but Nuitka repeatedly re-executes when its `._pth` forces
  `site` loading, so that interpreter is not used for packaging. The candidate is unsigned; no
  signed update metadata or publisher identity is present. A prior PySide6 6.12.0 wheel hash mismatch
  was not bypassed; the component uses the verified 6.10.3 wheel instead.
- The API adapter uses the documented `version=v2` response shape. It only imports displayed
  characters and equipped showcase details; undisplayed account inventory remains unknown. The API
  documentation does not define UID-to-region routing, so the selected server label stays local and
  region correctness remains an M0 decision.
- Cross-component planner/backend integration is not performed; no sibling source is imported.
- Equipment identity confirmation and duplicate linking are wired through the desktop UI and
  encrypted snapshot repository. Same-type candidates are never linked automatically, and field
  conflicts stop until the player chooses a source for each value.
- 2026-10-18 parser hardening: public IDs and profile field names are capped at 160 characters and reject control characters; invalid affix identifiers are skipped, and relic slot types must be finite non-boolean integers. All 33 standard-library tests and `compileall` passed. The planner interop fixture passed. A fresh PyInstaller 6.22.3 candidate was built; all 827 manifest hashes matched, required Qt/worker binaries were present, and an 8-second launch in an isolated `LOCALAPPDATA` loaded Qt Core and Widgets. Push remains pending because automatic approval review rejected the previous push attempts; no workaround was used.
- 2026-10-18 structured-import hardening: selected JSON imports read at most 16 MiB plus one byte, reject duplicate keys and non-standard numeric constants, and cap parsed data at 64 nesting levels, 250,000 nodes, and 1,000,000 characters per key/value. Synthetic tests cover depth, duplicates, NaN, and oversize input. All 34 package tests and `compileall` passed; planner interop passed. Rebuilt the unsigned PyInstaller 6.22.3 candidate, verified all 827 manifest hashes, and confirmed an 8-second isolated app startup loaded Qt Core and Widgets.
- Re-ran `tests/Install-Candidate.Smoke.ps1` after the 2026-10-18 candidate rebuild. Synthetic install, upgrade, two-way rollback, and tamper rejection all passed; the script used and removed its uniquely named system temporary directory.
- 2026-10-18 report lifecycle hardening: explicit save now binds validity to the current snapshot revision; a changed revision saves as expired and a missing snapshot saves as needs-review. Known evidence withdrawal and expiration remain monotonic when snapshot data is unavailable. Regression coverage passed with all 34 package tests and `compileall`; planner interop passed. Rebuilt the candidate, verified all 827 manifest hashes, confirmed an isolated 8-second startup, and reran the synthetic install/upgrade/two-way-rollback/tamper smoke successfully.
- 2026-10-18 report/public-bundle lifecycle: report lists and explicit saves now compare the stored release ID with the locally cached release ID. A changed release marks the old report for review while retaining its original release reference; the UI shows the latest cached ID and continues to flag online withdrawal status as unverified. Synthetic regression coverage passed; all 34 package tests and `compileall` passed. Planner interop passed; rebuilt candidate had 827 matching manifest hashes, completed an isolated 8-second startup, and passed synthetic install/upgrade/two-way-rollback/tamper checks.
- 2026-10-18 public-bundle bounds: bundle validation now applies 64 MiB, 64-level, 500,000-node and 1,000,000-character limits to transport bytes and in-memory objects; it rejects cycles, non-finite numbers, oversized integers, and invalid UTF-8/JSON before activation. Regression cases passed; all 35 package tests and `compileall` passed. Planner interop passed. The rebuilt candidate has 827 verified manifest hashes, completed an isolated 8-second startup, and passed install/upgrade/two-way-rollback/tamper smoke.
- 2026-10-18 Windows DPAPI integration: added and ran a Windows-only test using the real current-user DPAPI protector and synthetic data. It verifies the on-disk envelope excludes the plaintext marker and a newly constructed store/protector can restore the value. All 36 tests (including the Windows integration case), `compileall`, and `git diff --check` passed. The candidate executable source is unchanged by this test-only addition.
- 2026-10-18 progress UI: the progress page now keeps a bounded in-session activity history (latest 50 events), while retaining the current status and progress indicator; it writes no activity log to disk. An offscreen Qt regression verified ordering and trimming. All 37 tests and `compileall` passed. Rebuilt the candidate; all 827 manifest hashes matched, planner interop passed, isolated startup remained alive for 8 seconds, and synthetic install/upgrade/two-way-rollback/tamper checks passed.
- 2026-10-18 public UID response binding: the direct network fetch now checks the documented `player.uid` against the explicitly confirmed requested UID and rejects absent/mismatched identities before preview normalization, without echoing either UID. A mocked transport regression covers matching, absent, and mismatched responses; all 38 component tests and `compileall` passed. Rebuilt the Windows candidate; all 827 manifest hashes matched, an isolated 8-second launch loaded Qt Core and Widgets, and synthetic install/upgrade/two-way-rollback/tamper checks passed from a component-local temporary directory after the system temp path denied a rename. No real UID was queried.
- 2026-10-18 public-read cancellation: AccountsPage now offers a cancel button for manual and separately authorized automatic reads. Worker completion, failure, and cancellation signals carry their event token so stale callbacks cannot replace a newer request or revive a canceled preview. An offscreen UI regression checked cancellation feedback, task unregistering, and ignored late callbacks; a synthetic worker regression checked post-fetch cancellation discards the proposal. All 40 component tests and `compileall` passed. Rebuilt the candidate; all 827 manifest hashes matched, an isolated 8-second startup loaded Qt Core and Widgets, and synthetic install/upgrade/two-way-rollback/tamper checks passed. Target-Windows user acceptance remains outstanding.

## M0 blockers, affected flows, and independent work (2026-10-18)

The coordinator confirmed that no complete M0 freeze package exists. These are the concrete missing decisions; the desktop component keeps production integration unavailable until the relevant items are frozen.

| Missing field or rule | Blocked flow | Minimum proposal for coordination | Independent B work that can continue |
|---|---|---|---|
| PublicQuery production route, version, allowlisted fields, and error codes | Discover/fetch a production A release | Freeze one versioned route and request/response/error fixture; reject unknown fields and codes | Keep the current public-query allowlist and synchronization interfaces fail-closed; exercise synthetic transport fixtures |
| Canonical mode, cycle, stage, game-version/environment, entity IDs and source mappings | Map task UI selections to a public stage/template and build AnalysisRequest | A publishes source-backed stable IDs and dated scope fixtures; task selection should then use scope/goal objects read from the verified bundle, not translate Chinese labels locally | Keep task memory encrypted and planner submission disabled without a compatible validated release |
| AnalysisRequest/snapshot contract: field states, coverage/completeness, provenance/time, equipment identity, objective and constraints | Construct B→C production requests and show current/rearrangement/cultivation results in ReportsPage | Freeze a versioned B serializer and request/result fixture, including profile generation and snapshot/release correlation fields | Retain the pinned 045965b synthetic serializer replay as a compatibility fixture; continue UI/storage/import work independent of production mapping |
| Predicate/attribute registry, units, measurement phase/assumptions, and error/withdrawal semantics | Explain planner conditions, hard constraints, and withdrawn evidence without guessing | Freeze registered names, units, context semantics and result/error envelope against C's explicitly versioned adapter API | Preserve unknown conditions and errors, and keep correlation mismatches rejected |
| Production bundle envelope, cross-language canonicalization, signature trust owner/keyring provisioning, rotation and revocation | Verify and activate production public bundles or sync them offline | Coordinate canonical bytes/hash rules and a separately provisioned production trust anchor; test keys remain test-only | Continue signature/hash/dependency/cache/rollback testing only with the signed synthetic fixture |
| Approved source permissions, real mode/stage/entity mappings, and complete authored examples | Production public-query results and representative three-mode/equipment acceptance | A records allowed source/domain/path, rate/freshness/coverage and permission evidence, then delivers explicitly versioned signed fixtures | No real content or source is fabricated; component remains synthetic-only where coverage is absent |
| UID-to-region/service routing semantics and verified showcase coverage | Claim that a confirmed UID/region selects the intended public account or provides complete inventory/history | Confirm official service behavior, supported regions and exact response coverage; otherwise UI must present the limitation and not infer region correctness | Continue direct, consent-gated UID requests with redirects rejected and returned UID bound to the request; no real UID has been queried |
| The pinned `rel_fixture_0001` A delivery contains one mode and no equipment requirements; it cannot exercise three-mode coverage, equipment locks, or ambiguous-instance allocation | Cross-component M4 acceptance for three-mode progress, current equipment plans, and rearrangement between characters | A publishes a new immutable delivery with three distinct synthetic mode datasets, each containing a main, complete alternative, and no-match case. Include public equipment type plus explicit kind/slot/type requirements, and at least one assignment that moves a concrete B-serialized instance between known characters. C consumes that new delivery and reports exercised/not-exercised requirements. Keep the current release and original artifact bytes unchanged | Keep the pinned one-mode replay as a compatibility fixture and continue B's independent identity, lock, merge, and unknown-coverage safeguards |

### Supplemental C bridge error fix (2026-10-18)

C's fixed-source evidence at commit `72ce0b9` reported that its `withdrawn_public_object` domain error omitted snapshot/generation correlation. B's stdio worker now fills only missing request ID, snapshot revision, and authorization generation from the already validated desktop wrapper; any correlation values returned by C remain untouched and are still checked by the parent bridge. A regression exercises the signed A fixture through the current B source bridge and bundled worker, verifies the structured withdrawal error and correlation tuple, and retains the existing mismatch-rejection tests. All 40 component tests pass; `compileall` and `git diff --check` pass.

### C bridge report version comparison (2026-10-18)

C's later machine report `c-0.3.0-b-86fafdd-source-bridge.json` still fails the withdrawn-evidence case because it extracts B host commit `86fafdd`, which predates B fix `60b7c99` (`Preserve planner domain error correlation`). The reported missing `snapshot_revision` and `authorization_generation` therefore describe that historical host snapshot, not current `codex/mvp-desktop-account` (`7e9f30c`). Re-running `python -m unittest discover -s tests -p test_planner_interop.py -v` in the current component passed; its bundled-worker branch is present and checks the withdrawn error code, request ID, snapshot revision, and authorization generation. The pinned `045965b` snapshot serializer remains unchanged. C should rerun its bridge harness against current B host source before treating the withdrawn-error case as a current integration failure.

The rebuilt unsigned PyInstaller 6.22.3 candidate has 827 SHA-256 manifest entries, all verified. An isolated 8-second startup loaded Qt6Core.dll and Qt6Widgets.dll. The actual candidate was also installed to a unique temporary path under the component build directory; the installer verified and copied all 827 manifest entries. The synthetic installer smoke passed install, upgrade, two-way rollback, and tamper rejection. An additional installed-path startup attempt did not yield a usable result and is not counted as passed; the directory-candidate isolated startup did pass. Temporary installation files were removed. This does not constitute production A trust, target-machine acceptance, real-account acceptance, or complete MVP approval.

### Producer request builder (2026-10-18)

Added `starhelp_desktop.producer_request` as the B-owned request construction seam for the pinned C producer adapter. `select_public_task` takes stage scope and public goal directly from a validated bundle's planner view by exact IDs; absent, ambiguous, cross-release, or mismatched mappings fail closed. `build_producer_analysis_request` preserves original signed A bytes, serializes the supplied B snapshot, hashes both byte sequences, and requires explicit A/B producer commits, format profiles, distribution trust purpose/key material, and active authorization generation. It does not access the network, choose production trust, or persist data. The A/B/C synthetic replay test now exercises this shared builder, including an unavailable stage rejection; all 40 component tests and `compileall` passed. Ruff was not installed in the component venv.

This is a request builder only; at this point in the work TaskPage had not been wired to submit it. The public mode/stage/goal mapping, production trust configuration, serializer/request contract, and complete coverage cases remain M0 blockers. Regular UI task creation stores only an encrypted goal draft and does not analyze or recommend.

### Synthetic analysis-to-report orchestration (2026-10-18)

Added `starhelp_desktop.analysis.ProducerAnalysisRunner` to call `LocalPlannerProcess` under the selected profile authorization and produce an `AnalysisReport` only for `plans_available`. The unsaved report retains the planner result/citations and binds the exact snapshot revision, bundle release, and planner version. Citation IDs/revisions are retained as report references; malformed or cross-release citation data fails closed. No result is persisted by the runner; the existing explicit-save lifecycle remains the only persistence path. The signed A bundle + pinned B synthetic snapshot + C 0.3.0 test now exercises request construction, local planning, temporary report creation, explicit save, and report reload. All 40 package tests, `compileall`, and `git diff --check` pass.

The orchestration is available as a component seam. Production UI execution still requires frozen M0 mappings, snapshot/request semantics, and provisioned production trust; do not treat this synthetic replay as a production or complete MVP flow.

### Refreshed candidate evidence (2026-10-18)

Exported the request builder and analysis runner from the component package root so PyInstaller includes them. Rebuilt the unsigned candidate with PyInstaller 6.22.3; its manifest contains 916 files and every SHA-256 entry verifies. PyInstaller archive inspection confirms `starhelp_desktop.analysis` and `starhelp_desktop.producer_request` are present. An isolated 8-second launch loaded Qt6Core.dll and Qt6Widgets.dll. The installer smoke initially hit Access denied moving a staging directory under the sandbox system temp path; the run left no residual smoke directory. Re-running with TEMP/TMP scoped to the component build directory passed install, upgrade, both rollback directions, and tamper rejection. This remains an unsigned candidate; target-machine acceptance, publisher signing and production M0 remain outstanding.

### Explicit synthetic TaskPage demo (2026-10-18)

TaskPage now exposes “运行合成联调演示（仅 fixture）” as a distinct button. It asks before creating
or reusing a separately labeled encrypted synthetic profile, reads only the three bundled
`producer-interop-v1` fixtures, checks their pinned SHA-256 values, validates the A bundle with its
fixture-only Ed25519 key, selects exact stage/template/goal IDs from that signed bundle, and stores
those canonical IDs as the demo profile's encrypted last-task draft. It never loads the currently
selected profile snapshot and has no network client. The B snapshot, task request, and planner run
stay within the local subprocess path. Analysis runs on a Qt worker; eligible results reach the
existing report preview and remain unsaved until the user clicks the explicit save button. Pending
and saved report labels carry a persistent `synthetic_demo` marker and visibly say “仅合成 fixture”.
The demo profile appears in Accounts and can be revoked there. The frozen app packages these
fixtures under `demo-fixtures/`.

The PublicKnowledge page now lists cache pointer/releases, bounded coverage and freshness metadata
declared inside each cached bundle, and the local cache-file modification time. It labels those
fields as unverified display metadata, not proof that the bundle is valid; malformed cache data is
flagged and is not enabled. Cache activation and successful current/previous release revalidation
write an unsigned local receipt containing the verification time and SHA-256 of the exact cached
bytes. The page displays that timestamp only when the receipt's content digest still matches; a
missing/altered payload makes the receipt unknown/mismatched. The receipt is informational and is
not a publisher signature. Production trust is not provisioned, and latest withdrawal/disable
status remains unknown while offline. Cached bundle and local receipt reads are bounded before
JSON parsing. Usable analysis inputs must still pass `PublicBundleSynchronizer` signature, hash,
capability, and dependency revalidation. This improves offline status without claiming an
unavailable production sync or revocation feed.

An offscreen PySide6 regression clicks the demo button with synthetic approval, waits for the local
C 0.3.0 worker result, confirms a distinct `synthetic-demo` profile and a staged report, verifies the
encrypted report store remains empty before explicit save, and confirms one report exists after the
save click. No real profile, UID, or network request is involved. This makes a visible end-to-end
synthetic substitute available while M0 remains `0.1-draft`; it does not enable production task
mapping, trust, source coverage, or MVP acceptance.

Verification on 2026-10-18: all 47 package `unittest` cases pass; `compileall` and `git diff --check`
pass. A fresh PyInstaller 6.22.3 candidate has 919 manifest entries and all hashes match; archive
inspection contains `starhelp_desktop.analysis`, `starhelp_desktop.producer_request`, and
`starhelp_desktop.synthetic_demo`, while `_internal/demo-fixtures/` contains the pinned A bundle,
synthetic B snapshot, and fixture public key. The packaged planner worker is present. An isolated
8-second startup under a new `LOCALAPPDATA` stayed alive and loaded Qt6Core/Qt6Widgets. Synthetic
installer install, upgrade, both rollback directions, and tamper rejection passed with TEMP/TMP in
a component-local temporary directory. Cache receipt digest matching/tamper behavior and bounded
pre-parse cache/receipt reads are covered by regressions. OCR screenshot file reads are also bounded
before decode, with empty and over-limit file regressions. Private object write, encrypted-envelope
read, decrypted-size, and late-snapshot-write revocation limits have dedicated regressions. The
candidate remains unsigned; production M0,
publisher signing, target-Windows acceptance, and real-account acceptance remain outstanding.

### Report reference validation follow-up (2026-10-18)

`ProducerAnalysisRunner` now also requires the planner result's release ID to equal the submitted bundle release and every citation `{id, revision}` to resolve to that exact release's evidence catalog before staging a report. A withdrawn-public-object result is routed through the runner and verified to produce no temporary report. All 40 component tests, `compileall`, and `git diff --check` pass. The frozen candidate was rebuilt after this code change: all 916 manifest hashes match, PyInstaller archive contains both integration modules, isolated 8-second Qt startup passes, and the synthetic install/upgrade/two-way-rollback/tamper smoke passes with TEMP/TMP inside the component build directory. This still does not connect TaskPage to production data or remove the M0 blockers.

### Fresh local verification (2026-10-18)

On the current B source, all 47 package tests passed, `compileall` passed, and `git diff --check`
passed. An additional offline OCR runtime check generated a synthetic PNG in memory, ran the
packaged RapidOCR models locally, recognized the synthetic label, and redacted its 8-digit
fixture value as `[UID 已隐藏]`; no user image or network request was used. The existing unsigned
Windows candidate manifest was independently rechecked: all 919 listed SHA-256 values match and
the candidate file set is exact. These checks do not resolve production M0 mappings/trust, complete
three-mode equipment fixtures, publisher signing, or real-account/target-machine acceptance.

### OCR profile lifecycle isolation (2026-10-18)

AccountsPage now binds screenshot OCR to the selected profile ID and authorization generation,
registers the background recognition as lifecycle work, and drops mapped OCR drafts when the user
switches profiles or revokes authorization. The worker checks cancellation both before and after
recognition, releases its image reference, and never emits a late candidate after cancellation.
Saving a preview also requires its captured profile generation to remain active. Synthetic Qt
regressions cover cancellation during recognition, profile switching, and revoke cleanup.

Verification after this source change: all 49 package tests, `compileall`, and `git diff --check`
passed. A fresh PyInstaller 6.22.3 candidate has 919 manifest entries with exact hashes/file set
and stayed alive for an 8-second startup under isolated `LOCALAPPDATA`. Installer install,
upgrade, two-way rollback, and tamper rejection passed with TEMP/TMP scoped under the component
build directory after the system temp path denied a staging move. The candidate remains unsigned;
production M0, publisher signing, target-Windows acceptance, and real-account acceptance remain
outstanding.

### Public profile request switch isolation (2026-10-18)

AccountsPage now cancels a manual or authorized automatic public-profile request immediately when
the selected profile ID or authorization generation changes. It finalizes the old lifecycle task,
clears pending profile data, and leaves late completion/failure callbacks unable to replace the
new profile's page. A synthetic Qt regression covers switching during an in-flight request and
asserts that a late proposal and failure remain discarded.

Verification after this source change: all 50 package tests, `compileall`, and `git diff --check`
passed. A fresh PyInstaller 6.22.3 candidate has 919 manifest entries with exact hashes/file set
and stayed alive for an 8-second startup under isolated `LOCALAPPDATA`. Installer install,
upgrade, two-way rollback, and tamper rejection passed with TEMP/TMP scoped under the component
build directory. The candidate remains unsigned; production M0, publisher signing, target-Windows
acceptance, and real-account acceptance remain outstanding.

### Bound import preview profile isolation (2026-10-18)

When a structured, manual, OCR, or public-profile import preview is bound to a profile ID and
generation, switching to a different profile now clears that preview and disables its save action.
Unbound local previews remain available for a later explicit profile choice. A synthetic Qt test
switches between two independent local profiles while a structured import is pending and verifies
the preview is removed without writing either profile snapshot.

Verification after this source change: all 51 package tests, `compileall`, and `git diff --check`
passed. The rebuilt PyInstaller 6.22.3 candidate has 919 manifest entries with exact hashes/file
set and stayed alive for an 8-second startup under isolated `LOCALAPPDATA`. Installer install,
upgrade, two-way rollback, and tamper rejection passed with TEMP/TMP scoped under the component
build directory. The candidate remains unsigned; production M0, publisher signing, target-Windows
acceptance, and real-account acceptance remain outstanding.

### Mihomo progress summary and three-mode status (2026-10-18)

The public profile preview now preserves only the named nonnegative integer `player.memory_data`
fields `level`, `chaos_id`, and `chaos_level` as source-scoped facts. The Progress page selects an
authorized local profile, displays these values with their original source names and observation
times, and keeps Memory of Chaos, Pure Fiction, and Apocalyptic Shadow separately marked unknown.
It says missing records do not mean uncleared and refreshes its profile selection on page entry so
revoked profile data is removed from view. No cycle, stage, star, score, or historical coverage is
inferred. The field names were checked against the official Mihomo models at commit
`008b91bfe8c0e2daca0ab69061efd9ea1ad71bd2`; no real UID or live public profile was queried.

Verification: all 52 package tests pass; `compileall` and `git diff --check` pass. A fresh unsigned
PyInstaller 6.22.3 candidate contains 919 files and its SHA-256 manifest matches the exact file set.
The app remained alive for an 8-second launch under isolated `LOCALAPPDATA`. Synthetic installer
install, upgrade, two-way rollback, and tamper rejection pass with temp data under the component
build directory. Three-mode current-cycle coverage, M0 IDs and source mapping remain incomplete.

The progress-page Qt regression also now exercises the real hide/revoke/show path: after profile
revocation on another page, the next page entry reloads the profile list and removes the old summary
from view. The full 52-test suite, `compileall`, and `git diff --check` passed; this follow-up changes
only test coverage and handoff evidence, so the previously verified application candidate is unchanged.

### Task and report page revocation refresh (2026-10-18)

TaskPage and ReportsPage now reload their profile selection when shown. This clears stale task fields,
saved report rows, rendered report details, and pending report state after authorization is revoked
while the user is on another page. A synthetic Qt regression exercises the hide/revoke/show sequence.

Verification: all 53 package tests, `compileall`, and `git diff --check` pass. The rebuilt unsigned
PyInstaller 6.22.3 candidate has 919 manifest entries whose hashes and file set match exactly. The
app remained alive for an 8-second startup under isolated `LOCALAPPDATA`; synthetic installer
install, upgrade, two-way rollback, and tamper rejection pass with temporary data under the
component build directory. Production M0 mappings/trust, publisher signing, target-Windows
acceptance, and real-account acceptance remain outstanding.

### Unsaved report validity refresh (2026-10-18)

An unsaved report preview is now reassessed whenever the Reports page refreshes. If its profile's
snapshot revision changed, the preview is immediately labelled expired with the reason; a changed
local public release is labelled as needing review. The assessment is in-memory only and does not
persist the report. A synthetic Qt regression verifies that a pending report changes from current
to expired as soon as a second confirmed import advances the snapshot.

Verification: all 54 package tests pass, including the new pending-preview regression;
`compileall` and `git diff --check` pass. The rebuilt unsigned PyInstaller 6.22.3 candidate has 919
manifest entries with exact hashes and file set, stayed alive for an 8-second startup under isolated
`LOCALAPPDATA`, and passed synthetic installer install, upgrade, two-way rollback, and tamper
rejection. Production M0 mappings/trust, publisher signing, target-Windows acceptance, and
real-account acceptance remain outstanding.

### Task equipment lock selection (2026-10-18)

TaskPage now opens a multi-select picker populated only from the selected authorized profile's
current equipment snapshot. Each choice shows slot, public type, owner, identity state, and local
instance ID. Unconfirmed identities may be locked for the current record but are not thereby
eligible for cross-character rearrangement. Task creation rechecks selected IDs against the current
snapshot and refuses stale or arbitrary IDs. A synthetic Qt regression verifies selection, encrypted
task preference persistence, and rejection without overwriting the previous task when an ID is stale.

Verification: all 55 package tests pass; `compileall` and `git diff --check` pass. A rebuilt unsigned
PyInstaller 6.22.3 candidate has 919 manifest entries with exact hashes and file set, stayed alive
for an 8-second startup under isolated `LOCALAPPDATA`, and passed synthetic installer install,
upgrade, two-way rollback, and tamper rejection. Production M0 mappings/trust, publisher signing,
target-Windows acceptance, and real-account acceptance remain outstanding.

### Profile-backed character constraints (2026-10-18)

TaskPage now provides snapshot-backed pickers for fixed and excluded characters. The fixed-character
picker allows selection only for ownership entries explicitly marked `owned`; other recorded states
are shown disabled, and characters absent from the snapshot are not inferred as unowned. The
excluded-character picker shows the ownership state for each recorded ID. Both selections remain
profile-scoped encrypted task preferences. A synthetic Qt regression verifies the owned-only fixed
choice, explicit not-owned exclusion, and task persistence.

Verification: all 56 package tests pass; `compileall` and `git diff --check` pass. The rebuilt
unsigned PyInstaller 6.22.3 candidate has 919 manifest entries with exact hashes and file set, stayed
alive for an 8-second startup under isolated `LOCALAPPDATA`, and passed synthetic installer install,
upgrade, two-way rollback, and tamper rejection. Production M0 mappings/trust, publisher signing,
target-Windows acceptance, and real-account acceptance remain outstanding.

### 规划报告分区展示（2026-10-18）

ReportsPage 将 planner result 按分析范围、当前配装、调装、待确认候选、未采用原因、覆盖/时效/降级、公共证据引用和排障建议分区；方案对象保留完整 JSON，并把方案中的培养步骤、成本和材料缺口另行汇总。所有未识别的顶层规划器字段继续显示在“其他规划器字段”，没有返回的章节不臆造。保存报告与未保存预览共用此呈现逻辑；合成 Qt 回归覆盖范围、配装、培养与引用章节。

验证：56 项 package unittest、compileall、diff-check 通过。重建 unsigned PyInstaller 6.22.3 候选包，919 项 SHA-256 与完整文件集合一致；隔离 LOCALAPPDATA 启动 8 秒并加载 Qt6Core/Qt6Widgets；合成安装、升级、连续双向回滚和篡改候选拒绝通过。生产 M0 映射/签名信任、发布者签名、目标 Windows 和真实账号验收仍待完成。

### Mihomo V2 endpoint alignment（2026-10-18）

The public-profile client now requests the documented V2 default with only `lang`; it no longer adds the undocumented `version=v2` query. MetaCubeX/mihomo's upstream [README](https://github.com/MetaCubeX/mihomo#basic) shows V2 without a version parameter and uses `version=v1` only for V1; its client likewise adds only the language for the default request. A synthetic transport assertion locks the exact URL and continues checking UID echo matching. No live UID was queried; provider authorization, region mapping and source coverage remain M0/user acceptance items.

Verification: all 56 package tests pass; `compileall` and `git diff --check` pass. Candidate rebuild and frozen-package checks are recorded after this source change below.

Rebuilt the candidate after this URL correction. The 919-file SHA-256 manifest matches the exact candidate file set; isolated 8-second startup loaded Qt6Core/Qt6Widgets; synthetic install, upgrade, two-way rollback and tamper rejection passed. No real UID request was made.

### M0/M6 生产集成待输入清单（2026-10-28 更新）

以下记录 B 当前真实阻塞及所需输入。S3/B2 已完成合成技术回放；这不等于生产来源、映射或数据覆盖已验收。此清单不改变共同契约、A/C 文件或固定测试产物。

| B 流程 | 当前限制 | 最小所需决定/产物 |
|---|---|---|
| TaskPage 生产分析 | 已能从同一签名 S3 fixture 选择规范 task 并通过 C 0.4.0；真实任务仍无游戏版本/环境/模式/周期/关卡/目标映射，UI 标签不能推导这些 ID | A/内容维护方确认真实且获准发布的 ID、修订、目标语义及适用期；B/C 对照当期人工审核样例。生产内容批准仍需明确人工审阅 |
| Progress 三模式 | Mihomo 只提供展示字段及有限进度摘要，不证明完整历史、星数、周期或未展示模式；当前没有生产 `mode_records` 映射 | 获准来源字段、三模式实际 ID/覆盖/更新时间及固定样例；缺失记录继续显示 unknown，不填零或推断通关 |
| 公共包同步与撤回 | B 已有签名校验、双版本缓存、原子激活/回滚与最新已知撤回处理；尚无接入 A 的生产发现/下载/撤回 transport，也无生产公钥配置 | A 提供受支持的服务接口与原始字节/摘要/签名/撤回 freshness 规则；协调确定独立信任锚 provisioning、key rotation 和离线状态。测试 key 只用于 synthetic-test |
| UID 公开档案 | 已有明确确认后直接读取 Mihomo、UID 回显匹配、重定向拒绝及预览；未查询真实 UID，服务覆盖和区服映射未认证 | 确认允许使用的来源/许可、精确端点和字段覆盖、区服映射、限流/失败语义。目标账号只能由用户主动提供并在本机明确授权后查询 |
| 本地服务/邀请维护 | SettingsPage 明确显示服务 lifecycle 和邀请维护未接通；A 当前为本地 CLI/WSGI，没有共享部署可供 B 验收 | A 提供部署目标、start/stop/health、身份提供方、邀请/read-only 权限 provisioning、TLS/ACL/审计及 secret distribution 方案，再做本机到服务联调 |
| S3 技术 replay 与数据覆盖 | B 源与打包 worker 对 C 固定捕获匹配 21/21。C 最新 packaged report `c-0.4.0-b2-c248daa-packaged-comparison-v2.json`（C `fa512b6`，blob `174fa9b57a5b7c35a765c900d9429794db7eebf6`）记录 83 checks passed、0 failed、62 worker cases，包含 B2 builder、source worker 与 Windows worker；报告为 synthetic-only。报告仍标 `full_M0_acceptance=false`、candidate source provenance/publisher trust 未建立，并将完整库存/材料正向计算、最终面板正向计算列为未覆盖。当前 AccountSnapshot 不表达这些完整来源语义 | 保留 C 报告为跨组件合成证据，不把它升级为 M0 或生产验收。若要验证完整库存/材料正向计算或最终面板，先提出版本化 schema/profile/capability 扩展并由 A/B/C 确认，再实现对应输入和可核验期望；不得在当前 profile 下伪造完整覆盖 |

当前技术集成元组为 A producer `0.3.0` / release `rel_fixture_s3_0001`、B1 serializer `103741e02c90ac672017f783058bdd8dacae982e`、B host B2 `c248daab22255a069464a6d277757d01df5d49f3`、C wheel `0.4.0` / native rules `0.2.0`。共同生产契约仍为 `0.1-draft`；固定技术接口只覆盖合成回放。内容许可/人工批准、生产 signing trust、在线服务部署、完整材料/面板表示、发布签名、目标 Windows 和真实账号验收分别保持独立关口。

### UID/区服编辑后重置公开查询同意（2026-10-18）

AccountsPage 的公开档案同意现绑定到当时展示的 UID 与区服：编辑任一字段会立即撤销勾选，并提示重新确认服务来源、查询用途和数据范围，避免把针对旧 UID/区服的同意沿用到新请求。新增合成 Qt 回归覆盖已勾选后分别修改 UID 和区服的情形。

本轮验证：57 项 package unittest、`compileall` 与 `git diff --check` 通过。重建的 unsigned PyInstaller 候选包 919 项 SHA-256 与完整文件集一致；隔离 `LOCALAPPDATA` 启动 8 秒并加载 Qt6Core/Qt6Widgets；合成安装、升级、双向回滚和篡改拒绝通过。没有查询真实 UID。候选仍未签名；生产 M0 映射/信任、完整三模式和装备 fixture、目标 Windows 与真实账号验收仍未完成。

### Mihomo 响应复杂度限制（2026-10-18）

公开档案响应在 4 MiB 传输上限之外，现在还限制解码 JSON 的最大嵌套深度、节点数和单字符串长度；校验使用迭代遍历，超限统一报告为响应复杂度错误，避免未经约束的服务端 JSON 在本机归一化前造成高内存/CPU 消耗。新增合成回归分别覆盖节点数、深度和字符串长度边界。

本轮验证：58 项 package unittest、`compileall` 与 `git diff --check` 通过。重建 unsigned PyInstaller 候选后，919 项 SHA-256 与完整文件集一致；隔离 `LOCALAPPDATA` 启动 8 秒并加载 Qt6Core/Qt6Widgets；安装/升级/双向回滚/篡改拒绝 smoke 通过。重建后再次运行固定 A 签名 fixture + B snapshot + 打包 C worker 回放，`plans_available` 与 withdrawal 拒绝路径均通过。未发起真实 UID 请求。生产 M0 映射/信任、完整三模式和装备 fixture、发布者签名、目标 Windows 与真实账号验收仍未完成。

### 窗口退出时取消后台任务（2026-10-18）

主窗口关闭时停止公开档案自动刷新计时器，并通过 `ProfileLifecycle.begin_shutdown()` 原子地封闭新任务登记、向所有已注册的公开读取/OCR/本地规划任务发送取消信号。这样也覆盖窗口关闭与 worker 首次登记之间的竞态。取消只停止本次工作，不撤销授权，也不删除加密档案；正在传输的公开请求是否已被服务处理仍按页面提示处理。

本轮验证：59 项 package unittest、`compileall` 与 `git diff --check` 通过；新增 Qt 回归验证窗口关闭触发任务取消、拒绝关闭后的新登记、停止计时器且档案授权/目录保留。重建 unsigned PyInstaller 候选的 919 项哈希与文件集一致，隔离启动加载 Qt6Core/Qt6Widgets，安装/升级/双向回滚/篡改拒绝 smoke 通过；固定签名 fixture + B snapshot + 新打包 C worker 的正常规划与 withdrawal 错误回放通过。生产 M0/服务部署、签名、目标机和真实账号验收仍未完成。

### 固定角色任务约束绑定档案快照（2026-10-18）

TaskPage 创建任务前现会重新读取当前授权档案快照，并要求每个固定角色 ID 明确具有 `owned` 状态；未拥有、未知、过期档案或没有快照均拒绝，且不会覆盖之前保存的有效任务。角色选择框的文字也改为提示必须来自 `owned` 快照记录。此检查防止直接编辑文本框绕过只允许确认拥有角色的选择器。

验证：59 项 package unittest、`compileall`、`git diff --check` 通过。重建候选包的 919 项 SHA-256 与完整文件集一致，隔离启动加载 Qt6Core/Qt6Widgets，安装/升级/双向回滚/篡改拒绝 smoke 通过；固定 A 签名 fixture + B snapshot + 新打包 C worker 回放通过。M0 映射/信任和其他生产/人工验收门槛仍未完成。

### 结构化导入保留装备字段事实（2026-10-18）

`starhelp.account-import` `0.1-draft` 现在接受装备条目的可选 `facts` 对象。每项必须是受限本地字段路径及显式 `value`，可带字符串 `scope`；生成的事实保留导入来源和观测时间，状态为 `needs_review`，仍须玩家确认后才合并。装备类型、槽位和持有者标识均拒绝格式错误、控制字符、超长值与 UID-like 内容，装备事实路径拒绝 `uid`。`ImportPreview.raw_field_count` 现计入装备事实。物品实例身份继续保持 `unconfirmed`，不会从类型 ID 推断。

合成回归覆盖来源/时间/scope/待确认语义，以及损坏事实、UID 路径和 UID-like 装备标识拒绝。该格式仍是本地草案，不代表生产来源字段映射已冻结。

本轮验证：61 项 package unittest、`compileall` 与 `git diff --check` 通过；独立 A 签名 fixture + B snapshot + 打包 C worker 回放通过。重建 unsigned PyInstaller 6.22.3 候选后，919 项 SHA-256 与实际文件集合完全吻合；隔离 `LOCALAPPDATA` 启动 8 秒并加载 Qt6Core/Qt6Widgets；合成安装、升级、双向回滚和篡改拒绝通过。未查询真实 UID。M0 映射/信任、发布签名、目标 Windows 与真实账号验收仍未完成。

### 装备事实在确认前可见（2026-10-20）

AccountsPage 的结构化导入预览现在逐件展示槽位、公共类型 ID、持有者、本地实例 ID 与身份状态，并逐字段展示装备事实值、待确认状态、来源、观测时间和范围。预览明确说明公共类型 ID 不等于副本身份，支持玩家在确认合并前检查字段和身份歧义。合成 Qt 回归锁定上述展示内容。

验证：62 项 package unittest、`compileall` 与 `git diff --check` 通过。新建 unsigned PyInstaller 6.22.3 候选的 919 项 SHA-256 与完整文件集合吻合；隔离 `LOCALAPPDATA` 启动 8 秒并加载 Qt6Core/Qt6Widgets。合成安装、升级、双向回滚、篡改拒绝和 A 签名 fixture + B snapshot + 打包 C worker 回放均通过。过程中首次构建会话句柄在上下文切换后不可读取；检查确认没有构建进程且 dist 未更新，随后从干净构建重跑成功。未查询真实 UID。

### S3 B2 planner integration and candidate (2026-10-21)

B2 source commit `c248daab22255a069464a6d277757d01df5d49f3` pins the official C 0.4.0 wheel
byte-for-byte (SHA-256 `3b5b8de8f2ef71cd07f1cfb7724cb0a1564f316860232b58728386d52c47aea2`) and adds
the immutable S3 bundle, synthetic B1 snapshot, equipment type table, and test-only public key.
The fixture provenance is A producer `dcb1e3ee220b85229bedc6c79d72ebe495825f37`, B1 serializer
`103741e02c90ac672017f783058bdd8dacae982e`, profile
`starhelp.desktop.snapshot.interop-min.v0.1`, release `rel_fixture_s3_0001`, and C's committed
0.4.0 lock at `parallel/local-planner/packages/starhelp-planner/artifacts/starhelp_planner-0.4.0.lock.json`
(SHA-256 `f18a85dbb1258d76917e14566b8be0ed3f7e9e61adbc953d25e301e7603297d5`). B2 keeps the
protected B1 serializers unchanged. The synthetic demo explicitly permits equipment rearrangement;
the confirmation and progress copy disclose that behavior and the fixture-only result.

The package suite passes all 65 tests, including signed S3 bundle validation, raw snapshot byte
preservation, exact task scope checks, explicit report save, withdrawn-evidence rejection, report
correlation, GUI synthetic demo staging, and revocation cleanup. B's real `LocalPlannerProcess`
replayed the 21 committed C capture wrappers through the pinned vendor wheel. The packaged
`StarHelpPlannerWorker.exe` replayed the same 21 cases. In both runs, status, available variant IDs,
and pending variant IDs matched C's installed-wheel report 21/21. A separate packaged withdrawal
run returned correlated `withdrawn_public_object` and produced no temporary or saved report.

| Capture | Status | Available | Pending | Rejected |
|---|---:|---:|---:|---:|
| `stage-0-ambiguous_move` | `confirmation_required` | 0 | 2 | 0 |
| `stage-0-complete_alternate` | `plans_available` | 1 | 0 | 1 |
| `stage-0-locked_move` | `confirmation_required` | 0 | 2 | 0 |
| `stage-0-main_current_equipment` | `plans_available` | 2 | 0 | 0 |
| `stage-0-missing_fields` | `plans_available` | 2 | 0 | 0 |
| `stage-0-normal` | `plans_available` | 2 | 0 | 0 |
| `stage-0-not_owned` | `no_feasible_variant` | 0 | 0 | 2 |
| `stage-0-player_confirmed_move` | `plans_available` | 2 | 0 | 0 |
| `stage-0-same_type_distinct_instance` | `plans_available` | 2 | 0 | 0 |
| `stage-0-source_confirmed_move` | `confirmation_required` | 0 | 2 | 0 |
| `stage-0-unknown_ownership` | `confirmation_required` | 0 | 2 | 0 |
| `stage-1-complete_alternate` | `plans_available` | 1 | 0 | 1 |
| `stage-1-missing_fields` | `plans_available` | 2 | 0 | 0 |
| `stage-1-normal` | `plans_available` | 2 | 0 | 0 |
| `stage-1-not_owned` | `no_feasible_variant` | 0 | 0 | 2 |
| `stage-1-unknown_ownership` | `confirmation_required` | 0 | 2 | 0 |
| `stage-2-complete_alternate` | `plans_available` | 1 | 0 | 1 |
| `stage-2-missing_fields` | `plans_available` | 2 | 0 | 0 |
| `stage-2-normal` | `plans_available` | 2 | 0 | 0 |
| `stage-2-not_owned` | `no_feasible_variant` | 0 | 0 | 2 |
| `stage-2-unknown_ownership` | `confirmation_required` | 0 | 2 | 0 |

Counts are B-adapter result arrays; C's report exposes its native `available` projection with a
different shape. Both B runs compared complete available/pending variant identities as well as
status. C's packaged comparison at `fa512b6` now includes B2 and records 83 passed checks across
62 worker cases with zero failures. Its `not_exercised` list still includes production source,
content and trust acceptance, positive complete inventory/material calculations, and final-loadout
panel calculations.

The single post-B2 PyInstaller build used Python 3.12.14 and PyInstaller 6.22.3. The candidate has
920 manifest entries; the manifest hash is
`30e4820db6b3a97b193b29b225591758a1e424828b8f55be6094c68046bc19c3`, `StarHelp.exe` hash is
`0370b6f93e095dbb59d22758c5fa1d50abfce7989ab9971d03726acbbdd91dc9`, and packaged worker hash is
`989c0a8ee1abf73bd99db9b50722990d3a4e728ec6b038814b44dcdd7a260f9a`. The manifest's exact file
set and all hashes were independently checked, and the four embedded S3 fixtures match their
pinned digests. The app stayed alive for an 8-second launch with isolated `LOCALAPPDATA`. Synthetic
installer install, upgrade, two-way rollback, and tamper rejection passed. The local verification
record is `packages/starhelp-desktop/build/candidate-verification-2026-10-21.txt` (SHA-256
`c448ba6553c8fda45a253e802c42cca3030145b1db570e4d351d4e0149abe1b3`).

This advances the synthetic B2 integration only. The candidate is unsigned; production mode/task
mapping, production signing trust and revocation transport, publisher signing, target-machine
review, and real-account acceptance remain open. No real UID or account was queried.

## S4.1 A→B production integration interface review (2026-10-28)

Read-only review of A's proposal at commit `ed0028c7e3a3ce00929cf7ae3db939cb137ced06`
(`production-integration-proposal-v0.1-draft.md`, blob
`b6e09bdbfc2ea770bbcdb17940ea11ae0111a2fb`). The B-side review is in
[`s4-1-integration-review.md`](../../packages/starhelp-desktop/docs/s4-1-integration-review.md).
The agreed product sequence stays two-stage: a B-managed A process bound to loopback for the
first Windows MVP, then shared HTTPS A managed by its host for the second stage. This review
does not freeze wire fields or freshness windows and does not change S3/B1 artifacts.

Code inspection confirmed B currently has a generic `PublicBundleSource` returning only release ID
and object/bytes, a synchronizer that checks bundle signature/capabilities/closure, and an atomic
two-release cache. It has no signed catalog/withdrawal validation, freshness enforcement, explicit
rollback API, HTTPS source, or A process controller. The local verification receipt is unsigned and
only binds cached bytes to a local timestamp. The review records the missing catalog tuple, signed
sequence/expiry/withdrawal fields and errors, plus readiness, process ownership, loopback and staged
HTTPS boundaries. This is a design review only; no production HTTP or service process was started,
and no A/C source, shared contract, S3 fixture, B1 serializer, or candidate was modified.

Current B package verification on 2026-10-28 used the component `.venv`: all 65 `unittest` cases
passed, and `python -m compileall -q src tests` completed successfully. These checks cover the
current checkout only; no candidate was rebuilt. GitHub branch inspection found A still at the
reviewed `ed0028c` proposal and C advanced to `fa512b6` with preserved S3 packaged replay evidence;
neither publishes a frozen S4.1 catalog/withdrawal protocol. Production transport and controller
implementation therefore remain pending the shared interface freeze.

### Review of A's local S4.1 contract candidate (2026-10-28)

Read-only review of A local commit `243a9e04a243124a75d76efc4a20edb989c8eaec`,
[`public-distribution-local-service-contract-candidate-v0.1.md`](../../../knowledge-backend/packages/starhelp-knowledge/docs/public-distribution-local-service-contract-candidate-v0.1.md).
This commit is not the current GitHub A branch head (`ed0028c`) and is not a frozen shared
interface. B agrees with the proposed stage topology, strict catalog/revocation signatures,
exact A/B/C tuple, immutable raw-byte digest, bounded download, explicit rollback, and readiness
split. The detailed field-by-field review is in
[`s4-1-integration-review.md`](../../packages/starhelp-desktop/docs/s4-1-integration-review.md).

The material difference is transaction ordering: candidate section 4 currently commits catalog
and revocation high-water only with successful artifact activation, so an artifact download or
verification failure could discard an already authenticated newer revocation. B requests A to
split durable catalog/revocation safety checkpoints from the later artifact pointer transaction;
persist authenticated catalog replay state and a fully verified revocation checkpoint before
artifact download, never roll those checkpoints back on artifact failure, and continue to gate an
old cached release against the newest known safety state. Same-sequence raw digests must be
immutable: same sequence/same raw digest is idempotent; same sequence/different digest is conflict.
No new transport/controller code was added pending an A revision and A/B/C confirmation of the
same candidate hash.

## Packaged OCR model smoke (2026-10-28)

The existing candidate remains the single 2026-10-21 build from B2 source commit
`c248daab22255a069464a6d277757d01df5d49f3`; it was not rebuilt. The current `dist/StarHelp`
manifest SHA-256 still matches the recorded `30e4820d…bc19c3` manifest. All three bundled OCR
models are present under `_internal/rapidocr/models`, and each candidate model SHA-256 matches the
installed build environment: detection `090f04abcd9d9a7498bc4ebf677e4cb9bdce1fe4197ddb7e529f1ef44e1ff94f`,
classification `e47acedf663230f8863ff1ab0e64dd2d82b838fceb5957146dab185a89d6215c`, recognition
`6f327246b50388f3c176ae304bd95767ea6dc0c9ae92153ef8cbe210b3c14884`.

Added reproducible `packages/starhelp-desktop/packaging/smoke-candidate-ocr.py` and documented
its invocation in the packaging README. On 2026-10-28 it loaded both `rapidocr` and `onnxruntime`
from the candidate `_internal` directory, used the candidate model files, and recognized an
in-memory synthetic PNG as `LEVEL 80`. This exercises packaged OCR runtime/model inference, not
the frozen GUI click path; the existing Qt tests cover field mapping/preview behavior. No real
screenshot or account data was read, and no image file was saved.

The reproducible helper also checks that Pillow, NumPy, and the B OCR module are in the frozen
executable archive and that NumPy/OpenCV native extensions are present in `_internal`. Its external
Python smoke process uses build-environment Pillow and NumPy to generate and pass the synthetic PNG;
it does not claim to execute the frozen app's own Python imports.

## Public-query transport boundary hardening (2026-10-28)

`PublicQueryBuilder.serialize()` now independently validates the required draft schema identifiers,
allowlisted query kinds and environments, exact scope keys, and bounded/trimmed/control-free public
identifiers. Optional goal and release identifiers are checked at serialization time as well, so
callers cannot bypass the `build()` validation by constructing a request dictionary directly. The
synthetic regression covers unapproved query kind, schema version, missing fields, unsupported
environment, whitespace/control/oversized identifiers, UID-like release and goal values.

Verification on 2026-10-28: all 66 package `unittest` cases passed, `compileall` passed, and
`git diff --check` passed. This is local contract-boundary validation only; it does not freeze the
shared M0 production query mappings or add a production network client.

## Public-profile duplicate conflict handling (2026-10-28)

The Mihomo preview normalizer now rejects duplicate character records and refuses to silently
overwrite a field when a response repeats the same normalized character/stat or character/skill
path with a different value. This prevents one response from becoming an arbitrary last-write-wins
snapshot before the ordinary player preview/confirmation and merge flow. Tests use only synthetic
responses for duplicate characters, attributes, and skills.

Verification on 2026-10-28: all 67 package `unittest` cases passed, `compileall` passed, and
`git diff --check` passed. No network request or UID lookup was made. Provider coverage, region
mapping, and production acceptance remain open M0 decisions.

## Current Windows candidate rebuild and verification (2026-10-28)

The earlier 2026-10-21 candidate record above is superseded by this rebuild from B product source
commit `06535cfe5582d043e091bdce42f6656cdc5da016`, which includes transport-boundary query
validation and public-profile duplicate conflict handling. PyInstaller 6.22.3 rebuilt the GUI and
planner worker. The candidate manifest has 920 entries, SHA-256
`e116bad026729702cdbc80e28f5e465ba737fdbbbf772bbeabd5c1d64f134d0d`; an independent check found
920 files, no missing or extra entries, and no hash mismatches.

The OCR smoke recognized synthetic `LEVEL 80`. It also confirmed candidate-local RapidOCR, ONNX
Runtime, OpenCV and OCR models, as well as the embedded Pillow/NumPy/app modules. The smoke now
disables Python bytecode writes; a post-smoke manifest check again found exactly the same 920 files
and hashes. This remains an external Python OCR inference smoke, not a frozen GUI import/click test.
An isolated 8-second launch with a unique temporary `LOCALAPPDATA` remained running and loaded
`Qt6Core.dll` and `Qt6Widgets.dll`. The synthetic installer smoke passed install, upgrade,
two-direction rollback and tamper rejection; its first sandboxed run was denied at the temporary
directory rename, and the same scoped test passed when rerun with local temporary-directory access.
The fixed signed S3 fixture replay was also rerun through the newly built
`planner-worker/StarHelpPlannerWorker.exe` using the existing B interop harness; it passed. The
post-replay candidate still has the same 920 manifest files and hashes; packaged worker SHA-256 is
`5f4feea1f077fe936270b3f1fe7c74a8c6172ba4f1d50fe4db589394d483b546`.

No real profile, UID, or screenshot was used. The folder candidate remains unsigned; this Windows
11 build-host result does not replace target-user Windows compatibility, publisher-signing, M0
production mappings/trust, or user-provided account acceptance.

## Local feedback request plumbing (2026-10-28)

`build_producer_analysis_request()` now accepts optional feedback for the pinned local C worker.
The builder limits it to 64 reported fields and 64 KiB, requires each fact to be explicitly
`user_reported` with a unit and measurement context, binds an optional scope to the selected task,
and rejects unsupported keys/non-JSON values. It copies the feedback into the local producer
request; no PublicQuery or A transport path receives it. When C returns an eligible report, the
feedback travels with the unsaved report details and is retained only if the player explicitly
saves the encrypted report.

The B/C interop test passed a synthetic reported failure through the pinned worker, and the full 67
package tests, `compileall`, and `git diff --check` passed. The fixed S3 bundle has no troubleshooting
rules, so this verifies bounded request plumbing and local report retention, not an alternative-plan
recommendation. A player-facing feedback/reanalysis control and a production bundle with reviewed
troubleshooting rules remain open; current task creation still reports production analysis as
unavailable until M0 is frozen.

## Candidate rebuilt after feedback plumbing (2026-10-28)

Rebuilt the unsigned Windows folder candidate from B HEAD `080e11fc40e67b4297034dfa3bd6337ff62153e7`
with PyInstaller 6.22.3 and the repository-pinned C 0.4.0 wheel. Its manifest contains 920 files;
all listed hashes, file membership, and the post-smoke inventory matched. Manifest SHA-256:
`b73c1eb7d43b8a0f5fb49e07a3026f9d1f41702c1f9fa52221381b3f701dc89f`. Packaged planner worker
SHA-256: `efcc8af5b9fc8b207079fc4397e005957dc9c66592567b9c8d4e65e0158a517a`.

The bundled RapidOCR/ONNX/OpenCV runtime loaded the candidate's local models and recognized the
synthetic text `LEVEL 80`; the test passed the generated image in memory and wrote no screenshot.
The candidate executable remained alive for eight seconds in an isolated per-user data directory
and loaded Qt6Core/Qt6Widgets. The existing B/C interop test was directed to the packaged worker
executable and passed against the fixed signed synthetic S3 fixture. All 67 package tests and
`compileall` passed. Synthetic install, upgrade, two-way rollback, and tamper rejection passed;
the sandboxed rename attempt was denied, then the test passed with scoped temporary-directory
filesystem access.

No real account or UID was used. This is still an unsigned candidate tested on the build host;
publisher signing, production trust and mappings, target-user Windows acceptance, and player
acceptance remain open.

## Temporary reports start in review state (2026-10-30)

C's read-only static review of B `37e142f` §10.6 noted that the GUI report page downgraded
unverified results, but `ReportLifecycle.make_temporary()` itself still created an object marked
`current`; a consumer could inspect that object before the GUI assessment. Legacy serialized
reports lacking a validity field also defaulted to `current`. B now initializes new reports as
`needs_review` with the missing-public-basis reason, and loads legacy reports with the same
fail-closed defaults. The state can return to `current` only after `ReportLifecycle` checks a
matching snapshot and release and receives explicit known withdrawal status. Regression checks
both direct temporary objects and legacy records with no validity fields. The targeted test, all
72 package tests, `compileall -q src packaging`, and `git diff --check` pass.

This closes the direct-object optimistic-default gap only. It does not establish an authenticated
public validity epoch, typed evidence identity/hash, selected-artifact offline eligibility, or a
shared total stdio budget. Those P1–P4 items and the mandatory B builder producer profile remain
subject to the shared S4.1 contract/source tuple; production report eligibility stays disabled.

## Encrypted player progress notes and refreshed candidate (2026-10-28)

The progress page now allows a player to add and delete profile-scoped notes for the three displayed
mode labels, with free-form period/stage labels, a player-reported outcome, and an optional note.
`ProgressRepository` stores these under the profile's encrypted key prefix and performs reads and
writes through the authorization lifecycle gate; ordinary profile revoke removes the notes with
the snapshot, task preferences, and reports. The page labels each item as player-reported, keeps
source coverage unknown for all three modes, and explicitly says these notes do not enter
production analysis. This does not resolve M0 mode/cycle/stage IDs or provide source-verified
progress coverage.

Synthetic UI/storage regression covers adding, reloading, displaying, deleting, ciphertext not
containing the note plaintext, and removal on profile revocation. All 67 package tests,
`compileall`, and `git diff --check` passed.

Rebuilt the unsigned PyInstaller 6.22.3 Windows candidate with the pinned C 0.4.0 wheel. Its 920
manifest entries and hashes matched; manifest SHA-256 is
`9076fd151141a9f1a5eba4907d3187fd7bc45380f5c48dfa208eb4407b406e3e`, and packaged worker SHA-256
is `34b1ff7f2e779dea9cedb9854b352abb8ad417c669418ec5852fe10b74fb79a9`. PyInstaller archive
inspection found both `starhelp_desktop.gui` and `starhelp_desktop.progress`. Candidate-local OCR
recognized synthetic `LEVEL 80`; the executable remained alive for eight seconds and loaded
Qt6Core/Qt6Widgets; the packaged worker passed the signed synthetic S3 interop replay; and the
synthetic install/upgrade/two-way-rollback/tamper-rejection smoke passed.

No real profile, UID, or screenshot was used. The candidate remains unsigned and has only been
validated on the build host. Production mappings/trust, verified three-mode coverage, target-user
Windows and player acceptance remain outstanding.

## B request-builder provenance boundary (2026-10-28)

The latest B source/candidate tree is commit `16ea426b312992de308d2d7646a9c592b894b525`.
The synthetic demo still declares the embedded snapshot serializer as
`103741e02c90ac672017f783058bdd8dacae982e` / `starhelp.desktop.snapshot.interop-min.v0.1`.
`_snapshot_to_dict` and its serialized snapshot shape were not changed by the later feedback patch.
However, the B request wrapper source did change: `producer_request.py` blob
`0086d9121b9506ddcd3d6144f41a530b59bd8073` (at B commit `080e11fc40e67b4297034dfa3bd6337ff62153e7`)
adds optional, bounded feedback to the outer and C request; `analysis.py` blob
`c607e20aabf216a33c30ff04b6e97ed476f919c1` preserves it with the unsaved report. The synthetic
demo producer constants live in unchanged blob `2b3ece32c57aba11d3bbd019ea7d0e6a307f5a4a`.

This separates two identities that must not be conflated: the embedded snapshot serializer tuple
and the B analysis-request builder tuple. The current envelope carries the former but has no
separate provenance field for the latter. B's compatibility proposal is to keep the original
snapshot tuple and introduce a separately versioned/allowlisted B request-builder identity, bound
to the complete A/B/C tuple. C must confirm whether that needs an optional provenance object or a
new `ProducerAnalysisRequest` profile/component version, and define replay cases for old requests
without feedback, accepted feedback, unknown tuple rejection, and local-only feedback. No emitted
tuple, old profile, fixture, or fixed wheel was changed pending that review.

The candidate was built from the `16ea426` source tree, but it is a later development candidate,
not a replacement for S3 acceptance. S3's fixed cross-component result still applies only to its
recorded B source/worker and `30e4820d…bc19c3` manifest; the 16ea candidate has local package and
synthetic interop evidence only. B attempted to send the compatibility proposal directly to C, but
automatic review rejected that cross-thread message because authorization to contact C was not
established for this action. No workaround was attempted; the proposal is recorded here for the
coordinator's review.

## Current-tree verification and remaining acceptance gates (2026-10-28)

At B HEAD `125f2ac9f0c1545940c30522cc9fc863bae76140`, the package source is unchanged from the
`16ea426` development candidate; this commit only adds handoff documentation. Re-ran
`.venv\Scripts\python.exe -m unittest discover -s tests -v` from `packages/starhelp-desktop/`:
67 tests passed. `compileall -q src packaging` also passed. These checks validate the current
source tree, not a candidate rebuilt from `125f2ac`.

The synthetic integration and unsigned candidate evidence above still do not satisfy full M0/M6 or
target-user acceptance. Remaining gates are: approved real field, region, mode, and task mappings;
an accepted B request-builder provenance tuple with C; production A trust/withdrawal configuration
and live adapter; representative signed production bundle and complete positive materials/final
loadout evidence; publisher signing and signed update metadata; target Windows install/upgrade/
recovery validation; and player-provided local acceptance. The three-mode/equipment synthetic S3
fixture already exists and is not listed as missing. No real UID or account data has been accessed.

## Feedback consistency guard and rebuilt candidate (2026-10-28)

At B source commit `9c51720a91d9dc25847cddd53f220fb60ca7b075`,
`ProducerAnalysisRunner.run()` now compares canonical JSON for the outer report feedback and the
nested `producer_request.feedback` before starting the local planner. It rejects differing values
or one-sided feedback so a saved report cannot claim feedback that the planner did not analyze.
Synthetic regression covers mismatch and both missing-side cases, and asserts rejection occurs
before the planner call. The full package suite passes 68 tests; `compileall -q src packaging`
passes.

The unsigned PyInstaller 6.22.3 candidate was rebuilt from this source commit with the pinned C
0.4.0 wheel. All 920 manifest entries and hashes match; manifest SHA-256 is
`f74134a6611d7a2758a5748c2b6388ab7dafd97ecb17ce4efd8dcf2ba1da216f`, and the packaged worker
SHA-256 is `b7c45fcf7a76538aa7e6c8fc209c4c825a3be8e8cbdd17a5ab5a0099a817912f`. Candidate OCR
recognized synthetic `LEVEL 80`; the candidate stayed alive for eight seconds and loaded Qt6Core
and Qt6Widgets; the actual packaged worker passed the signed synthetic S3 replay. The installer
smoke passed install, upgrade, two-way rollback, and tamper rejection using synthetic installer
fixtures in a unique `%TEMP%` directory. No candidate was installed over the user's existing app.

This candidate remains unsigned and synthetic-only. M0 mappings/trust, C acceptance of the B
request-builder provenance tuple, production A integration, reviewed troubleshooting evidence,
target-user Windows validation, publisher signing, and player-provided acceptance remain open.

## C static review follow-up (2026-10-28)

C's read-only review at `parallel/local-planner` commit
`6a10fba12a719c314c88fd7b79930aa90768344e` confirms that the snapshot format anchor and the
actual request-builder source must be tracked separately. It recommends a mandatory new producer
request profile/component with an explicitly registered builder/source/artifact tuple; an
optional provenance field in the old profile would be ignorable and is not an adequate gate. The
review is static, not a freeze or acceptance of B `9c51720`, its rebuilt candidate, or the current
S3 wheel. It did not execute the B candidate or establish a new cross-component tuple.

B `9c51720` now rejects mismatched or one-sided outer/inner feedback before launching the planner,
with synthetic regression coverage. C's proposed future consumer acceptance also calls for checks
between request submission, result receipt, report staging/saving, and changes to public validity
basis. Those gates and the new producer profile remain unimplemented/unfrozen pending a shared
tuple; do not relabel the old serializer profile or claim full M0/S3 acceptance. This C review was
read from its committed documentation; no cross-thread message was sent from B.

## Request snapshot isolation candidate (2026-10-28)

B source commit `dd904e3edc11177e735381d454c1b8e3b114897d` strengthens the runner boundary: it
serializes the bounded request once, creates separate JSON copies for the worker and report, checks
outer/nested feedback agreement on the report-bound copy, then uses that copy for report scope,
snapshot, citations, and feedback. A synthetic regression mutates the worker's received copy and
confirms that the original request and temporary report retain the pre-submit feedback. The full
component suite passes 69 tests and `compileall -q src packaging` passes.

The prior `9c51720` candidate is superseded. The unsigned PyInstaller 6.22.3 candidate was rebuilt
from `dd904e3` with the pinned C 0.4.0 wheel. Its exact 920-file set and hashes were verified;
manifest SHA-256 is `3d2fd1b39449e0bc2e67557c7376cd18b3e5f18df01068dd78dd5f1eb408932b`, and worker
SHA-256 is `b7add70426eef2ac5f3d52ce67392ea6112e073f2c53e791a9a1cad23ebd31fe`. OCR recognized the
synthetic `LEVEL 80`; the GUI stayed alive for eight seconds with Qt6Core/Qt6Widgets loaded; and
the packaged worker passed the signed synthetic S3 replay. The installer smoke again passed
install, upgrade, two-way rollback, and tamper rejection with synthetic installer fixtures in its
guarded temporary directory.

This validates B request/report binding and the built artifact only. C's new mandatory producer
profile and full request/result/public-validity binding remain proposals, not a frozen tuple;
production mappings/trust, actual A service integration, publisher signing, target-user validation,
and player acceptance remain open. No real UID/account was used and the existing `.tmp/` was kept.

## Mihomo endpoint shape checked against its client documentation (2026-10-28)

The [MetaCubeX `mihomo` README](https://github.com/MetaCubeX/mihomo/blob/main/README.md) documents
`https://api.mihomo.me/sr_info_parsed/{UID}?lang={LANG}`; its V2 example omits `version`, while the
V1 example adds `version=v1`. B's `MihomoPublicProfileClient` builds the documented V2 path and
language query. The UI's server/region label is required local metadata but is not part of the HTTP
request. This client README confirms the URL shape only: it does not establish how the service routes
UIDs across regions, its data coverage, privacy terms, or rate limits. UID-to-region mapping therefore
remains an M0 item, and no real UID was requested during this check.

## Synthetic feedback/reanalysis UI (2026-10-28)

The Reports page now exposes “反馈并重新分析（仅合成 fixture）” only when the selected saved report
belongs to the active `synthetic-demo` profile. The user selects one of three fixed synthetic failure
labels; B binds it to the saved report's task scope, marks it `user_reported`, and passes it through the
existing bounded request builder to the local worker. The result returns to the unsaved report
preview, and the saved-report count stays unchanged until the separate save action. The action is
disabled for ordinary reports, and there is no network route in this flow.

The end-to-end PySide6 regression uses the pinned synthetic S3 bundle and packaged C wheel: it saves
an initial demo report, selects synthetic feedback, reruns the local worker, confirms the feedback is
present in the new temporary report, and confirms the second report was not saved automatically.
This closes a synthetic UI/worker/report plumbing gap only. Production task analysis and player
feedback/reanalysis remain unavailable pending the shared M0 tuple, production trust and mappings,
and reviewed troubleshooting content. No real account or UID was used.

## Strict task-preference loading and progress-page events (2026-10-28)

`AnalysisTaskDraft.from_dict()` now rejects unknown/missing keys, boolean generations/progress,
coercible non-string task labels, malformed identifier arrays, and non-string timestamps rather than
silently stringifying or integer-coercing encrypted preference data. A synthetic regression covers
these malformed representations, and the existing encrypted restart/revoke test still passes.

The full PySide6 suite exposed a separate progress-page notification error after a player-reported
record was added or deleted: the page connected the shared progress bus but did not retain it for its
event handlers. The page now stores the bus; its UI regression checks the add and delete event in the
session history as well as the encrypted record changes.

Verification: 70 package tests passed; targeted task lifecycle and progress UI tests passed;
`compileall -q src packaging` and `git diff --check` passed. A fresh unsigned PyInstaller 6.22.3
candidate was built with the pinned C 0.4.0 wheel. Its 920-file manifest set and SHA-256 values
matched (manifest SHA-256 `51ec308fb4cfc6f9df6ba13c2760f0b9a2763cc6a5d7fd23ca548aa3178a9de8`;
worker SHA-256 `bde7d0648c281d0d7b1bfcb661cb35708cadcc65d6afa35ac8d64a8681790a17`). Candidate OCR
recognized synthetic `LEVEL 80`; the GUI remained alive for eight seconds and loaded candidate-local
Qt6Core/Qt6Widgets; the packaged worker passed the signed synthetic S3 replay; and the installer
smoke passed synthetic install, upgrade, two-way rollback, and tamper rejection in its guarded
temporary directory. This does not establish production M0, publisher signing, target-user Windows
compatibility, or player acceptance. No real UID/account data was used.

## Candidate refreshed for synthetic feedback UI (2026-10-28)

The full package suite passed 70 tests, including the end-to-end synthetic feedback/reanalysis flow
and the ordinary-report gate. `compileall -q src packaging` and `git diff --check` passed. The new
unsigned PyInstaller 6.22.3 candidate was built with the pinned C 0.4.0 wheel; all 920 manifest files
and hashes matched (manifest SHA-256
`64f310db62ff3ac5b9ecc75abc444d48e7ff7b261e4d24b423d78b647d3a2dd1`; packaged worker SHA-256
`3c257894d72a5d4fe0df7998861b0bd99f973258616c4ef4935d647c614a67b7`). Candidate OCR recognized
synthetic `LEVEL 80`; the GUI stayed alive eight seconds and loaded candidate-local Qt6Core/Qt6Widgets;
the packaged worker passed the signed synthetic S3 replay; and the installer smoke passed synthetic
install, upgrade, two-way rollback, and tamper rejection in a guarded temporary directory.

This candidate remains unsigned and tested only on the build host. The feedback/reanalysis UI is still
limited to synthetic demo reports. Production mappings/trust, live A integration, reviewed production
troubleshooting, target-user Windows validation, publisher signing, and player-provided acceptance
remain open.

## Automatic-refresh catalog failure rollback and candidate (2026-10-28)

`ProfileRepository.set_auto_refresh()` previously deleted the per-profile refresh object whenever a
catalog update failed, even when auto-refresh was already enabled and the old encrypted UID/config
was still the committed state. It now retains the previous config and restores it if catalog
persistence fails. A fault-injection regression starts with an enabled profile and a recorded
attempt time, rejects the catalog write while changing the UID, then confirms the prior encrypted
UID, attempt time, and enabled catalog state remain intact.

Verification: the full desktop package suite passes 71 tests; the targeted rollback regression,
`compileall -q src packaging`, and `git diff --check` pass. A fresh unsigned PyInstaller 6.22.3
candidate using the pinned C 0.4.0 wheel has 920 manifest files with exact hash verification; the
manifest SHA-256 is `6cf00caf71d861ee01af48d68c8a07ffcf6c1c6e1d9e094b7de4f979f4fc0a55`, and the
packaged planner worker SHA-256 is
`6900ff39072a05ff16f74aab18867202581b931f8a6a79a3d174326606177fbe`. Synthetic OCR recognized
`LEVEL 80`; the candidate stayed active for eight seconds and loaded Qt6Core/Qt6Widgets from its
own `_internal`; the actual packaged worker passed the signed synthetic S3 replay. The installer
smoke passed install, upgrade, two-way rollback, and tamper rejection in a unique temporary
directory. This is build-host evidence only; the candidate remains unsigned, production M0/A
integration and target-user acceptance remain open, and no real UID/account was used.

## Current M0 and B2 producer-builder freeze inputs (2026-10-28)

Read-only comparison of the current component records confirms that the remaining integration work
is not a missing synthetic fixture. B's `producer-interop-s3` sample pins A producer commit
`dcb1e3ee220b85229bedc6c79d72ebe495825f37`, A envelope profile
`starhelp.b-publicbundle-envelope.v1`, B snapshot serializer commit
`103741e02c90ac672017f783058bdd8dacae982e` / profile
`starhelp.desktop.snapshot.interop-min.v0.1`, release `rel_fixture_s3_0001`, and a test-only key.
C's current adapter API documents this A 0.3.0 producer and B1 serializer as admitted to its 0.4.0
wheel. The checked-in S3 fixture exercises three synthetic modes and equipment cases. These facts
support the existing synthetic packaged-worker replay only; they do not establish production M0 or
real-data semantics.

The current C review (read from C `6a10fba`) separately says the B request-building code needs its
own mandatory producer profile and exact source/artifact tuple. The current B request envelope
records A producer and B snapshot provenance; its `adapter_profile` names C's consumer adapter and
does not identify the B builder implementation. Do not relabel the snapshot serializer profile or
silently add an optional field: C's review says that would not be an enforceable compatibility
gate. Freeze a required B builder profile and its accepted source/artifact identity with the
coordinator and C before production request construction is enabled.

Concrete production inputs still absent from the M0 draft are:

- An authorized, documented public data source and allowed host/path, with actual exposed fields,
  coverage limits, freshness/rate rules, and applicable use/storage terms. A's current handoff
  reports no live source as both authorized and verified.
- Verified game-version/environment and mode, cycle, stage, character, equipment-type, and external
  ID mappings, plus the confirmed public-goal and task-scope values. The selected Mihomo server or
  region is local metadata today; its UID routing semantics remain unverified.
- Shared condition attribute IDs, operators, units, measurement phases/assumptions, ownership and
  coverage meanings, and physical-equipment identity policy for real imported records.
- Production A distribution endpoints and catalog/revocation semantics, freshness/offline rules,
  and a provisioned publisher key plus independently pinned B trust anchor/key purpose. The
  synthetic fixture key is test-only.
- The mandatory B request-builder profile/source/artifact tuple and C-accepted binding rules across
  submission, result receipt, staged/saved report, snapshot revision, authorization generation,
  and public validity basis.

Until these are frozen and supported by dated real-source samples plus a reviewed production trust
configuration, keep production analysis/synchronization disabled and continue using the explicitly
labeled synthetic demo. No real UID or account data was accessed for this comparison.

## Report validity requires a known public basis (2026-10-30)

`ReportLifecycle` now fails closed when there is no current public release ID or the latest signed
withdrawal/disable state is unknown. Those cases display and persist `needs_review` with a specific
reason; a report can return to `current` only when its snapshot and public release match and the
caller explicitly says withdrawal status is known. A verified withdrawn citation remains
`evidence_withdrawn`, and a changed snapshot remains `expired`. The GUI has no signed A withdrawal
feed yet, so its reports remain visibly `needs_review` rather than implying online validity.

Regression covers unknown withdrawal status, missing current release, recovery to current when the
same basis is again verifiable, and the pending-report UI. All 72 package tests pass;
`compileall -q src packaging` and `git diff --check` pass. A fresh unsigned PyInstaller 6.22.3
candidate with pinned C 0.4.0 has 920 manifest entries and exact file-set/hash verification; manifest
SHA-256 is `eb0f5fb15c83ee40d56ec72c59b64208f10e27c792a5cd56bc9df4a102c76715`, and packaged worker
SHA-256 is `bd8b2909d4cba28bcee2e0ab4ccf8ef650300ff47d21eddb3dcf3221d9b8a099`. Synthetic OCR
recognized `LEVEL 80`; the GUI stayed active for eight seconds with candidate-local Qt6Core and
Qt6Widgets; the packaged worker passed signed synthetic S3 replay; and installer smoke passed
install, upgrade, two-way rollback, and tamper rejection. This remains build-host-only unsigned
evidence; production withdrawal data, publisher signing, target-machine acceptance, and player
acceptance remain open.

## Revocation removes interrupted encrypted staging files (2026-10-30)

`EncryptedPrivateStore.save` writes ciphertext to a hidden per-object `.tmp` file before replacing
the `.bin` destination. If the process exits between those steps, the previous revocation cleanup
removed committed `.bin` objects but could leave that ciphertext on disk. `delete_profile` now
removes both patterns scoped to the exact profile UUID; unrelated profiles' staging files remain.
The synthetic revocation regression confirms committed data and interrupted staging files are
deleted, another profile's staging file remains, and task cancellation/late-result rejection still
work. The targeted regression and all 72 package tests passed; `compileall -q src packaging` and
`git diff --check` passed. A fresh unsigned PyInstaller 6.22.3 candidate with pinned C 0.4.0 has
920 manifest entries with exact file-set/hash verification; manifest SHA-256 is
`35bc61763c5facec7f64f3a31a3246f9b8de0ee37695d87aa4e7194e35a950af`, GUI executable SHA-256 is
`55f8eb037e5193a1a4eec03320ba66410330a27a0e220c8a14587021f51b5da6`, and packaged worker SHA-256
is `6ff387a00867e2aaad7b39722e395a5e3531611cf022727b501fb7b731d32391`. Synthetic OCR recognized
`LEVEL 80`; the GUI stayed active for eight seconds and loaded candidate-local Qt6Core and
Qt6Widgets; the packaged worker passed signed synthetic S3 replay; installer smoke passed install,
upgrade, two-way rollback, and tamper rejection. This remains unsigned build-host evidence;
production data, publisher signing, target-machine acceptance, and player acceptance remain open.

## Rebuilt candidate for fail-closed temporary report state (2026-10-30)

The candidate was rebuilt after the `ReportLifecycle` default change from B HEAD `ed3e235` plus the
current package patch. The unsigned PyInstaller 6.22.3 candidate with pinned C 0.4.0 has 920
manifest entries with exact file-set/hash verification. Manifest SHA-256 is
`141e13416d721bf9574c7f0b61a86751b1eabceb1dd4e8ffc9ca33a1496df451`, GUI executable SHA-256 is
`fa26fc182e9fb106c27c54a61ece1f2ba3841086b92149315b623b221a235896`, and packaged worker SHA-256
is `4ce36f7c016293446dc61bcb34f04e2b068cfaf9fad85fba3de2fb88f595deb2`. Candidate OCR recognized
synthetic `LEVEL 80`; the GUI stayed active for eight seconds and loaded candidate-local Qt6Core and
Qt6Widgets; the packaged worker passed signed synthetic S3 replay. The synthetic installer smoke
was last run against the unchanged installer in the immediately prior candidate build; this report
state change does not alter installer code. All account and bundle inputs remained synthetic.

## S4.1 review inputs for production validity and builder admission (2026-10-30)

Read-only current C review: `parallel/local-planner` HEAD `1106437669e1ae5989ddd1e2d62cf22252c5ac80`,
`packages/starhelp-planner/docs/production-consumption-review-v0.1-draft.md` §§9.1–9.4 and 10.6.
These are proposed next-version semantics; they do not amend the shared `mvp-v0.1.md` draft, extend
C 0.4.0, or authorize a production request. B HEAD `83a609e` closes the direct temporary-report
optimistic default noted by the earlier review, but does not implement the larger validity protocol.

| Gate | Fields/decision that must be frozen | Minimum B/C acceptance evidence |
|---|---|---|
| P1 typed withdrawal identity | Preserve object `{kind, id, revision, content_hash}` and release `{release_id, envelope_sha256}` identities; define the native hash profile/material and prove its binding to the signed A record and C-consumed object. C 0.4.0's `id`/`id@revision` projection is lossy when kinds collide. | Same ID across kinds, wrong revision/hash, wrong release digest, unknown hash profile, and dependent-object withdrawal all reject without over-withdrawing another object. |
| P2 selected-artifact offline qualification | Persist separately the signed catalog/revocation sequence and raw digest pair, trusted time/expiry, policy/origin/channel, selected envelope raw digest and exact producer/planner/snapshot tuple, qualification state, and pending/recovery state. A new metadata check cannot extend offline eligibility for an old artifact that the metadata did not qualify. | Failed new download plus successful metadata refresh does not extend old artifact eligibility; sequence rollback, missing pair, expired/offline window, unknown key, and persistence-recovery ambiguity fail closed. Runtime values such as TTL/window remain A/B operations decisions. |
| P3 result/report validity epoch | Bind one authenticated public-basis epoch to task submission, worker result, temporary report, explicit save, and later display; include the accepted metadata pair, selected raw envelope digest, tuple, policy/epoch, and trusted evaluation time. Recheck or CAS before acceptance/save so an intervening withdrawal cannot make an old result current. | Change raw digest or sequence while keeping release ID constant; finish a worker on an old basis; submit a withdrawal before save; unknown basis with empty refs/true boolean; require stale result rejection or review/expiry. |
| P4 complete local message budget | Keep limits on fully encoded UTF-8 bytes (including JSON escaping/repeated `raw_json`, multi-byte text and framing), separately from the download cap. The current B request cap is 8 MiB and response cap 16 MiB; C separately limits each `raw_json` to 8,000,000 characters, 100k nodes and depth 48. Any new raw signed catalog/revocation bytes must count toward the entire serialized request. | Boundary tests cover max multibyte/escaped values and all duplicated fields; over-limit requests fail before spawn and over-limit responses terminate the worker with a size error, not a domain no-plan result. |
| Builder provenance | New consumer profile must require a `request_producer` identity that independently names B host/package, actual source commit, builder blob, dependency lock and artifact/build tuple; keep it distinct from the snapshot serializer profile. The claim must be tied to B's verified build/load policy, not merely self-reported fields. | Unknown/missing/conflicting builder identity, old B1 identity with new builder source, and artifact mismatch reject. Freeze the C-accepted profile/capability and full A/B/C source-artifact tuple before implementation; do not alter fixed S3 or C 0.4.0. |

The separate production M0 inputs remain: authorized real public source/terms and coverage, verified game/mode/cycle/stage/entity/goal mappings, field units/measurement context/coverage/identity semantics, A signed distribution/revocation operations, and a separately provisioned production trust anchor. Until those inputs and the S4.1 tuple are agreed, production TaskPage analysis and public synchronization stay disabled; synthetic replay is compatibility evidence only.

## Mihomo response-shape verification (2026-10-30)

The first-party March7th Parsed Data API example places the Memory summary at
`player.space_info.memory_data`; its reference model likewise declares `SpaceInfo.memory_data`
inside `PlayerInfo.space_info`. B previously looked for the undocumented flattened
`player.memory_data`, so documented responses would silently omit this summary. B now reads the
nested path and records the matching provenance scope. A synthetic regression confirms named
summary values are retained without mapping them to challenge modes, while a separate regression
confirms the undocumented flat shape is ignored. All 73 package tests pass.

The source review is recorded in
`packages/starhelp-desktop/docs/research/mihomo-public-profile-source-2026-10-30.md`. This verifies
the endpoint/query shape and example field paths only. It does not establish service authorization,
privacy/retention terms, numerical rate limits, cache freshness, UID-to-region routing, full account
coverage, or frozen task mappings. The documented server label therefore remains local metadata;
no live UID or account request was made. Production sync and analysis remain behind the existing M0
freeze gates.

## Mihomo parser correction candidate (2026-10-30)

Rebuilt the unsigned PyInstaller 6.22.3 candidate after correcting the documented Memory summary path.
The manifest contains 920 entries and exact file-set/hash verification passed. Manifest SHA-256 is
`e55304b5fc3b73afba36fbc65e8a17af5364961fb1de949dab69bddab7c6c2cf`; GUI executable SHA-256 is
`2c830897138d84b896dcd1d27ab88a45a848848a66ea0d14127123b7b60bfd20`; packaged worker SHA-256 is
`d457d203d5e8dfe4aa58e822e178b4967f9f3ba3acd64c33c74b87c099cc85b3`.

All 73 package tests passed, `compileall -q src packaging` passed, and `git diff --check` passed.
The candidate-local OCR smoke recognized synthetic `LEVEL 80`; an isolated 8-second GUI launch loaded
`Qt6Core.dll` and `Qt6Widgets.dll`; and the packaged worker passed the signed synthetic S3
interop/report replay. The installer script was unchanged and its synthetic install/upgrade/rollback
smoke is recorded above from the prior candidate. No real UID, account data, or user screenshot was
used. The candidate remains unsigned and build-host-only; production M0, publisher signing, and
target-machine acceptance remain open.

The Mihomo equipment regression now also mirrors the documented relic `main_affix`/`sub_affix`
shape. It verifies provider field/value/count/step retention, needs-review state, and ambiguous
physical-copy identity. The parser already supported these fields; this change adds representative
coverage only. Full synthetic suite remains 73/73.
