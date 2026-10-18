# Desktop and Account Component Handoff

Status: in progress. This is an implementation log, not an MVP acceptance statement.

## Boundary and current baseline

- Repository: `parallel/desktop-account`; branch: `codex/mvp-desktop-account`.
- Component ownership: `packages/starhelp-desktop/` and this handoff only.
- Shared contract, root dependencies, legacy `src/abyss_ai`, and other components remain unchanged.
- Current implementation is isolated from the legacy offline simulation. The planner and knowledge
  service are not connected; local adapters must display that state.

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
