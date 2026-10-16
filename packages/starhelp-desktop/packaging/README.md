# Windows candidate build

Run `packaging/build-candidate.ps1` from a Windows PowerShell session with this component's
`[desktop,package,ocr,crypto]` extras installed. The script checks the expected repository, branch and origin
before writing into this component's `build/` and `dist/` directories.

The result is an unsigned folder-style candidate. It is suitable only for local evaluation. The
release still needs an approved code-signing certificate, published SHA-256, signed update metadata,
and target-Windows install/upgrade/recovery validation. This script does not sign, publish, update, or
install the candidate.
