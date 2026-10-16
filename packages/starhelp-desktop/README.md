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
- The task form saves the latest target and local constraints under the selected encrypted profile,
  restores that profile's values, and clears them on profile revocation. It records a waiting state;
  it does not call a planner or present a recommendation.
- OCR: optional local RapidOCR adapter, with explicit text-to-field mapping and confirmation;
  screenshot bytes stay in memory during recognition and OCR output is not trusted automatically.
- An unsigned folder-style candidate builds with PyInstaller 6.22.3. Its per-user installer
  verifies a SHA-256 file manifest, stages upgrades, preserves previous versions, and can roll back.
  The frozen executable currently fails in the `PySide6.QtWidgets` import chain at startup on this
  build machine; do not treat this candidate as runnable. Publisher signing, update metadata, and
  target-Windows install/upgrade/recovery validation remain release work.
