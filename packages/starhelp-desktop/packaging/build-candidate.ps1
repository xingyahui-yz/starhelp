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
$pythonCommand = Get-Command $python -ErrorAction Stop
$python = $pythonCommand.Source
$plannerWheel = Join-Path $component 'packaging\vendor\starhelp_planner-0.4.0-py3-none-any.whl'
$expectedPlannerHash = '3b5b8de8f2ef71cd07f1cfb7724cb0a1564f316860232b58728386d52c47aea2'
if (-not (Test-Path -LiteralPath $plannerWheel)) { throw 'Pinned planner artifact is missing' }
$actualPlannerHash = (Get-FileHash -LiteralPath $plannerWheel -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualPlannerHash -ne $expectedPlannerHash) { throw 'Pinned planner artifact hash mismatch' }
& $python -m pip install --no-index --no-deps --force-reinstall $plannerWheel
if ($LASTEXITCODE -ne 0) { throw 'Pinned local planner wheel installation failed' }
& $python -c "from starhelp_planner import COMPONENT_VERSION, PRODUCER_ADAPTER_PROFILE; assert (COMPONENT_VERSION, PRODUCER_ADAPTER_PROFILE) == ('0.4.0', 'starhelp.producers.v0.1')"
if ($LASTEXITCODE -ne 0) { throw 'Installed local planner artifact is incompatible' }
$plannerV2Wheel = Join-Path $component 'packaging\vendor\starhelp_planner-0.5.1-py3-none-any.whl'
$expectedPlannerV2Hash = 'c79ceb58e78d11cf947c0c9f7c5c862ccad8155886fab715a76f7d8977f98322'
$plannerV2Lock = Join-Path $component 'packaging\vendor\starhelp_planner-0.5.1.lock.json'
$expectedPlannerV2LockHash = 'aceb07b0b8bec677e2ccfc39ce6b1018662991dd22524c6340eb3995134f9121'
if (-not (Test-Path -LiteralPath $plannerV2Wheel)) { throw 'Pinned producer v0.2 planner artifact is missing' }
$actualPlannerV2LockHash = (Get-FileHash -LiteralPath $plannerV2Lock -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualPlannerV2LockHash -ne $expectedPlannerV2LockHash) { throw 'Pinned producer v0.2 artifact lock hash mismatch' }
$actualPlannerV2Hash = (Get-FileHash -LiteralPath $plannerV2Wheel -Algorithm SHA256).Hash.ToLowerInvariant()
if ($actualPlannerV2Hash -ne $expectedPlannerV2Hash) { throw 'Pinned producer v0.2 planner artifact hash mismatch' }
$plannerV2Dependencies = Join-Path $component 'build\planner-v2-deps'
New-Item -ItemType Directory -Path $plannerV2Dependencies -Force | Out-Null
& $python -m pip install --no-index --no-deps --upgrade --target $plannerV2Dependencies $plannerV2Wheel
if ($LASTEXITCODE -ne 0) { throw 'Pinned producer v0.2 planner artifact extraction failed' }
$env:STARHELP_PLANNER_V2_DEPENDENCIES = $plannerV2Dependencies
& $python -c "import os, sys; sys.path.insert(0, os.environ['STARHELP_PLANNER_V2_DEPENDENCIES']); import starhelp_planner; assert starhelp_planner.COMPONENT_VERSION == '0.5.1' and 'starhelp.producers.v0.2' in starhelp_planner.PRODUCER_V2_CAPABILITIES"
if ($LASTEXITCODE -ne 0) { throw 'Pinned producer v0.2 planner artifact is incompatible' }
Remove-Item Env:\STARHELP_PLANNER_V2_DEPENDENCIES
$originalPath = $env:PATH
try {
    # Do not let unrelated installations contribute same-named DLLs (for example,
    # Poppler's ICU build) to the frozen application. Windows system DLLs remain discoverable.
    $env:PATH = "$(Join-Path $env:SystemRoot 'System32');$env:SystemRoot"
    Push-Location $component
    try {
        & $python -m PyInstaller --clean --noconfirm --distpath (Join-Path $component 'dist') `
            --workpath (Join-Path $component 'build') (Join-Path $PSScriptRoot 'StarHelp.spec')
        if ($LASTEXITCODE -ne 0) { throw 'PyInstaller candidate build failed' }
        & $python -m PyInstaller --clean --noconfirm --distpath (Join-Path $component 'dist') `
            --workpath (Join-Path $component 'build\StarHelpPlannerWorker') `
            (Join-Path $PSScriptRoot 'StarHelpPlannerWorker.spec')
        if ($LASTEXITCODE -ne 0) { throw 'PyInstaller planner worker build failed' }
        & $python -m PyInstaller --clean --noconfirm --distpath (Join-Path $component 'dist') `
            --workpath (Join-Path $component 'build\StarHelpPlannerV2Worker') `
            (Join-Path $PSScriptRoot 'StarHelpPlannerV2Worker.spec')
        if ($LASTEXITCODE -ne 0) { throw 'PyInstaller producer v0.2 worker build failed' }
    } finally {
        Pop-Location
    }
} finally {
    $env:PATH = $originalPath
}

$candidate = Join-Path $component 'dist\StarHelp'
$workerBuild = Join-Path $component 'dist\StarHelpPlannerWorker'
$workerV2Build = Join-Path $component 'dist\StarHelpPlannerV2Worker'
$workerDestination = Join-Path $candidate 'planner-worker'
$workerV2Destination = Join-Path $candidate 'planner-v2-worker'
if (-not (Test-Path -LiteralPath (Join-Path $workerBuild 'StarHelpPlannerWorker.exe'))) {
    throw 'Planner worker build output is incomplete'
}
if (-not (Test-Path -LiteralPath (Join-Path $workerV2Build 'StarHelpPlannerV2Worker.exe'))) {
    throw 'Producer v0.2 worker build output is incomplete'
}
Copy-Item -LiteralPath $workerBuild -Destination $workerDestination -Recurse
Copy-Item -LiteralPath $workerV2Build -Destination $workerV2Destination -Recurse
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
