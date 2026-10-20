<#
.SYNOPSIS
    Start the GIS Core Service (the main platform's GIS instance) locally with one command. Needs Docker
    Desktop only.

.DESCRIPTION
    Safe to run again at any time; each step only does what is still missing:

      1. .env              created from .env.example with random passwords
      2. images + stack    docker compose build, then db -> migrate (registers GIS_TENANT_ID) -> api -> web
      3. reference data    the development release and basemap, loaded once and made current

    The GIS checks no credentials: the main platform owns users and sign-in, and requests act for the
    platform's organisation (GIS_TENANT_ID). Nothing expires.

.PARAMETER SkipSampleData
    Do not load the development reference data release.

.PARAMETER WithSampleTenant
    Also load the demonstration tenant wildlife-dept (sites, devices, geofences and a batch of events near
    Habarana). The main platform brings its own devices, so this is only for exploring the GIS on its own.

.EXAMPLE
    .\setup.ps1
    (or double-click setup.cmd)
#>
[CmdletBinding()]
param(
    [switch]$SkipSampleData,
    [switch]$WithSampleTenant
)

$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot

$Utf8NoBom = New-Object System.Text.UTF8Encoding $false

function Write-Step([string]$Message) { Write-Host "`n==> $Message" -ForegroundColor Cyan }

# Runs a native command; stderr stays on the console (Docker writes progress there) and a non-zero exit
# code stops the script.
function Invoke-Native([string]$Description, [scriptblock]$Command) {
    $previous = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    try { & $Command } finally { $ErrorActionPreference = $previous }
    if ($LASTEXITCODE -ne 0) { throw "$Description failed (exit code $LASTEXITCODE)." }
}

function New-Password {
    $alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789'
    $rng = [System.Security.Cryptography.RandomNumberGenerator]::Create()
    $buffer = New-Object byte[] 1
    $result = New-Object System.Text.StringBuilder
    try {
        while ($result.Length -lt 32) {
            $rng.GetBytes($buffer)
            # 248 = 4 * 62: rejecting the rest keeps every character equally likely.
            if ($buffer[0] -lt 248) { [void]$result.Append($alphabet[$buffer[0] % 62]) }
        }
    } finally { $rng.Dispose() }
    $result.ToString()
}

function Get-EnvValue([string]$Text, [string]$Name, [string]$Default = '') {
    $match = [regex]::Match($Text, "(?m)^$Name=([^\r\n]*)")
    if ($match.Success -and $match.Groups[1].Value.Trim()) { return $match.Groups[1].Value.Trim() }
    $Default
}

function Set-EnvValue([string]$Text, [string]$Name, [string]$Value) {
    if ([regex]::IsMatch($Text, "(?m)^$Name=")) {
        return [regex]::Replace($Text, "(?m)^$Name=[^\r\n]*", { param($m) "$Name=$Value" })
    }
    $Text.TrimEnd("`r", "`n") + "`n$Name=$Value`n"
}

function Read-TextFile([string]$Path) { [System.IO.File]::ReadAllText((Join-Path $PSScriptRoot $Path)) }
function Write-TextFile([string]$Path, [string]$Text) {
    [System.IO.File]::WriteAllText((Join-Path $PSScriptRoot $Path), $Text, $Utf8NoBom)
}

# ---------------------------------------------------------------------------------------------------------
Write-Step 'Checking Docker'
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    throw 'Docker is not installed. Install Docker Desktop (https://www.docker.com/products/docker-desktop/), start it, then run this script again.'
}
$previous = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
docker info *> $null; $dockerRunning = ($LASTEXITCODE -eq 0)
docker compose version *> $null; $composeAvailable = ($LASTEXITCODE -eq 0)
$ErrorActionPreference = $previous
if (-not $dockerRunning) { throw 'Docker is not running. Start Docker Desktop, wait until it says "Engine running", then run this script again.' }
if (-not $composeAvailable) { throw 'Docker Compose v2 ("docker compose") is missing. Update Docker Desktop.' }
Write-Host 'Docker is running.'

