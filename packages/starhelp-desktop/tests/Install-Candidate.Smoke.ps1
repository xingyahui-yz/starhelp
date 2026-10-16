$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

$installer = Join-Path $PSScriptRoot '..\packaging\install-candidate.ps1'
$testRoot = Join-Path ([System.IO.Path]::GetTempPath()) "starhelp-install-smoke-$([Guid]::NewGuid().ToString('N'))"
$destination = Join-Path $testRoot 'Programs\StarHelp'
$sourceV1 = Join-Path $testRoot 'candidate-v1'
$sourceV2 = Join-Path $testRoot 'candidate-v2'

function New-FixtureCandidate([string]$Path, [string]$Version) {
    New-Item -ItemType Directory -Path (Join-Path $Path '_internal') -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $Path 'StarHelp.exe') -Value "synthetic-$Version"
    Set-Content -LiteralPath (Join-Path $Path '_internal\runtime.bin') -Value 'synthetic-runtime'
    $rows = Get-ChildItem -LiteralPath $Path -File -Recurse | ForEach-Object {
        $relative = $_.FullName.Substring($Path.TrimEnd('\').Length + 1)
        $hash = (Get-FileHash -LiteralPath $_.FullName -Algorithm SHA256).Hash.ToLowerInvariant()
        "$hash *$relative"
    } | Sort-Object { $_.Substring(66) }
    [System.IO.File]::WriteAllLines(
        (Join-Path $Path 'candidate-manifest.sha256'),
        [string[]]$rows,
        [System.Text.UTF8Encoding]::new($false)
    )
}

function Assert-AppVersion([string]$Path, [string]$Expected) {
    $actual = (Get-Content -LiteralPath (Join-Path $Path 'StarHelp.exe') -Raw).Trim()
    if ($actual -ne "synthetic-$Expected") {
        throw "Expected synthetic-$Expected, got $actual."
    }
}

try {
    New-FixtureCandidate $sourceV1 'v1'
    New-FixtureCandidate $sourceV2 'v2'
    & $installer -Source $sourceV1 -Destination $destination -Confirm:$false
    Assert-AppVersion $destination 'v1'

    & $installer -Source $sourceV2 -Destination $destination -Confirm:$false
    Assert-AppVersion $destination 'v2'
    $backupCount = @(Get-ChildItem -LiteralPath (Split-Path $destination) -Directory |
        Where-Object Name -Like 'StarHelp.rollback-*').Count
    if ($backupCount -ne 1) { throw "Expected one preserved version, found $backupCount." }

    & $installer -Destination $destination -Rollback -Confirm:$false
    Assert-AppVersion $destination 'v1'
    & $installer -Destination $destination -Rollback -Confirm:$false
    Assert-AppVersion $destination 'v2'

    Set-Content -LiteralPath (Join-Path $sourceV1 'StarHelp.exe') -Value 'tampered'
    $rejected = $false
    try {
        & $installer -Source $sourceV1 -Destination $destination -Confirm:$false
    } catch {
        if ($_.Exception.Message -match 'checksum mismatch') { $rejected = $true } else { throw }
    }
    if (-not $rejected) { throw 'Tampered candidate was not rejected.' }
    Assert-AppVersion $destination 'v2'

    Write-Output 'Installer smoke passed: install, upgrade, two-way rollback, and tamper rejection.'
} finally {
    if (Test-Path -LiteralPath $testRoot) {
        $tempParent = [System.IO.Path]::GetFullPath([System.IO.Path]::GetTempPath()).TrimEnd('\') + '\'
        $resolvedTestRoot = [System.IO.Path]::GetFullPath($testRoot)
        if (-not $resolvedTestRoot.StartsWith($tempParent, [System.StringComparison]::OrdinalIgnoreCase) -or
            (Split-Path -Leaf $resolvedTestRoot) -notmatch '^starhelp-install-smoke-[0-9a-f]{32}$') {
            throw 'Refusing to remove a path outside this test run temporary directory.'
        }
        Remove-Item -LiteralPath $testRoot -Recurse -Force
    }
}
