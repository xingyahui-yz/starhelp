# Windows candidate build

Run `packaging/build-candidate.ps1` from a Windows PowerShell session with this component's
`[desktop,package,ocr,crypto]` extras installed. The script checks the expected repository, branch
and origin before writing into this component's `build/` and `dist/` directories. It verifies and
installs the pinned offline planner wheel from `vendor/PLANNER-ARTIFACT.md`, builds the desktop and
separate `planner-worker/StarHelpPlannerWorker.exe` stdio process, creates a SHA-256 manifest for
the candidate, and copies `install-candidate.ps1` beside the app folder.

The install script verifies every file against the manifest, stages the new folder beside the target,
then swaps it into the per-user default location `%LOCALAPPDATA%\Programs\StarHelp`. Upgrades keep
the previous folder as a rollback copy. Run `install-candidate.ps1 -Rollback` to restore the newest
saved copy. It does not delete backups or install outside the current user by default. Pass
`-WhatIf` to preview an install or rollback.
Run the synthetic installer smoke flow with
`pwsh -File tests/Install-Candidate.Smoke.ps1`; it exercises install, upgrade, two-way rollback, and
tamper rejection in a temporary directory.

The worker, reusable producer request builder, and analysis-to-temporary-report runner are included
for the local adapter interface. TaskPage has a separate, explicit “synthetic interop demo” button.
After confirmation, it verifies bundled fixture hashes and the test-only Ed25519 key, creates or
reuses an encrypted profile labeled as synthetic, saves the fixture's canonical task IDs to that
profile, and runs the local planner worker in a background thread. It never reads the selected
profile or accesses the network. Any eligible report is staged for preview and still requires the
existing explicit save action. The synthetic profile can be revoked and deleted from Accounts.

This UI is only a synthetic integration substitute. Regular task creation still saves an encrypted
draft and does not submit a production request. Production submission remains unavailable until M0
task mappings, the snapshot/request contract, complete representative fixtures, and a separately
provisioned production trust anchor are frozen. The source fixture files are under
`tests/fixtures/producer-interop-v1/` and are embedded in the candidate under `demo-fixtures/`.

The result remains an unsigned folder-style candidate. SHA-256 verification detects accidental
corruption but does not authenticate the publisher because the manifest is unsigned. The release
still needs an approved code-signing certificate, signed update metadata, and target-Windows
install/upgrade/recovery validation. The script does not publish or self-update the app.
