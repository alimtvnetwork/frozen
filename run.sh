#!/usr/bin/env bash
# Idle Shutdown — One-shot Build & Run (Bash, Linux/macOS)
# Usage:
#   ./run.sh                  # first-run setup + tests, then auto-runs `init-db`
#   ./run.sh simulate         # forwards to `idle-shutdown simulate` (auto-setup if needed)
#   ./run.sh run              # `idle-shutdown run`
#   ./run.sh <any subcmd ...> # any other CLI subcommand, args pass through
#   ./run.sh --setup          # force re-run of setup + tests
#   ./run.sh -i               # install/refresh dependencies only (no tests, no run)
#   ./run.sh -d               # deploy: install if needed, then launch the GUI window
# The venv is created/reused automatically; you never need to `source` it.

set -u

# ---------- colors ----------
if [ -t 1 ]; then
  C_RED=$'\033[31m'; C_GRN=$'\033[32m'; C_YEL=$'\033[33m'
  C_CYA=$'\033[36m'; C_GRY=$'\033[90m'; C_RST=$'\033[0m'
else
  C_RED=""; C_GRN=""; C_YEL=""; C_CYA=""; C_GRY=""; C_RST=""
fi
log()  { echo "${C_CYA}==>${C_RST} $*"; }
ok()   { echo "  ${C_GRN}✓${C_RST} $*"; }
warn() { echo "  ${C_YEL}!${C_RST} $*"; }
err()  { echo "${C_RED}ERROR:${C_RST} $*" >&2; }

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG="$SCRIPT_DIR/run.config.json"
[ -f "$CONFIG" ] || { err "run.config.json not found at $CONFIG"; exit 1; }

# ---------- arg parsing ----------
FORCE_SETUP=0
INSTALL_ONLY=0
DEPLOY_GUI=0
if [ "${1:-}" = "--setup" ]; then FORCE_SETUP=1; shift; fi
if [ "${1:-}" = "-i" ] || [ "${1:-}" = "--install" ]; then INSTALL_ONLY=1; FORCE_SETUP=1; shift; fi
if [ "${1:-}" = "-d" ] || [ "${1:-}" = "--deploy" ]; then DEPLOY_GUI=1; shift; fi
CLI_ARGS=("$@")  # everything else is forwarded to idle-shutdown

# -d implies: launch the GUI after setup
if [ "$DEPLOY_GUI" = "1" ]; then
  CLI_ARGS=("gui")
fi

# ---------- minimal JSON reader (python) ----------
jget() { python3 -c "import json,sys;d=json.load(open('$CONFIG'));k='$1'.split('.');v=d
for x in k:
 v=v[x]
print(v if not isinstance(v,list) else ' '.join(v))" 2>/dev/null; }

PROJECT_NAME=$(jget projectName)
APP_DIR=$(jget appDir)
PYTHON_MIN=$(jget pythonMin)
VENV_DIR=$(jget venvDir)
INSTALL_CMD=$(jget installCommand)
TEST_CMD=$(jget testCommand)
BUILD_CMD=$(jget buildCommand)
INSTALLER_CMD=$(jget installerCommand)

APP_PATH="$SCRIPT_DIR/$APP_DIR"
VENV_PATH="$SCRIPT_DIR/$VENV_DIR"

log "$PROJECT_NAME — one-shot setup"

# ---------- OS detect ----------
OS="$(uname -s)"
case "$OS" in
  Linux*)   PLATFORM=linux ;;
  Darwin*)  PLATFORM=macos ;;
  MINGW*|MSYS*|CYGWIN*) PLATFORM=windows ;;
  *)        PLATFORM=other ;;
esac
log "platform: $PLATFORM"

have() { command -v "$1" >/dev/null 2>&1; }

# ---------- python detection / install ----------
ensure_python() {
  if have python3; then PY=python3
  elif have python; then PY=python
  else
    warn "python not found — attempting install"
    case "$PLATFORM" in
      macos)
        if have brew; then brew install python@3.12
        else err "Install Homebrew (https://brew.sh) then re-run."; exit 1; fi ;;
      linux)
        if   have apt-get; then sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip
        elif have dnf;     then sudo dnf install -y python3 python3-pip
        elif have pacman;  then sudo pacman -S --noconfirm python python-pip
        else err "no known package manager — install Python $PYTHON_MIN+ manually"; exit 1; fi ;;
      *) err "Install Python $PYTHON_MIN+ from https://www.python.org/downloads/"; exit 1 ;;
    esac
    PY=python3
  fi
  ver=$("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])')
  ok "python $ver ($PY)"
  awk -v v="$ver" -v m="$PYTHON_MIN" 'BEGIN{split(v,a,".");split(m,b,".");
    if (a[1]<b[1] || (a[1]==b[1] && a[2]<b[2])) exit 1}' \
    || { err "Python $PYTHON_MIN+ required, found $ver"; exit 1; }
}
ensure_python

