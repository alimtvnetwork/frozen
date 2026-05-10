# Idle Shutdown — One-shot Build & Run (PowerShell, Windows / cross-platform pwsh)
# Just run:  .\run.ps1
# It will: detect/install Python, create venv, install deps, run tests,
#          and (on Windows) build the .exe + Inno Setup installer.
# Configure via run.config.json. No flags needed.

$ErrorActionPreference = "Stop"

function Write-Step($msg)  { Write-Host "==> $msg" -ForegroundColor Cyan }
function Write-Ok($msg)    { Write-Host "  ✓ $msg" -ForegroundColor Green }
function Write-Warn2($msg) { Write-Host "  ! $msg" -ForegroundColor Yellow }
function Write-Err($msg)   { Write-Host "ERROR: $msg" -ForegroundColor Red }
function Test-Cmd($n)      { return $null -ne (Get-Command $n -ErrorAction SilentlyContinue) }

# ---------- paths + config ----------
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
if ([string]::IsNullOrWhiteSpace($ScriptDir)) { $ScriptDir = Get-Location }
$ConfigPath = Join-Path $ScriptDir "run.config.json"
if (-not (Test-Path $ConfigPath)) { Write-Err "run.config.json not found at $ConfigPath"; exit 1 }
try { $Config = Get-Content $ConfigPath -Raw | ConvertFrom-Json }
catch { Write-Err "Failed to parse run.config.json: $_"; exit 1 }

$ProjectName  = if ($Config.projectName) { $Config.projectName } else { "Project" }
$AppDir       = $Config.appDir
$PythonMin    = if ($Config.pythonMin) { $Config.pythonMin } else { "3.11" }
$VenvDir      = if ($Config.venvDir) { $Config.venvDir } else { ".venv" }
$InstallCmd   = if ($Config.installCommand) { $Config.installCommand } else { "pip install -e .[dev]" }
$TestCmd      = if ($Config.testCommand) { $Config.testCommand } else { "python -m pytest -q" }
$BuildCmd     = if ($Config.buildCommand) { $Config.buildCommand } else { "pwsh -File build/build.ps1" }
$InstallerCmd = if ($Config.installerCommand) { $Config.installerCommand } else { "" }

$AppPath  = Join-Path $ScriptDir $AppDir
$VenvPath = Join-Path $ScriptDir $VenvDir

Write-Step "$ProjectName — one-shot setup"

# ---------- platform ----------
if ($IsWindows -or $env:OS -eq "Windows_NT") { $Platform = "windows" }
elseif ($IsMacOS) { $Platform = "macos" }
elseif ($IsLinux) { $Platform = "linux" }
else { $Platform = "other" }
Write-Step "platform: $Platform"

# ---------- python install / detect ----------
function Install-Python {
    Write-Warn2 "Python not found — attempting auto-install"
    if ($Platform -eq "windows") {
        if (Test-Cmd "winget") {
            winget install Python.Python.3.12 --accept-package-agreements --accept-source-agreements
            if ($LASTEXITCODE -ne 0) { Write-Err "winget install failed"; exit 1 }
            $env:Path = [Environment]::GetEnvironmentVariable("Path","Machine") + ";" +
                        [Environment]::GetEnvironmentVariable("Path","User")
        } else {
            Write-Err "winget unavailable. Install Python $PythonMin+ from https://www.python.org/downloads/"; exit 1
        }
    } elseif ($Platform -eq "macos" -and (Test-Cmd "brew")) {
        brew install python@3.12
    } elseif ($Platform -eq "linux") {
        if     (Test-Cmd "apt-get") { sudo apt-get update; sudo apt-get install -y python3 python3-venv python3-pip }
        elseif (Test-Cmd "dnf")     { sudo dnf install -y python3 python3-pip }
        elseif (Test-Cmd "pacman")  { sudo pacman -S --noconfirm python python-pip }
        else   { Write-Err "no known package manager — install Python $PythonMin+ manually"; exit 1 }
    } else {
        Write-Err "Cannot auto-install Python on $Platform — install $PythonMin+ manually"; exit 1
    }
}

$Py = $null
foreach ($cand in @("python3","python","py")) {
    if (Test-Cmd $cand) { $Py = $cand; break }
}
if (-not $Py) { Install-Python; $Py = if (Test-Cmd "python3") { "python3" } else { "python" } }

$pyVer = & $Py -c "import sys;print('%d.%d'%sys.version_info[:2])"
Write-Ok "python $pyVer ($Py)"
$minParts = $PythonMin.Split('.'); $curParts = $pyVer.Split('.')
if ([int]$curParts[0] -lt [int]$minParts[0] -or
    ([int]$curParts[0] -eq [int]$minParts[0] -and [int]$curParts[1] -lt [int]$minParts[1])) {
    Write-Err "Python $PythonMin+ required, found $pyVer"; exit 1
}

# ---------- venv ----------
if (-not (Test-Path $VenvPath)) {
    Write-Step "Creating virtualenv at $VenvDir"
    & $Py -m venv $VenvPath
    if ($LASTEXITCODE -ne 0) { Write-Err "venv creation failed"; exit 1 }
    Write-Ok "venv created"
} else {
    Write-Ok "venv already exists ($VenvDir)"
}

if ($Platform -eq "windows") {
    $Activate = Join-Path $VenvPath "Scripts\Activate.ps1"
} else {
    $Activate = Join-Path $VenvPath "bin/Activate.ps1"
}
if (Test-Path $Activate) { . $Activate }
else { Write-Warn2 "could not find $Activate — falling back to system python" }

Push-Location $AppPath
try {
    # ---------- install ----------
    Write-Step "Installing dependencies"
    python -m pip install --upgrade pip | Out-Null
    Invoke-Expression $InstallCmd
    if ($LASTEXITCODE -ne 0) { Write-Err "install failed"; exit 1 }
    Write-Ok "dependencies installed"

    # ---------- test ----------
    Write-Step "Running tests"
    Invoke-Expression $TestCmd
    if ($LASTEXITCODE -ne 0) { Write-Err "tests failed"; exit 1 }
    Write-Ok "tests passed"

    # ---------- build (Windows only) ----------
    if ($Platform -eq "windows") {
        Write-Step "Building Windows .exe"
        Invoke-Expression $BuildCmd
        if ($LASTEXITCODE -ne 0) { Write-Err "build failed"; exit 1 }
        Write-Ok "exe built (see app/dist/)"

        if ($InstallerCmd) {
            if (Test-Cmd "ISCC.exe") {
                Write-Step "Compiling installer"
                Invoke-Expression $InstallerCmd
                if ($LASTEXITCODE -eq 0) { Write-Ok "installer built (see app/dist/)" }
                else { Write-Warn2 "installer compile failed (exit $LASTEXITCODE)" }
            } else {
                Write-Warn2 "Inno Setup (ISCC.exe) not found — skipping installer step"
            }
        }
    } else {
        Write-Warn2 "Windows .exe build skipped on $Platform (logic verified by tests above)"
    }
}
finally { Pop-Location }

Write-Step "All done."
Write-Host ""
if ($Platform -eq "windows") {
    Write-Host "Try the CLI:  .\$VenvDir\Scripts\Activate.ps1; cd $AppDir; idle-shutdown --help"
} else {
    Write-Host "Try the CLI:  source $VenvDir/bin/activate && cd $AppDir && idle-shutdown --help"
}