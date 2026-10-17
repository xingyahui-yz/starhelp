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
requires Windows; the encryption contract is injected in platform-independent unit tests.

## Integration status

- Public profile provider: Mihomo parsed HSR endpoint normalization is covered by synthetic fixtures,
  including malformed optional arrays. No real UID has been requested; UID-to-region routing remains
  an M0 decision.
- Enka HSR fields and region mapping: not verified from its public API documentation.
- Planner and public knowledge components: contract adapters only; no cross-branch source or
  runtime is loaded here.
- A local planner process bridge is available for an explicitly configured executable. It sends one
  complete `AnalysisRequest` as UTF-8 JSON on stdin and accepts one versioned result envelope on
  stdout, checks declared capabilities, bounds payload sizes and runtime, discards stderr, and kills
  the process when profile authorization is revoked. It binds returned results to request ID,
  snapshot revision, and authorization generation. This is an integration seam only: no C planner
  executable, production capability set, complete request builder, or GUI task-to-result flow is
  currently wired.
- The task form saves the latest target and local constraints under the selected encrypted profile,
  restores that profile's values, and clears them on profile revocation. It records a waiting state;
  it does not call a planner or present a recommendation.
- OCR: optional local RapidOCR adapter, with explicit text-to-field mapping and confirmation;
  screenshot bytes stay in memory during recognition and OCR output is not trusted automatically.
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
  state is reported as unknown until A's signed withdrawal feed is available. No report is generated
  without a planner result.
- An unsigned folder-style candidate builds with PyInstaller 6.22.3. Its per-user installer
  verifies a SHA-256 file manifest, stages upgrades, preserves previous versions, and can roll back.
  The build script limits the dependency search path to Windows system directories so unrelated
  software cannot contribute incompatible DLLs. The rebuilt candidate starts on the Windows 11
  build machine and loads Qt Core and Widgets. It relies on the target Windows system ICU; target
  Windows compatibility and install/upgrade/recovery checks remain release work. Publisher signing
  and update metadata are also outstanding.
