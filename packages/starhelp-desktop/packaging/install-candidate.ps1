[CmdletBinding(SupportsShouldProcess = $true, ConfirmImpact = 'Medium')]
param(
    [string]$Source = (Join-Path $PSScriptRoot 'StarHelp'),
    [string]$Destination = (Join-Path $env:LOCALAPPDATA 'Programs\StarHelp'),
    [switch]$Rollback
)

$ErrorActionPreference = 'Stop'
Set-StrictMode -Version Latest

function Get-FullPath([string]$Path) {
    return [System.IO.Path]::GetFullPath($Path).TrimEnd([System.IO.Path]::DirectorySeparatorChar)
}

function Test-IsWithin([string]$Path, [string]$Parent) {
    $prefix = $Parent.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    return $Path.StartsWith($prefix, [System.StringComparison]::OrdinalIgnoreCase)
}

function Assert-Candidate([string]$CandidatePath) {
    $manifestPath = Join-Path $CandidatePath 'candidate-manifest.sha256'
    $expectedExe = Join-Path $CandidatePath 'StarHelp.exe'
    $expectedRuntime = Join-Path $CandidatePath '_internal'
    if (-not (Test-Path -LiteralPath $expectedExe -PathType Leaf) -or
        -not (Test-Path -LiteralPath $expectedRuntime -PathType Container) -or
        -not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) {
        throw 'Candidate must contain StarHelp.exe, _internal/, and candidate-manifest.sha256.'
    }

    $root = Get-FullPath $CandidatePath
    $files = @{}
    foreach ($line in [System.IO.File]::ReadAllLines($manifestPath, [System.Text.Encoding]::UTF8)) {
        if ($line -notmatch '^([0-9a-fA-F]{64}) \*(.+)$') {
            throw 'Candidate manifest has an invalid row.'
        }
        $expectedHash = $Matches[1]
        $relative = $Matches[2]
        if ([System.IO.Path]::IsPathRooted($relative) -or $relative.Contains(':') -or
            $relative -match '(^|[\\/])\.\.([\\/]|$)' -or $relative -match '(^|[\\/])\.([\\/]|$)') {
            throw 'Candidate manifest contains an unsafe path.'
        }
        $fullPath = Get-FullPath (Join-Path $root $relative)
        if (-not (Test-IsWithin $fullPath $root) -or $files.ContainsKey($relative)) {
            throw 'Candidate manifest contains an escaping or duplicate path.'
        }
        if (-not (Test-Path -LiteralPath $fullPath -PathType Leaf)) {
            throw "Candidate file is missing: $relative"
        }
        $actualHash = (Get-FileHash -LiteralPath $fullPath -Algorithm SHA256).Hash
        if ($actualHash -ne $expectedHash) {
            throw "Candidate checksum mismatch: $relative"
        }
        $files[$relative] = $true
    }

    $actualFiles = @(Get-ChildItem -LiteralPath $root -File -Recurse | Where-Object {
        $_.FullName -ne $manifestPath
    })
    if ($actualFiles.Count -ne $files.Count) {
        throw 'Candidate file set does not match its manifest.'
    }
    foreach ($file in $actualFiles) {
        $relative = $file.FullName.Substring($root.Length + 1)
        if (-not $files.ContainsKey($relative)) {
            throw "Candidate contains an unlisted file: $relative"
        }
    }
}

function Assert-NotRunning([string]$InstallPath) {
    $expectedExe = Join-Path $InstallPath 'StarHelp.exe'
    $running = Get-Process -Name StarHelp -ErrorAction SilentlyContinue | Where-Object {
        try { (Get-FullPath $_.Path) -eq (Get-FullPath $expectedExe) } catch { $false }
    }
    if ($running) {
        throw 'Close StarHelp from this install directory before installing or rolling back.'
    }
}

$destinationPath = Get-FullPath $Destination
$parentPath = Split-Path -Parent $destinationPath
$leafName = Split-Path -Leaf $destinationPath
if ([string]::IsNullOrWhiteSpace($leafName) -or [string]::IsNullOrWhiteSpace($parentPath)) {
    throw 'Destination must name an installation directory below a parent directory.'
}

if ($Rollback) {
    if (-not (Test-Path -LiteralPath $parentPath -PathType Container)) {
        throw 'No installation parent directory exists for rollback.'
    }
    Assert-NotRunning $destinationPath
    $backupPrefix = "$leafName.rollback-"
    $backup = Get-ChildItem -LiteralPath $parentPath -Directory | Where-Object {
        $_.Name.StartsWith($backupPrefix, [System.StringComparison]::OrdinalIgnoreCase)
    } | Sort-Object Name -Descending | Select-Object -First 1
    if (-not $backup) { throw 'No previous installation backup is available.' }
    Assert-Candidate $backup.FullName

    $current = $null
    if (Test-Path -LiteralPath $destinationPath -PathType Container) {
        $current = "$destinationPath.rollback-$([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ'))-$([Guid]::NewGuid().ToString('N').Substring(0, 8))"
    }
    if (-not $PSCmdlet.ShouldProcess($destinationPath, "Restore previous version from $($backup.FullName)")) {
        return
    }
    try {
        if ($current) { Move-Item -LiteralPath $destinationPath -Destination $current }
        Move-Item -LiteralPath $backup.FullName -Destination $destinationPath
    } catch {
        if ($current -and (Test-Path -LiteralPath $current -PathType Container) -and
            -not (Test-Path -LiteralPath $destinationPath)) {
            Move-Item -LiteralPath $current -Destination $destinationPath
        }
        throw
    }
    Write-Output "Restored $destinationPath from $($backup.Name)."
    return
}

$sourcePath = (Resolve-Path -LiteralPath $Source).Path
if (-not (Test-Path -LiteralPath $sourcePath -PathType Container)) { throw 'Source must be a candidate folder.' }
$sourcePath = Get-FullPath $sourcePath
if ($sourcePath -eq $destinationPath -or (Test-IsWithin $destinationPath $sourcePath) -or
    (Test-IsWithin $sourcePath $destinationPath)) {
    throw 'Source and destination must be separate, non-nested directories.'
}
Assert-Candidate $sourcePath
Assert-NotRunning $destinationPath
[System.IO.Directory]::CreateDirectory($parentPath) | Out-Null

$token = [Guid]::NewGuid().ToString('N')
$stagingPath = "$destinationPath.staging-$token"
$backupPath = "$destinationPath.rollback-$([DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ'))-$($token.Substring(0, 8))"
if (-not $PSCmdlet.ShouldProcess($destinationPath, 'Install verified StarHelp candidate and preserve the previous version')) {
    return
}

$previousMoved = $false
try {
    Copy-Item -LiteralPath $sourcePath -Destination $stagingPath -Recurse
    Assert-Candidate $stagingPath
    if (Test-Path -LiteralPath $destinationPath) {
        Move-Item -LiteralPath $destinationPath -Destination $backupPath
        $previousMoved = $true
    }
    try {
        Move-Item -LiteralPath $stagingPath -Destination $destinationPath
    } catch {
        if ($previousMoved -and -not (Test-Path -LiteralPath $destinationPath)) {
            Move-Item -LiteralPath $backupPath -Destination $destinationPath
            $previousMoved = $false
        }
        throw
    }
} finally {
    if (Test-Path -LiteralPath $stagingPath) {
        Remove-Item -LiteralPath $stagingPath -Recurse -Force
    }
}

if ($previousMoved) { Write-Output "Previous version preserved at $backupPath." }
Write-Output "Installed verified candidate to $destinationPath."
