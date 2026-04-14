# ───────────────────────────────────────────────
#  Docksmith GUI — Windows Launcher (PowerShell)
# ───────────────────────────────────────────────

$PORT = if ($env:PORT) { $env:PORT } else { "5000" }
$HOST_ADDR = if ($env:HOST) { $env:HOST } else { "127.0.0.1" }
$SCRIPT_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path
$GUI_DIR = Join-Path $SCRIPT_DIR "gui"

Write-Host "╔══════════════════════════════════════╗" -ForegroundColor Cyan
Write-Host "║      Docksmith Dashboard GUI         ║" -ForegroundColor Cyan
Write-Host "╚══════════════════════════════════════╝" -ForegroundColor Cyan
Write-Host ""

# ── Find Python ──────────────────────────────────────────────────────────────
$PYTHON = $null

# Try py launcher first (standard Windows Python installer)
if (Get-Command "py" -ErrorAction SilentlyContinue) {
    $PYTHON = "py"
} elseif (Get-Command "python" -ErrorAction SilentlyContinue) {
    $PYTHON = "python"
} elseif (Get-Command "python3" -ErrorAction SilentlyContinue) {
    $PYTHON = "python3"
}

if (-not $PYTHON) {
    Write-Host "ERROR: Python not found. Install Python 3.8+ from https://python.org" -ForegroundColor Red
    Read-Host "Press Enter to exit"
    exit 1
}

$pyVersion = & $PYTHON --version 2>&1
Write-Host "Using Python: $pyVersion  ($PYTHON)" -ForegroundColor Green
Write-Host ""

# ── Install Flask using the SAME python that will run the server ──────────────
Write-Host "Checking GUI dependencies..." -ForegroundColor Yellow
$checkFlask = & $PYTHON -c "import flask" 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "Installing flask and flask-cors..." -ForegroundColor Yellow
    & $PYTHON -m pip install flask flask-cors --quiet
    if ($LASTEXITCODE -ne 0) {
        Write-Host "ERROR: Failed to install dependencies." -ForegroundColor Red
        Write-Host "Try manually: $PYTHON -m pip install flask flask-cors" -ForegroundColor Yellow
        Read-Host "Press Enter to exit"
        exit 1
    }
    Write-Host "Dependencies installed." -ForegroundColor Green
} else {
    Write-Host "Dependencies already satisfied." -ForegroundColor Green
}

Write-Host ""
Write-Host "Starting Docksmith GUI at http://$HOST_ADDR`:$PORT" -ForegroundColor Cyan
Write-Host "Open that URL in your browser." -ForegroundColor White
Write-Host "Press Ctrl+C to stop." -ForegroundColor White
Write-Host ""

Set-Location $SCRIPT_DIR
& $PYTHON (Join-Path $GUI_DIR "server.py") --host $HOST_ADDR --port $PORT
