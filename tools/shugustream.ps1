<#
.SYNOPSIS
    Shugu stream CLI — local dev/prod manager for the Shugu v4 stack.

.DESCRIPTION
    Subcommand dispatcher for starting, stopping, and inspecting the Shugu
    backend (FastAPI + uvicorn) and frontend (Next.js) on the dev workstation.

    State (PIDs + logs) lives in `.shugustream/` at the project root. Logs
    are captured to files so you can tail them with `shugustream logs`.

.EXAMPLE
    shugustream install       # add a `shugustream` function to $PROFILE
    shugustream dev           # start backend + frontend in dev mode
    shugustream status        # are services up?
    shugustream logs back     # tail backend log
    shugustream stop          # kill both

.NOTES
    Requires PowerShell 7+ (pwsh). Works on Windows 10/11.
    Run `. $PROFILE` after `install` to activate the shugustream function.
#>

[CmdletBinding()]
param(
    [Parameter(Position = 0)]
    [string]$Command = "help",

    [Parameter(Position = 1)]
    [string]$Arg
)

$ErrorActionPreference = "Stop"

# ─── Paths ──────────────────────────────────────────────────────────────────

$ProjectRoot = Split-Path -Parent $PSScriptRoot                 # F:\Dev\Fork\Shugu_stream
$StateDir    = Join-Path $ProjectRoot ".shugustream"
$LogDir      = Join-Path $StateDir "logs"
$StateFile   = Join-Path $StateDir "state.json"
$BackendDir  = Join-Path $ProjectRoot "backend"
$FrontendDir = Join-Path $ProjectRoot "frontend"
$EnvFile     = Join-Path $ProjectRoot "ops\env\.env"

# Derived log paths
$BackendLog    = Join-Path $LogDir "backend.log"
$BackendErrLog = Join-Path $LogDir "backend.err.log"
$FrontendLog   = Join-Path $LogDir "frontend.log"
$FrontendErrLog= Join-Path $LogDir "frontend.err.log"

# Ports
$BackendPort  = 8701
$FrontendPort = 3100

# ─── Pretty printing ────────────────────────────────────────────────────────

function Write-Ok      ([string]$msg) { Write-Host "  OK  " -ForegroundColor Green     -NoNewline; Write-Host $msg }
function Write-Warn    ([string]$msg) { Write-Host " WARN " -ForegroundColor Yellow    -NoNewline; Write-Host $msg }
function Write-Err     ([string]$msg) { Write-Host " FAIL " -ForegroundColor Red       -NoNewline; Write-Host $msg }
function Write-Step    ([string]$msg) { Write-Host "  ->  " -ForegroundColor Cyan      -NoNewline; Write-Host $msg }
function Write-Heading ([string]$msg) { Write-Host ""; Write-Host "== $msg ==" -ForegroundColor Magenta }

# ─── State management ──────────────────────────────────────────────────────

function Ensure-StateDir {
    if (-not (Test-Path $StateDir)) { New-Item -ItemType Directory -Path $StateDir -Force | Out-Null }
    if (-not (Test-Path $LogDir))   { New-Item -ItemType Directory -Path $LogDir   -Force | Out-Null }
}

function Load-State {
    if (-not (Test-Path $StateFile)) { return @{} }
    try {
        $raw = Get-Content -Raw -Path $StateFile
        if ([string]::IsNullOrWhiteSpace($raw)) { return @{} }
        $obj = $raw | ConvertFrom-Json -AsHashtable
        if ($null -eq $obj) { return @{} }
        return $obj
    } catch {
        Write-Warn "state.json unreadable, resetting"
        return @{}
    }
}

function Save-State ([hashtable]$state) {
    Ensure-StateDir
    ($state | ConvertTo-Json -Depth 4) | Set-Content -Path $StateFile -Encoding UTF8
}

function Is-ProcessAlive ([int]$procId) {
    # NOTE: do NOT name this param `$pid` — `$pid` is a PowerShell auto
    # readonly variable containing the current process PID; shadowing it
    # raises "Cannot overwrite variable pid because it is read-only".
    if ($procId -le 0) { return $false }
    try {
        $null = Get-Process -Id $procId -ErrorAction Stop
        return $true
    } catch { return $false }
}

function Cleanup-DeadPids {
    $state = Load-State
    $changed = $false
    foreach ($name in @("backend", "frontend")) {
        if ($state.ContainsKey($name)) {
            $entry = $state[$name]
            if (-not (Is-ProcessAlive $entry.pid)) {
                $state.Remove($name)
                $changed = $true
            }
        }
    }
    if ($changed) { Save-State $state }
    return $state
}

# ─── Pre-flight checks ─────────────────────────────────────────────────────

function Test-PortFree ([int]$port) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    return $null -eq $conn
}

