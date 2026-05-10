#!/usr/bin/env bash
# Idle Shutdown — One-shot Build & Run (Bash, Linux/macOS)
# Just run:  ./run.sh
# It will: detect/install Python, create venv, install deps, run tests,
#          and (on Windows via Git-Bash/WSL) build the .exe + installer.
# Configure via run.config.json. No flags needed.

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

# ---------- install ----------
log "Installing dependencies"
( cd "$APP_PATH" && python -m pip install --upgrade pip >/dev/null && eval "$INSTALL_CMD" ) \
  || { err "install failed"; exit 1; }
ok "dependencies installed"

# ---------- test ----------
log "Running tests"
( cd "$APP_PATH" && eval "$TEST_CMD" ) || { err "tests failed"; exit 1; }
ok "tests passed"

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
else
  warn "Windows .exe build skipped on $PLATFORM (logic verified by tests above)"
fi

log "${C_GRN}All done.${C_RST}"
echo
echo "Try the CLI:  source $VENV_DIR/bin/activate && cd $APP_DIR && idle-shutdown --help"