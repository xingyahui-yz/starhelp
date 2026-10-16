$ErrorActionPreference = 'Stop'

$component = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..')).Path
$repository = (Resolve-Path -LiteralPath (Join-Path $component '..\..')).Path
$expectedRepository = 'C:\Users\admin\Documents\ChatGPT\星铁\parallel\desktop-account'
if ($repository -ne $expectedRepository) { throw 'unexpected repository path; refusing to build' }
if ((git -C $repository branch --show-current) -ne 'codex/mvp-desktop-account') {
    throw 'unexpected branch; refusing to build'
}
if ((git -C $repository remote get-url origin) -ne 'https://github.com/xingyahui-yz/starhelp.git') {
    throw 'unexpected origin; refusing to build'
}

$python = if ($env:STARHELP_PYTHON) { $env:STARHELP_PYTHON } else { 'python' }
& $python -c "import PyInstaller, PySide6, onnxruntime, PIL; from rapidocr import RapidOCR; from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey" 2>$null
if ($LASTEXITCODE -ne 0) {
    throw 'PyInstaller, PySide6 Essentials, RapidOCR, ONNX Runtime, Pillow, and cryptography must be installed in the selected build environment'
}
Push-Location $component
try {
    & $python -m PyInstaller --clean --noconfirm --distpath (Join-Path $component 'dist') `
        --workpath (Join-Path $component 'build') (Join-Path $PSScriptRoot 'StarHelp.spec')
    if ($LASTEXITCODE -ne 0) { throw 'PyInstaller candidate build failed' }
} finally {
    Pop-Location
}

$candidate = Join-Path $component 'dist\StarHelp'
$manifest = Join-Path $candidate 'candidate-manifest.sha256'
$manifestRows = Get-ChildItem -LiteralPath $candidate -File -Recurse | ForEach-Object {
    $relative = $_.FullName.Substring($candidate.TrimEnd('\').Length + 1)
    $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
    "$hash *$relative"
} | Sort-Object { $_.Substring(66) }
[System.IO.File]::WriteAllLines($manifest, [string[]]$manifestRows, [System.Text.UTF8Encoding]::new($false))
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'install-candidate.ps1') `
    -Destination (Join-Path $component 'dist\install-candidate.ps1') -Force

Write-Output 'Unsigned Windows candidate and SHA-256 file manifest created. Use dist\install-candidate.ps1 for per-user install, upgrade, and rollback evaluation. Do not distribute until publisher signing and target-Windows validation are complete.'