# ---------- venv ----------
if [ ! -d "$VENV_PATH" ]; then
  log "Creating virtualenv at $VENV_DIR"
  "$PY" -m venv "$VENV_PATH" || { err "venv creation failed"; exit 1; }
  ok "venv created"
else
  ok "venv already exists ($VENV_DIR)"
fi
# shellcheck disable=SC1091
. "$VENV_PATH/bin/activate" 2>/dev/null || . "$VENV_PATH/Scripts/activate"

# ---------- skip-setup fast path ----------
# If the venv already has idle-shutdown installed, skip the install/test
# phase on every subsequent run. Use --setup to force a re-install.
SKIP_SETUP=0
if [ "$FORCE_SETUP" -eq 0 ] && have idle-shutdown; then
  SKIP_SETUP=1
  ok "idle-shutdown already installed (use --setup to re-install)"
fi

# macOS: Quartz is required for real idle detection AND for the
# visible-window enumeration used by the apps/chrome capture. Without it,
# snapshots show apps=0 / chrome_tabs=0. Always make sure it's present —
# this is a no-op once installed.
if [ "$PLATFORM" = "macos" ]; then
  if ! python -c "import Quartz" >/dev/null 2>&1; then
    log "Installing pyobjc-framework-Quartz (needed for app/window capture on macOS)"
    python -m pip install --quiet pyobjc-framework-Quartz \
      && ok "pyobjc-framework-Quartz installed" \
      || warn "pyobjc-framework-Quartz install failed — snapshots will show apps=0"
  fi
fi

if [ "$SKIP_SETUP" -eq 0 ]; then
  # ---------- install ----------
  log "Installing dependencies"
  ( cd "$APP_PATH" && python -m pip install --upgrade pip >/dev/null && eval "$INSTALL_CMD" ) \
    || { err "install failed"; exit 1; }
  # macOS: install Quartz so real idle detection works (best-effort, optional).
  if [ "$PLATFORM" = "macos" ]; then
    python -m pip install --quiet pyobjc-framework-Quartz 2>/dev/null \
      && ok "pyobjc-framework-Quartz installed (real idle detection enabled)" \
      || warn "pyobjc-framework-Quartz install failed — `simulate` still works, `run` will use stub idle"
  fi
  ok "dependencies installed"

  # ---------- test ----------
  log "Running tests"
  ( cd "$APP_PATH" && eval "$TEST_CMD" ) || { err "tests failed"; exit 1; }
  ok "tests passed"
fi

# ---------- build (Windows only) ----------
if [ "$PLATFORM" = "windows" ]; then
  log "Building Windows .exe"
  ( cd "$APP_PATH" && eval "$BUILD_CMD" ) || { err "build failed"; exit 1; }
  ok "exe built (see app/dist/)"
  if have ISCC.exe || have iscc; then
    log "Compiling installer"
    ( cd "$APP_PATH" && eval "$INSTALLER_CMD" ) && ok "installer built (see app/dist/)" \
      || warn "installer compile failed"
  else
    warn "Inno Setup (ISCC.exe) not found — skipping installer step"
  fi
elif [ "$SKIP_SETUP" -eq 0 ]; then
  warn "Windows .exe build skipped on $PLATFORM (logic verified by tests above)"
fi

# ---------- forward to CLI (or run init-db on first setup) ----------
cd "$APP_PATH"
if [ "${#CLI_ARGS[@]}" -gt 0 ]; then
  log "${C_GRN}Running:${C_RST} idle-shutdown ${CLI_ARGS[*]}"
  exec idle-shutdown "${CLI_ARGS[@]}"
fi

# No subcommand passed → first-time-friendly defaults.
if [ ! -f "$HOME/.local/share/IdleShutdownRestore/IdleShutdown.db" ]; then
  log "Initializing database"
  idle-shutdown init-db || true
fi

log "${C_GRN}All done.${C_RST}"
cat <<EOF

No more activating the venv. Just run:

  ${C_CYA}./run.sh simulate${C_RST}                     full popup → countdown → dry-run shutdown
  ${C_CYA}./run.sh simulate --no-popup${C_RST}          headless variant
  ${C_CYA}./run.sh simulate --countdown 10${C_RST}      custom countdown
  ${C_CYA}./run.sh run${C_RST}                          real idle monitor (Ctrl+C to stop)
  ${C_CYA}./run.sh settings show${C_RST}                view config
  ${C_CYA}./run.sh settings set-idle 1${C_RST}          set idle threshold to 1 min
  ${C_CYA}./run.sh history${C_RST}                      shutdown history
  ${C_CYA}./run.sh --help${C_RST}                       full CLI help
  ${C_CYA}./run.sh --setup${C_RST}                      force re-install + re-run tests
EOF