# SPDX-License-Identifier: LicenseRef-GNCL-1.0
<#
.SYNOPSIS
    Build the self-contained portable Windows bundle.

.DESCRIPTION
    Wrapper around scripts/build_portable.py, which does the work. This exists so
    a release build and a developer build are the same command, and so CI only
    has to call one entry point.

    Output goes to dist/:
        GannetNVR-<version>-win64.zip           the bundle, with GannetNVR.exe inside
        GannetNVR-<version>-win64.zip.sha256    its digest
        SHA256SUMS.txt                          same digest, release-asset name
        RELEASE-NOTES.md                        release body
        unsubstantiation.GannetNVR.yaml         winget manifest with the digest

    With -Slim, output goes to dist/slim/ by default and has a -slim suffix.
    Selected TensorFlow and OpenVINO C/C++ SDK headers are omitted; use the
    full bundle for native custom-op or extension development. Slim builds do
    not emit a winget manifest.

    Nothing here runs the bundle: only a Windows x64 host can do that.

.PARAMETER Version
    Override the version from pyproject.toml. Use this when the tag and the
    package version must agree and the file has not been bumped yet.

.PARAMETER RequirePinned
    Fail instead of trusting an unrecorded CPython digest. Release builds use
    this; a developer's first build does not, so it can record one.

.PARAMETER Slim
    Opt into removing selected SDK headers from the portable bundle.

.EXAMPLE
    pwsh scripts/build_portable.ps1

.EXAMPLE
    pwsh scripts/build_portable.ps1 -Version 0.19.1 -RequirePinned
#>
[CmdletBinding()]
param(
    [string]$Version,
    [string]$OutputDir,
    [string]$PythonVersion,
    [string]$PythonZip,
    [string]$Requirements,
    [switch]$Slim,
    [switch]$SkipWeb,
    [switch]$SkipWheels,
    [switch]$SkipArtifacts,
    [switch]$RequirePinned,
    [switch]$PlanOnly,
    [switch]$KeepStaging,
    [switch]$VerboseOutput
)

$ErrorActionPreference = "Stop"

$RepoRoot = Split-Path -Parent $PSScriptRoot
$Builder = Join-Path $PSScriptRoot "build_portable.py"
if (-not (Test-Path $Builder)) {
    Write-Error "scripts/build_portable.py is missing; run this from a full checkout"
    exit 1
}

# Returns the reported version, or nothing when this launcher cannot start.
function Get-PythonLauncher {
    param([string]$Executable, [string[]]$Prefix)

    $probe = @()
    $probe += $Prefix
    $probe += @("-c", "import sys; print('%d.%d' % sys.version_info[:2])")
    try {
        $reported = & $Executable @probe 2>$null
        if ($LASTEXITCODE -eq 0) { return ($reported | Select-Object -Last 1) }
    }
    catch {
        return $null
    }
    return $null
}

# Prefer the interpreter the application targets, then fall back to whatever is
# installed. The builder only needs a Python new enough to run pip; the
# interpreter it bundles is downloaded separately.
#
# PowerShell variables are case-insensitive, so this must not be called
# $pythonVersion: that would be the -PythonVersion parameter, and assigning
# the host's reported "3.12" here made the wrapper pass --python-version 3.12
# to the builder, which then looked for python-3.12-embed-amd64.zip (404).
$pythonExe = $null
$pythonPrefix = @()
$detectedVersion = $null

$py = Get-Command "py" -ErrorAction SilentlyContinue
if ($py) {
    $reported = Get-PythonLauncher -Executable $py.Source -Prefix @("-3.12")
    if ($reported) {
        $pythonExe = $py.Source
        $pythonPrefix = @("-3.12")
        $detectedVersion = $reported
    }
}

if (-not $pythonExe) {
    foreach ($name in @("python", "python3")) {
        $candidate = Get-Command $name -ErrorAction SilentlyContinue
        if (-not $candidate) { continue }
        $reported = Get-PythonLauncher -Executable $candidate.Source -Prefix @()
        if ($reported) {
            $pythonExe = $candidate.Source
            $detectedVersion = $reported
            break
        }
    }
}

if (-not $pythonExe) {
    Write-Error "No Python interpreter found. Install 64-bit CPython 3.12 and rerun."
    exit 1
}
Write-Verbose "Using $pythonExe $($pythonPrefix -join ' ') (Python $detectedVersion)"

$arguments = @($Builder)
if ($Version) { $arguments += @("--version", $Version) }
if ($OutputDir) { $arguments += @("--output-dir", $OutputDir) }
if ($PythonVersion) { $arguments += @("--python-version", $PythonVersion) }
if ($PythonZip) { $arguments += @("--python-zip", $PythonZip) }
if ($Requirements) { $arguments += @("--requirements", $Requirements) }
if ($Slim) { $arguments += "--slim" }
if ($SkipWeb) { $arguments += "--skip-web" }
if ($SkipWheels) { $arguments += "--skip-wheels" }
if ($SkipArtifacts) { $arguments += "--skip-artifacts" }
if ($RequirePinned) { $arguments += "--require-pinned" }
if ($PlanOnly) { $arguments += "--plan-only" }
if ($KeepStaging) { $arguments += "--keep-staging" }
if ($VerboseOutput) { $arguments += "--verbose" }

$invoke = @()
$invoke += $pythonPrefix
$invoke += $arguments

Push-Location $RepoRoot
try {
    & $pythonExe @invoke
    $code = $LASTEXITCODE
}
finally {
    Pop-Location
}

if ($code -ne 0) {
    Write-Error "The build failed (exit $code)."
    exit $code
}

$dist = if ($OutputDir) {
    if ([System.IO.Path]::IsPathRooted($OutputDir)) { $OutputDir }
    else { Join-Path $RepoRoot $OutputDir }
}
elseif ($Slim) { Join-Path $RepoRoot "dist\slim" }
else { Join-Path $RepoRoot "dist" }
if (-not $PlanOnly -and (Test-Path $dist)) {
    Write-Host ""
    Write-Host "Artifacts in $dist :"
    Get-ChildItem -Path $dist -File |
        Where-Object { $_.Extension -in @(".zip", ".txt", ".md", ".yaml") } |
        ForEach-Object { Write-Host ("  {0,-40} {1,10:N1} MiB" -f $_.Name, ($_.Length / 1MB)) }
}

exit 0