function Get-PortHolder ([int]$port) {
    $conn = Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue
    if ($null -eq $conn) { return $null }
    try {
        $proc = Get-Process -Id $conn[0].OwningProcess -ErrorAction Stop
        return "$($proc.ProcessName) (PID $($proc.Id))"
    } catch { return "PID $($conn[0].OwningProcess)" }
}

function Preflight ([string]$mode) {
    Write-Heading "Pre-flight checks ($mode)"
    $bad = $false

    # .env
    if (Test-Path $EnvFile) { Write-Ok ".env found: $EnvFile" }
    else { Write-Err ".env missing at $EnvFile"; $bad = $true }

    # Python
    $py = Get-Command python -ErrorAction SilentlyContinue
    if ($py) { Write-Ok "python in PATH: $($py.Source)" }
    else { Write-Err "python not in PATH"; $bad = $true }

    # Node
    $node = Get-Command node -ErrorAction SilentlyContinue
    if ($node) { Write-Ok "node in PATH: $($node.Source)" }
    else { Write-Err "node not in PATH"; $bad = $true }

    # Redis
    $redisOk = Test-Connection -ComputerName 127.0.0.1 -TcpPort 6379 -TimeoutSeconds 1 -Quiet -ErrorAction SilentlyContinue
    if ($redisOk) { Write-Ok "Redis reachable on 127.0.0.1:6379" }
    else { Write-Warn "Redis not reachable on 127.0.0.1:6379 (moderation/quota/queue will fail)" }

    # Postgres
    $pgOk = Test-Connection -ComputerName 127.0.0.1 -TcpPort 5432 -TimeoutSeconds 1 -Quiet -ErrorAction SilentlyContinue
    if ($pgOk) { Write-Ok "Postgres reachable on 127.0.0.1:5432" }
    else { Write-Warn "Postgres not reachable on 127.0.0.1:5432 (archive/bans persistence disabled)" }

    # Ports
    foreach ($p in @(@{n="backend";  port=$BackendPort}, @{n="frontend"; port=$FrontendPort})) {
        if (Test-PortFree $p.port) { Write-Ok "Port $($p.port) free ($($p.n))" }
        else {
            $holder = Get-PortHolder $p.port
            Write-Err "Port $($p.port) already in use by $holder"
            $bad = $true
        }
    }

    if ($bad) {
        Write-Host ""
        Write-Err "Pre-flight failed. Fix the errors above and retry."
        exit 1
    }
}

# ─── Commands: install ─────────────────────────────────────────────────────

function Invoke-Install {
    $profilePath = $PROFILE.CurrentUserAllHosts
    $profileDir = Split-Path -Parent $profilePath
    if (-not (Test-Path $profileDir)) { New-Item -ItemType Directory -Path $profileDir -Force | Out-Null }

    $fnLine = "function shugustream { & `"$PSCommandPath`" @args }"
    $marker = "# shugustream CLI"

    if (Test-Path $profilePath) {
        $content = Get-Content -Raw -Path $profilePath
        if ($content -match [regex]::Escape($marker)) {
            Write-Warn "shugustream function already present in $profilePath"
            return
        }
    }

    $block = "`n$marker`n$fnLine`n"
    Add-Content -Path $profilePath -Value $block -Encoding UTF8
    Write-Ok "Added shugustream function to $profilePath"
    Write-Step "Reload your shell or run:  . `$PROFILE"
    Write-Step "Then try:                  shugustream"
}

# ─── Commands: start dev / prod ───────────────────────────────────────────

function Start-Backend ([string]$mode) {
    $reload = if ($mode -eq "dev") { "--reload" } else { "" }
    $cmd = @(
        "cd '$BackendDir'",
        "python -m uvicorn shugu.app:app --host 127.0.0.1 --port $BackendPort $reload"
    ) -join "; "

    $proc = Start-Process pwsh `
        -ArgumentList "-NoProfile","-NonInteractive","-Command",$cmd `
        -RedirectStandardOutput $BackendLog `
        -RedirectStandardError $BackendErrLog `
        -WindowStyle Hidden `
        -PassThru
    return $proc
}

function Start-Frontend ([string]$mode) {
    $cmd = if ($mode -eq "dev") {
        "cd '$FrontendDir'; npx next dev -p $FrontendPort"
    } else {
        "cd '$FrontendDir'; npx next start -p $FrontendPort"
    }

    $proc = Start-Process pwsh `
        -ArgumentList "-NoProfile","-NonInteractive","-Command",$cmd `
        -RedirectStandardOutput $FrontendLog `
        -RedirectStandardError $FrontendErrLog `
        -WindowStyle Hidden `
        -PassThru
    return $proc
}