# ---------------------------------------------------------------------------------------------------------
Write-Step 'Configuration (.env)'
if (-not (Test-Path -LiteralPath '.env')) {
    $envText = Read-TextFile '.env.example'
    Write-Host 'Created .env from .env.example.'
} else {
    $envText = Read-TextFile '.env'
    Write-Host 'Using the existing .env.'
}
foreach ($name in 'POSTGRES_SUPERUSER_PASSWORD', 'GIS_DB_MIGRATOR_PASSWORD', 'GIS_DB_APP_PASSWORD') {
    $value = Get-EnvValue $envText $name
    if (-not $value -or $value -eq 'CHANGE_ME') {
        $envText = Set-EnvValue $envText $name (New-Password)
        Write-Host "  $name set to a new random password."
    } elseif ($value -match '[$"''`\\\s]') {
        Write-Warning "$name contains `$, quotes, backslashes or spaces; Docker Compose may change it. Use letters and digits only."
    }
}
Write-TextFile '.env' $envText
$apiPort = Get-EnvValue $envText 'GIS_API_HOST_PORT' '8100'
$webPort = Get-EnvValue $envText 'GIS_WEB_HOST_PORT' '5174'

# ---------------------------------------------------------------------------------------------------------
Write-Step 'Building images (the first time this downloads packages and takes several minutes)'
Invoke-Native 'docker compose build' { docker compose build }

# ---------------------------------------------------------------------------------------------------------
Write-Step 'Map client settings (frontend/.env.local)'
$localText = if (Test-Path -LiteralPath 'frontend/.env.local') { Read-TextFile 'frontend/.env.local' } else { '' }
if (-not [regex]::IsMatch($localText, '(?m)^VITE_BASEMAP_STYLE_URL=')) {
    $localText = Set-EnvValue $localText 'VITE_BASEMAP_STYLE_URL' '/basemap/ref-2026.09-dev/style.json'
    Write-TextFile 'frontend/.env.local' $localText.TrimStart("`r", "`n")
    Write-Host 'Basemap set to the development release.'
} else {
    Write-Host 'Using the existing frontend/.env.local.'
}

# ---------------------------------------------------------------------------------------------------------
Write-Step 'Starting the stack (db -> migrate -> api -> web)'
Invoke-Native 'docker compose up' { docker compose up -d }

Write-Host "Waiting for http://localhost:$apiPort/health/ready ..."
$deadline = (Get-Date).AddMinutes(10)
$ready = $false
while (-not $ready -and (Get-Date) -lt $deadline) {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -TimeoutSec 10 -Uri "http://localhost:$apiPort/health/ready"
        $ready = ($response.StatusCode -eq 200)
    } catch { }
    if (-not $ready) { Start-Sleep -Seconds 5 }
}
if (-not $ready) { throw "The API did not become ready within 10 minutes. See: docker compose logs migrate api" }
Write-Host 'API is ready.'

# ---------------------------------------------------------------------------------------------------------
if (-not $SkipSampleData) {
    Write-Step 'Development reference data'
    $previous = $ErrorActionPreference; $ErrorActionPreference = 'Continue'
    $current = 'SELECT count(*) FROM meta.ref_data_release WHERE is_current;' |
        docker compose exec -T db sh -c 'psql -U $POSTGRES_USER -d $GIS_DB_NAME -At'
    $ErrorActionPreference = $previous
    if ("$current".Trim() -eq '1' -and -not $WithSampleTenant) {
        Write-Host 'Already loaded (a reference data release is current).'
    } else {
        $what = if ($WithSampleTenant) { 'the reference data release, basemap and the demonstration tenant' } else { 'the reference data release and basemap' }
        Write-Host "Loading $what (a few minutes)..."
        New-Item -ItemType Directory -Force -Path '.local' | Out-Null
        $log = Join-Path $PSScriptRoot '.local/sample-data.log'
        $tenantData = if ($WithSampleTenant) { 'true' } else { 'false' }
        Invoke-Native 'Loading sample data' {
            docker compose --profile sample run --rm -T -e "GIS_SAMPLE_TENANT_DATA=$tenantData" sample-data |
                Out-File -FilePath $log -Encoding utf8
        }
        Write-Host "Loaded. Details: .local/sample-data.log"
    }
}

Write-Host ''
Write-Host 'GIS Core Service is running.' -ForegroundColor Green
Write-Host "  Map client   http://localhost:$webPort   (first load can take ~20 s)"
Write-Host "  Yala / B43   http://localhost:$webPort/#map=11/6.38/81.45"
Write-Host "  API docs     http://localhost:$apiPort/docs"
Write-Host "  Readiness    http://localhost:$apiPort/health/ready"
Write-Host ''
Write-Host 'Stop: docker compose down'
