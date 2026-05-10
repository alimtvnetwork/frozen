#!/usr/bin/env bash
# Idle Shutdown — Build & Run Script (Bash, Linux/macOS)
# Version: 1.0.0
# Configure via run.config.json
#
# USAGE:
#   ./run.sh -h     Show help
#   ./run.sh        Install dependencies + run tests (default)
#   ./run.sh -i     Install/update dependencies only
#   ./run.sh -t     Run tests only (skip install)
#   ./run.sh -b     Build Windows exe (Windows-only; warns on Linux/macOS)
#   ./run.sh -f     Force clean (.venv, build, dist, caches)
#   ./run.sh -r     Rebuild (-f + -i + tests)
#   ./run.sh -v     Verbose

set -u

# ---------- flags ----------
HELP=0; INSTALL=0; TESTONLY=0; BUILD=0; FORCE=0; REBUILD=0; VERBOSE=0
while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help)    HELP=1 ;;
    -i|--install) INSTALL=1 ;;
    -t|--test)    TESTONLY=1 ;;
    -b|--build)   BUILD=1 ;;
    -f|--force)   FORCE=1 ;;
    -r|--rebuild) FORCE=1; INSTALL=1 ;;
    -v|--verbose) VERBOSE=1 ;;
    *) echo "Unknown flag: $1" >&2; exit 2 ;;
  esac
  shift
done

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
vrb()  { [ "$VERBOSE" = "1" ] && echo "  ${C_GRY}· $*${C_RST}" || true; }

if [ "$HELP" = "1" ]; then
  sed -n '2,16p' "$0" | sed 's/^# \{0,1\}//'
  exit 0
fi

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
CLEAN_PATHS=$(jget cleanPaths)

APP_PATH="$SCRIPT_DIR/$APP_DIR"
VENV_PATH="$SCRIPT_DIR/$VENV_DIR"

log "$PROJECT_NAME — Bash runner"
vrb "script dir: $SCRIPT_DIR"
vrb "app dir:    $APP_PATH"
vrb "venv:       $VENV_PATH"

# ---------- OS detect ----------
OS="$(uname -s)"
case "$OS" in
  Linux*)  PLATFORM=linux ;;
  Darwin*) PLATFORM=macos ;;
  *)       PLATFORM=other ;;
esac
vrb "platform:   $PLATFORM"

# ---------- python detection / install ----------
have() { command -v "$1" >/dev/null 2>&1; }

ensure_python() {
  if have python3; then
    PY=python3
  elif have python; then
    PY=python
  else
    warn "python3 not found — attempting install"
    if [ "$PLATFORM" = "macos" ] && have brew; then
      brew install python@3.12 || { err "brew install failed"; exit 1; }
    elif [ "$PLATFORM" = "linux" ]; then
      if have apt-get; then sudo apt-get update && sudo apt-get install -y python3 python3-venv python3-pip
      elif have dnf; then sudo dnf install -y python3 python3-pip
      elif have pacman; then sudo pacman -S --noconfirm python python-pip
      else err "no known package manager — install Python $PYTHON_MIN+ manually"; exit 1; fi
    else
      err "install Python $PYTHON_MIN+ from https://www.python.org/downloads/"; exit 1
    fi
    PY=python3
  fi
  ver=$("$PY" -c 'import sys;print("%d.%d"%sys.version_info[:2])')
  ok "python $ver ($PY)"
  awk -v v="$ver" -v m="$PYTHON_MIN" 'BEGIN{split(v,a,".");split(m,b,".");
    if (a[1]<b[1] || (a[1]==b[1] && a[2]<b[2])) exit 1}' \
    || { err "Python $PYTHON_MIN+ required, found $ver"; exit 1; }
}

# ---------- clean ----------
if [ "$FORCE" = "1" ]; then
  log "Cleaning"
  for p in $CLEAN_PATHS; do
    target="$SCRIPT_DIR/$p"
    if [ -e "$target" ]; then rm -rf "$target"; ok "removed $p"; else vrb "skip $p (absent)"; fi
  done
fi

ensure_python

# ---------- venv ----------
if [ ! -d "$VENV_PATH" ]; then
  log "Creating virtualenv at $VENV_DIR"
  "$PY" -m venv "$VENV_PATH" || { err "venv creation failed"; exit 1; }
  ok "venv created"
fi
# shellcheck disable=SC1091
. "$VENV_PATH/bin/activate"
vrb "activated $(python -V 2>&1)"

# ---------- decide steps ----------
DO_INSTALL=1
DO_TEST=1
if [ "$TESTONLY" = "1" ]; then DO_INSTALL=0; fi
if [ "$INSTALL" = "1" ] && [ "$TESTONLY" = "0" ] && [ "$BUILD" = "0" ] && [ "$REBUILD" = "0" ]; then
  # -i alone = install only
  if [ "$FORCE" = "0" ]; then DO_TEST=0; fi
fi

if [ "$DO_INSTALL" = "1" ]; then
  log "Installing dependencies ($INSTALL_CMD)"
  ( cd "$APP_PATH" && python -m pip install --upgrade pip >/dev/null && eval "$INSTALL_CMD" ) \
    || { err "install failed"; exit 1; }
  ok "dependencies installed"
fi

if [ "$DO_TEST" = "1" ]; then
  log "Running tests ($TEST_CMD)"
  ( cd "$APP_PATH" && eval "$TEST_CMD" ) || { err "tests failed"; exit 1; }
  ok "tests passed"
fi

if [ "$BUILD" = "1" ]; then
  warn "Windows .exe build is Windows-only (PyInstaller + pywin32 + Inno Setup)."
  warn "Run on a Windows host:  .\\run.ps1 -b"
fi

log "${C_GRN}Done.${C_RST}"