function Invoke-Start ([string]$mode) {
    Ensure-StateDir
    $state = Cleanup-DeadPids

    if ($state.ContainsKey("backend") -or $state.ContainsKey("frontend")) {
        Write-Warn "Already running. Use `shugustream stop` first."
        Invoke-Status | Out-Host
        exit 1
    }

    Preflight $mode

    # Truncate logs so each start is readable.
    Set-Content -Path $BackendLog    -Value "" -Encoding UTF8
    Set-Content -Path $BackendErrLog -Value "" -Encoding UTF8
    Set-Content -Path $FrontendLog   -Value "" -Encoding UTF8
    Set-Content -Path $FrontendErrLog -Value "" -Encoding UTF8

    Write-Heading "Starting ($mode)"

    Write-Step "Backend  -> uvicorn $BackendDir (port $BackendPort)"
    $backendProc = Start-Backend $mode
    Start-Sleep -Milliseconds 800

    Write-Step "Frontend -> next $mode (port $FrontendPort)"
    $frontendProc = Start-Frontend $mode

    $now = (Get-Date).ToString("s")
    $state = @{
        backend  = @{ pid = $backendProc.Id;  mode = $mode; started_at = $now; port = $BackendPort }
        frontend = @{ pid = $frontendProc.Id; mode = $mode; started_at = $now; port = $FrontendPort }
    }
    Save-State $state

    Write-Ok "Backend PID:  $($backendProc.Id)   log: $BackendLog"
    Write-Ok "Frontend PID: $($frontendProc.Id)  log: $FrontendLog"
    Write-Host ""
    Write-Host "Backend  -> http://127.0.0.1:$BackendPort" -ForegroundColor Green
    Write-Host "Frontend -> http://127.0.0.1:$FrontendPort" -ForegroundColor Green
    Write-Host ""
    Write-Step "Tail logs with:  shugustream logs [back|front]"
    Write-Step "Stop with:       shugustream stop"
}

# ─── Commands: stop ────────────────────────────────────────────────────────

function Invoke-Stop {
    $state = Load-State
    if ($state.Count -eq 0) {
        Write-Ok "Nothing to stop."
        return
    }

    Write-Heading "Stopping"
    foreach ($name in @("frontend", "backend")) {
        if (-not $state.ContainsKey($name)) { continue }
        $entry = $state[$name]
        $id = [int]$entry.pid
        # Use taskkill /T /F: kills the entire process tree. Stop-Process
        # only targets the single PID, leaving grandchildren (python under
        # pwsh, node under pwsh) holding the ports after a kill.
        $result = & taskkill /F /T /PID $id 2>&1
        if ($LASTEXITCODE -eq 0) {
            Write-Ok "$name stopped (tree rooted at PID $id)"
        } elseif ($result -match "not found|introuvable") {
            Write-Warn "$name PID $id already dead"
        } else {
            Write-Warn "$name PID ${id}: $result"
        }
    }

    # Safety net: any leftover process still holding our ports (e.g. child
    # that outlived the pwsh launcher in a race) gets sweep-killed here.
    foreach ($p in @($BackendPort, $FrontendPort)) {
        $conn = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
        if ($conn) {
            $holderPid = $conn[0].OwningProcess
            & taskkill /F /T /PID $holderPid 2>&1 | Out-Null
            if ($LASTEXITCODE -eq 0) {
                Write-Ok "swept leftover on port $p (PID $holderPid)"
            }
        }
    }

    if (Test-Path $StateFile) { Remove-Item $StateFile -Force }
    Write-Ok "State cleared."
}

# ─── Commands: status ──────────────────────────────────────────────────────

function Invoke-Status {
    Write-Heading "Status"
    $state = Cleanup-DeadPids

    foreach ($name in @("backend", "frontend")) {
        if ($state.ContainsKey($name)) {
            $entry = $state[$name]
            Write-Ok "$name running (PID $($entry.pid), mode=$($entry.mode), since $($entry.started_at)) on :$($entry.port)"
        } else {
            Write-Warn "${name}: not running"
        }
    }

    Write-Host ""
    # Ports
    $bPort = -not (Test-PortFree $BackendPort)
    $fPort = -not (Test-PortFree $FrontendPort)
    if ($bPort) { Write-Ok "Port $BackendPort  listening (backend)" }  else { Write-Warn "Port $BackendPort  not listening" }
    if ($fPort) { Write-Ok "Port $FrontendPort listening (frontend)" } else { Write-Warn "Port $FrontendPort not listening" }

    # Health probe (best-effort)
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$BackendPort/api/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction Stop
        if ($r.StatusCode -eq 200) { Write-Ok "/api/health 200 OK" }
        else { Write-Warn "/api/health returned $($r.StatusCode)" }
    } catch {
        Write-Warn "/api/health not reachable ($($_.Exception.Message))"
    }
}

