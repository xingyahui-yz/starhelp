# Desktop and Account Component Handoff

Status: in progress. This is an implementation log, not an MVP acceptance statement.

## Boundary and current baseline

- Repository: `parallel/desktop-account`; branch: `codex/mvp-desktop-account`.
- Component ownership: `packages/starhelp-desktop/` and this handoff only.
- Shared contract, root dependencies, legacy `src/abyss_ai`, and other components remain unchanged.
- Current implementation is isolated from the legacy offline simulation. The planner and knowledge
  service are not connected; local adapters must display that state.

## M0 source and contract findings (checked 2026-10-17)

1. March7th's parsed API documents `GET /sr_info_parsed/{uid}` with `language`/`lang` and
   `version` query parameters. Its example shows `player` and a `characters` showcase list. The
   documented character record includes ID, level, rank, skills, light cone, relics, attributes,
   while `player.space_info` includes aggregate counts. Aggregate counts are not item inventories.
   The component normalizes only listed showcase records and treats every unlisted character or
   item as unknown. It does not retain the returned player UID, nickname, signature, or raw body.
   The documented request has no region parameter; its optional `is_force_update` query flag bypasses
   the service cache, so the component does not use it for routine refresh. The UI stores the player's
   selected region label locally. Whether UID routing covers the selected server still needs M0
   confirmation. The documentation page says it was last updated 2025-02-15. Sources:
   [parsed API](https://march7th.xyz/zh/api/parsed.html),
   [Mihomo Python client](https://github.com/Mar-7th/mihomo.py/blob/master/mihomo/client.py).
2. Enka's public documentation describes UID lookup, showcase data, dynamic rate limits and a TTL
   that clients should honor; it also asks clients to send a custom User-Agent and not enumerate UIDs.
   Its current API document does not establish an HSR-specific schema or UID-to-region mapping for
   this component, so Enka is not enabled as an adapter. Source:
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
  asks for a separate confirmation. Images are size/type/dimension checked and not persisted.
- Imported equipment is listed per profile with its current identity. A player can explicitly
  confirm an individual equipment instance; the decision is written to the encrypted snapshot and
  only then becomes eligible for reassignment. The UI does not infer copy identity from a public
  equipment type ID. Same-type duplicate candidates can be linked only after the player confirms
  they are the same physical copy. Conflicting owner/stat values require per-field source choices;
  the existing local identity is retained and the duplicate record is removed from the merged snapshot.
- Public-profile refresh stays manual by default. A separate per-profile opt-in stores the UID only
  in current-user DPAPI storage, queries directly while the app is running (immediately on opt-in,
  then at most once per 24 hours), and keeps results in preview until the player confirms import.
  Disabling refresh or revoking the profile deletes the encrypted UID configuration.
- A consent-gated Mihomo request adapter, public-query allowlist, current-user DPAPI file store,
  encrypted profile catalog/snapshots, profile generation/revocation gate, signature-gated bundle
  validator/cache, and explicit-save report service. UID requests reject redirects, so the UID stays
  on the player-selected HTTPS service. Saving and revocation are serialized to prevent a late write
  after cleanup.
- The Mihomo response parser rejects duplicate JSON keys, non-finite constants, invalid UTF-8,
  excessive nesting, and non-object roots. Numeric preview fields exclude booleans, NaN, infinities,
  and overflowing integers so malformed service values cannot enter the encrypted snapshot.
- The report page lists saved reports per profile, persists snapshot-expired/evidence-withdrawn
  validity, and displays when online withdrawal state is unknown. It does not manufacture a report
  without a planner result. TaskPage exposes a temporary-report signal; the report page previews it
  and saves only after the user clicks the explicit save action. Report writes and task-preference
  writes serialize with revocation. No planner currently emits that signal.
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
