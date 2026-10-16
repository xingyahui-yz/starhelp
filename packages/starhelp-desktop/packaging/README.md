# Windows candidate build

Run `packaging/build-candidate.ps1` from a Windows PowerShell session with this component's
`[desktop,package,ocr,crypto]` extras installed. The script checks the expected repository, branch
and origin before writing into this component's `build/` and `dist/` directories. It creates a
SHA-256 manifest for the candidate and copies `install-candidate.ps1` beside the app folder.

The install script verifies every file against the manifest, stages the new folder beside the target,
then swaps it into the per-user default location `%LOCALAPPDATA%\Programs\StarHelp`. Upgrades keep
the previous folder as a rollback copy. Run `install-candidate.ps1 -Rollback` to restore the newest
saved copy. It does not delete backups or install outside the current user by default. Pass
`-WhatIf` to preview an install or rollback.
Run the synthetic installer smoke flow with
`pwsh -File tests/Install-Candidate.Smoke.ps1`; it exercises install, upgrade, two-way rollback, and
tamper rejection in a temporary directory.

The result remains an unsigned folder-style candidate. SHA-256 verification detects accidental
corruption but does not authenticate the publisher because the manifest is unsigned. The release
still needs an approved code-signing certificate, signed update metadata, and target-Windows
install/upgrade/recovery validation. The script does not publish or self-update the app.
