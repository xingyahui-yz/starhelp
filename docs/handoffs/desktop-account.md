# Desktop and Account Component Handoff

Status: in progress. This is an implementation log, not an MVP acceptance statement.

## Boundary and current baseline

- Repository: `parallel/desktop-account`; branch: `codex/mvp-desktop-account`.
- Component ownership: `packages/starhelp-desktop/` and this handoff only.
- Shared contract, root dependencies, legacy `src/abyss_ai`, and other components remain unchanged.
- Current implementation is isolated from the legacy offline simulation. The planner and knowledge
  service are not connected; local adapters must display that state.

## M0 source and contract findings (checked 2026-10-15)

1. March7th's parsed API documents `GET /sr_info_parsed/{uid}` with `language`/`lang` and
   `version` query parameters. Its example shows `player` and a `characters` showcase list. The
   documented character record includes ID, level, rank, skills, light cone, relics, attributes,
   while `player.space_info` includes aggregate counts. Aggregate counts are not item inventories.
   The component normalizes only listed showcase records and treats every unlisted character or
   item as unknown. It does not retain the returned player UID, nickname, signature, or raw body.
   The documented request has no region parameter; the UI says so explicitly and stores the player's
   selected region label locally. Whether UID routing covers the selected server still needs M0
   confirmation. Sources: [parsed API](https://march7th.xyz/zh/api/parsed.html),
   [Mihomo Python client](https://github.com/Mar-7th/mihomo.py/blob/master/mihomo/client.py).
2. Enka's public documentation describes UID lookup, showcase data, dynamic rate limits and a TTL
   that clients should honor. Its current API document does not establish an HSR-specific schema or
   UID-to-region mapping for this component, so Enka is not enabled as an adapter. Source:
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
  equipment type ID.
- Public-profile refresh stays manual by default. A separate per-profile opt-in stores the UID only
  in current-user DPAPI storage, queries directly while the app is running (immediately on opt-in,
  then at most once per 24 hours), and keeps results in preview until the player confirms import.
  Disabling refresh or revoking the profile deletes the encrypted UID configuration.
- A consent-gated Mihomo request adapter, public-query allowlist, current-user DPAPI file store,
  encrypted profile catalog/snapshots, profile generation/revocation gate, signature-gated bundle
  validator/cache, and explicit-save report service. UID requests reject redirects, so the UID stays
  on the player-selected HTTPS service. Saving and revocation are serialized to prevent a late write
  after cleanup.
- The report page lists saved reports per profile, persists snapshot-expired/evidence-withdrawn
  validity, and displays when online withdrawal state is unknown. It does not manufacture a report
  without a planner result; report generation and the user-triggered save action still need
  connection to a real temporary result.
- A verify-before-activate public bundle synchronizer interface and two-version atomic local cache.
  Failed signature verification leaves the current release active. No production transport, trust
  key, or final A-side bundle format is available yet.
- An unsigned Windows folder-style candidate packaging script/spec that collects the bundled
  RapidOCR models and ONNX Runtime. PyInstaller is pinned to 6.22.3. A per-user
  installer validates a file manifest, stages changes, keeps rollback folders, and can restore the
  most recent preserved version.

## Remaining work / verification limits

- Verification on 2026-10-16: 20 standard-library `unittest` cases pass with synthetic fixtures;
  `compileall` passes; current-user Windows DPAPI protect/unprotect round-trip passes with synthetic
  bytes; an offscreen PySide6 window was created; RapidOCR loaded its bundled local models and
  recognized a synthetic screenshot. An offscreen task-form smoke confirmed encrypted per-profile
  save/restore and the explicit planner-unavailable status. No real UID was queried.
- The equipment confirmation UI and separately opted-in automatic refresh both compile. The
  automatic refresh test uses only synthetic UID data and verifies consent gating, encrypted
  persistence, restart recovery, attempt timestamps, opt-out deletion, and revoke cleanup. An
  additional test confirms UID redirects are rejected. An offscreen window smoke confirms automatic
  refresh defaults off and the scheduler stays idle; no real UID request was made.
- The report browser was exercised offscreen with one synthetic authorized profile, snapshot, and
  explicitly saved report. It listed and rendered the report locally; no recommendation was shown.
- A fresh PyInstaller 6.22.3 candidate containing these changes was built. All 677 manifest entries
  matched their SHA-256 hashes. The executable remained open for an 8-second startup smoke under an
  isolated temporary `LOCALAPPDATA`, so it could not see or query any real saved profile.
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
- Equipment identity confirmation is now wired through the desktop UI and encrypted snapshot
  repository; no duplicate-link UI is provided, so matching two records as the same physical copy
  remains unsupported.