# ─── Commands: logs ────────────────────────────────────────────────────────

function Invoke-Logs ([string]$which) {
    $map = @{
        back     = $BackendLog;  backend  = $BackendLog
        front    = $FrontendLog; frontend = $FrontendLog
    }
    if ([string]::IsNullOrWhiteSpace($which)) {
        Write-Step "Usage: shugustream logs [back|front]"
        Write-Step "Showing most recent 30 lines of each:"
        foreach ($f in @(@{n="BACKEND";p=$BackendLog}, @{n="FRONTEND";p=$FrontendLog})) {
            Write-Heading $f.n
            if (Test-Path $f.p) { Get-Content -Tail 30 -Path $f.p }
            else { Write-Warn "no log yet" }
        }
        return
    }
    if (-not $map.ContainsKey($which.ToLower())) {
        Write-Err "Unknown logs target '$which' — use back|front"
        exit 1
    }
    $path = $map[$which.ToLower()]
    if (-not (Test-Path $path)) { Write-Warn "no log yet at $path"; return }
    Write-Heading "Tail -f $path  (Ctrl+C to exit)"
    Get-Content -Wait -Tail 50 -Path $path
}

# ─── Commands: build ───────────────────────────────────────────────────────

function Invoke-Build {
    Write-Heading "Backend deps (pip install -e .)"
    Push-Location $BackendDir
    try { & python -m pip install --quiet --disable-pip-version-check -e . }
    finally { Pop-Location }

    Write-Heading "Frontend deps (npm ci)"
    Push-Location $FrontendDir
    try {
        & npm ci --no-audit --no-fund
        Write-Heading "Frontend build (next build)"
        & npx next build
    } finally { Pop-Location }

    Write-Ok "Build complete."
}

# ─── Commands: health ──────────────────────────────────────────────────────

function Invoke-Health {
    Write-Heading "Health probes"
    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$BackendPort/api/health" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        Write-Ok "/api/health $($r.StatusCode)"
    } catch { Write-Err "/api/health: $($_.Exception.Message)" }

    try {
        $r = Invoke-WebRequest -Uri "http://127.0.0.1:$FrontendPort" -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        Write-Ok "frontend / $($r.StatusCode)"
    } catch { Write-Err "frontend /: $($_.Exception.Message)" }
}

# ─── Commands: help ────────────────────────────────────────────────────────

function Invoke-Help {
    Write-Host ""
    Write-Host "shugustream — Shugu v4 dev/prod launcher" -ForegroundColor Magenta
    Write-Host ""
    Write-Host "  shugustream install            " -NoNewline -ForegroundColor Cyan; Write-Host "add 'shugustream' function to `$PROFILE"
    Write-Host "  shugustream dev                " -NoNewline -ForegroundColor Cyan; Write-Host "uvicorn --reload + next dev"
    Write-Host "  shugustream prod               " -NoNewline -ForegroundColor Cyan; Write-Host "uvicorn + next start"
    Write-Host "  shugustream stop               " -NoNewline -ForegroundColor Cyan; Write-Host "kill both services"
    Write-Host "  shugustream status             " -NoNewline -ForegroundColor Cyan; Write-Host "check process + ports + /api/health"
    Write-Host "  shugustream logs [back|front]  " -NoNewline -ForegroundColor Cyan; Write-Host "tail -f (no arg = last 30 lines each)"
    Write-Host "  shugustream build              " -NoNewline -ForegroundColor Cyan; Write-Host "pip install -e . + npm ci + next build"
    Write-Host "  shugustream health             " -NoNewline -ForegroundColor Cyan; Write-Host "HTTP probe /api/health + frontend /"
    Write-Host "  shugustream help               " -NoNewline -ForegroundColor Cyan; Write-Host "this screen"
    Write-Host ""
    Write-Host "Paths:" -ForegroundColor DarkGray
    Write-Host "  project root:  $ProjectRoot" -ForegroundColor DarkGray
    Write-Host "  state dir:     $StateDir" -ForegroundColor DarkGray
    Write-Host "  logs dir:      $LogDir" -ForegroundColor DarkGray
    Write-Host ""
    Invoke-Status
}

# ─── Dispatcher ────────────────────────────────────────────────────────────

switch ($Command.ToLower()) {
    "install" { Invoke-Install; break }
    "dev"     { Invoke-Start "dev";  break }
    "prod"    { Invoke-Start "prod"; break }
    "stop"    { Invoke-Stop;   break }
    "status"  { Invoke-Status; break }
    "logs"    { Invoke-Logs $Arg; break }
    "build"   { Invoke-Build;  break }
    "health"  { Invoke-Health; break }
    "help"    { Invoke-Help;   break }
    default   {
        Write-Err "Unknown command '$Command'"
        Invoke-Help
        exit 1
    }
}
