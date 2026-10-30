# StarHelp Desktop and Account Component

The component is isolated from the legacy `src/abyss_ai` tree and root dependencies. It currently
implements local account facts, source-aware partial merge, import preview, DPAPI-backed private
storage, revocation, encrypted per-profile task memory, public-query allowlisting, bundle
validation/cache, and report lifecycle.

## Development

From this directory, install with `pip install -e ".[desktop,ocr,crypto]"` and run
`python -m starhelp_desktop`. Core models and workflows use the Python standard library. PySide6 is
an optional desktop extra. Local screenshot recognition uses RapidOCR, ONNX Runtime, and Pillow;
models are packaged with the RapidOCR wheel and the adapter refuses network model downloads.
Ed25519 bundle verification uses the optional `crypto` extra. The command reports a clear dependency
error when PySide6 Essentials is unavailable.

Tests are standard-library `unittest` tests under `tests/` and use synthetic data. DPAPI integration
requires Windows; the encryption contract is injected in platform-independent unit tests. Revoking
a profile removes its encrypted object files and any hidden encrypted staging files left by an
interrupted atomic write, while preserving files belonging to other profiles.

Structured local imports use `starhelp.account-import` version `0.1-draft`. Equipment entries may
include a `facts` object keyed by local field paths; each fact has an explicit `value` and optional
string `scope`. These facts keep the import source and observation time and remain `needs_review`
until the player confirms the preview. An imported public equipment type never establishes the
identity of a physical copy.

## Integration status

- Public profile provider: Mihomo parsed HSR endpoint normalization is covered by synthetic fixtures,
  including malformed optional arrays. Network responses must echo the requested UID in the documented
  `player.uid` field or they are rejected before preview. Manual and separately authorized automatic
  reads can be canceled locally; an already sent HTTP request may still finish at the service, but its
  response is discarded. Mihomo's documented `player.space_info.memory_data` summary values are
  retained with their provider field names and are shown as raw summary facts in the Progress page;
  they are not mapped to complete cycle or three-mode history. The three challenge modes stay unknown unless separately verified.
  No real UID has been requested; UID-to-region routing remains an M0 decision.
- The MetaCubeX `mihomo` client README documents the parsed endpoint as
  `https://api.mihomo.me/sr_info_parsed/{UID}?lang={LANG}` and says V2 is the default while V1 adds
  `version=v1` ([source](https://github.com/MetaCubeX/mihomo/blob/main/README.md), checked 2026-10-28).
  B constructs the documented V2 URL. Its selected server/region label is local metadata only and is
  not sent to Mihomo; the client documentation does not establish UID-to-region routing, coverage,
  service privacy, or rate-limit guarantees. No real UID request was made.
- Enka HSR fields and region mapping: not verified from its public API documentation.
- Planner and public knowledge components: no source code is imported from their worktrees. The
  desktop package vendors the pinned C 0.4.0 wheel as a black-box artifact and launches its worker
  through the bounded local process bridge. The S3 A bundle, B1 snapshot, and fixture key are
  synthetic; the B2 bridge and packaged candidate are verified separately in the handoff.
- The local planner process bridge sends one
  complete `AnalysisRequest` as UTF-8 JSON on stdin and accepts one versioned result envelope on
  stdout, checks declared capabilities, bounds payload sizes and runtime, discards stderr, and kills
  the process when profile authorization is revoked. It binds returned results to request ID,
  snapshot revision, and authorization generation. The frozen candidate includes a separate stdio
  worker executable. The GUI still does not construct a production request or call the worker:
  there is no production-signed A bundle/trust key, shared M0 field and task mapping, or complete
  bundle/snapshot/task request builder. TaskPage correctly remains in the explicit waiting state.
- The task form saves the latest target and local constraints under the selected encrypted profile,
  restores that profile's values, and clears them on profile revocation. It records a waiting state;
  it does not call a planner or present a recommendation.
- The Reports page offers a feedback/reanalysis action only for an explicitly saved synthetic-demo
  report. It submits a fixed, labeled fixture feedback value to the local worker and stages the new
  result without saving it. Ordinary reports cannot use this action; player-facing production
  feedback/reanalysis still awaits frozen M0 mappings, a production request builder/trust tuple, and
  reviewed troubleshooting data.
- OCR: optional local RapidOCR adapter, with explicit text-to-field mapping and confirmation;
  screenshot bytes stay in memory during recognition and OCR output is not trusted automatically.
- Structured import equipment facts preserve each field's source, observation time, optional scope,
  and review state alongside the type ID and slot; the import preview displays those facts and
  distinguishes the local instance ID from the public type ID. Malformed paths and UID-like
  equipment IDs are rejected before preview. This local draft schema does not claim to be a frozen
  production source mapping.
- Equipment instances appear in the selected account profile. Each can be individually confirmed
  by the player and the identity decision is saved in the encrypted snapshot. Automatic UID refresh
  is off by default. Per-profile opt-in stores the UID in current-user DPAPI storage, runs while the
  app is open (immediately on opt-in, then at most once every 24 hours), and leaves every result in
  preview until the player confirms import. Revoking or disabling the opt-in deletes the saved UID.
- Duplicate equipment records can be linked only after the player confirms they are the same
  physical copy. The UI lists candidates with matching type and slot; conflicting owner or stat
  values require individual source choices before the encrypted snapshot is updated.
- The report page lists only explicitly saved reports, reloads them under the active profile, and
  persists snapshot-expired or evidence-withdrawn status. A temporary planner result can be staged
  from TaskPage and requires the visible save action before DPAPI persistence. Online withdrawal
  state is reported as unknown until A's signed withdrawal feed is available. A report is marked
  `needs_review` if the current public release or signed withdrawal status cannot be checked; it can
  return to `current` when the same snapshot/release is available and withdrawal status is verified.
  Snapshot-expired and known-withdrawn states remain terminal. No report is generated without a
  planner result.
- The two-release public cache revalidates signed bytes every time a cached release is loaded.
  Byte-oriented sources retain the exact UTF-8 release bytes across activation and restart so the
  producer adapter can verify its recorded digest; test object sources use canonical JSON bytes.
- An unsigned folder-style candidate builds with PyInstaller 6.22.3. Its per-user installer
  verifies a SHA-256 file manifest, stages upgrades, preserves previous versions, and can roll back.
  The build script limits the dependency search path to Windows system directories so unrelated
  software cannot contribute incompatible DLLs. The rebuilt candidate starts on the Windows 11
  build machine and loads Qt Core and Widgets. It relies on the target Windows system ICU; target
  Windows compatibility and install/upgrade/recovery checks remain release work. Publisher signing
  and update metadata are also outstanding.
