<#
.SYNOPSIS
    Package the project as a zip to copy to another machine (then run setup.cmd / setup.sh there).

.DESCRIPTION
    Includes the source, the sample data and the built basemap. Leaves out what the other machine
    recreates or must not receive: .env and frontend/.env.local (local passwords and settings), .local (logs),
    node_modules, .venv, caches and build output. The database is not included; setup loads the same
    sample data on the other machine.

.PARAMETER IncludeRawData
    Also include data/raw (~150 MB of source downloads). Only needed to rebuild reference data with the
    pipeline; running the platform does not need it.

.PARAMETER OutFile
    Where to write the zip. Default: next to this folder, gis-core-service-<date>.zip.

.EXAMPLE
    .\package.ps1
#>
[CmdletBinding()]
param(
    [switch]$IncludeRawData,
    [string]$OutFile
)

$ErrorActionPreference = 'Stop'
$projectDir = $PSScriptRoot
$projectName = Split-Path -Leaf $projectDir
$parentDir = Split-Path -Parent $projectDir
if (-not $OutFile) { $OutFile = Join-Path $parentDir ("$projectName-{0:yyyy-MM-dd}.zip" -f (Get-Date)) }
$OutFile = [System.IO.Path]::GetFullPath($OutFile)

# Windows' own bsdtar writes zip entries with forward slashes (Compress-Archive in Windows PowerShell 5.1
# does not), so the archive unpacks correctly on Linux and macOS too.
$tar = Join-Path $env:SystemRoot 'System32\tar.exe'
if (-not (Test-Path -LiteralPath $tar)) { throw "tar.exe not found at $tar (Windows 10 1803 or later has it)." }

$p = $projectName
$exclude = @(
    "$p/.env", "$p/frontend/.env.local", "$p/.local",
    'node_modules', '.venv', 'venv', '__pycache__', '*.py[cod]', '*.egg-info',
    '.pytest_cache', '.mypy_cache', '.ruff_cache', '.coverage', 'htmlcov', '*.tsbuildinfo',
    "$p/frontend/dist", "$p/frontend/coverage", "$p/frontend/test-results", "$p/frontend/playwright-report",
    "$p/data/processed/*", '.DS_Store', 'Thumbs.db'
)
if (-not $IncludeRawData) { $exclude += "$p/data/raw/*" }
$arguments = @('-a', '-c', '-f', $OutFile) + ($exclude | ForEach-Object { "--exclude=$_" }) + @('-C', $parentDir, $p)

if (Test-Path -LiteralPath $OutFile) { Remove-Item -LiteralPath $OutFile -Force }
Write-Host "Packaging $projectDir"
Write-Host "  -> $OutFile"
& $tar @arguments
if ($LASTEXITCODE -ne 0) { throw "tar failed (exit code $LASTEXITCODE)." }

$sizeMb = [math]::Round((Get-Item -LiteralPath $OutFile).Length / 1MB, 1)
Write-Host ''
Write-Host "Done: $OutFile ($sizeMb MB)" -ForegroundColor Green
Write-Host 'On the other machine: install Docker Desktop, unzip, then double-click setup.cmd'
Write-Host '(Linux/macOS: bash setup.sh). Unzip outside OneDrive or other synced folders for speed.'
