#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI_UI_DIR="$ROOT_DIR/src/cli-ui"
VENV_DIR="$ROOT_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python3.12"
LAUNCHER="$ROOT_DIR/scripts/sonex"
USER_BIN="${SONEX_USER_BIN:-$HOME/.local/bin}"
USER_SHIM="$USER_BIN/sonex"
PYTHON_BIN=""
NPM_BIN=""
INSTALL_USER_SHIM=true
FORCE_USER_SHIM=false
NO_LAUNCH=false

usage() {
  cat <<'EOF'
Usage: ./scripts/install.sh [--no-user-shim] [--force-user-shim] [--no-launch]

Options:
  --no-user-shim      Do not create the user-facing sonex command.
  --force-user-shim   Replace an existing conflicting user-facing sonex command.
  --no-launch         Install only; used by the sonex bootstrap launcher.
EOF
}

ok() {
  printf 'OK       %s\n' "$1"
}

missing() {
  printf 'MISSING  %s\n' "$1" >&2
}

note() {
  printf 'NOTE     %s\n' "$1"
}

warn() {
  printf 'WARN     %s\n' "$1"
}

require_cmd() {
  local cmd="$1"
  local hint="$2"
  local resolved
  if ! resolved="$(command -v "$cmd")"; then
    missing "$cmd not found. $hint"
    exit 1
  fi
  case "$resolved" in
    /*) ;;
    *)
      missing "$cmd resolved to non-executable path: $resolved"
      exit 1
      ;;
  esac
  ok "$cmd found: $resolved"
  REQUIRED_CMD="$resolved"
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --no-user-shim)
      INSTALL_USER_SHIM=false
      ;;
    --force-user-shim)
      FORCE_USER_SHIM=true
      ;;
    --no-launch)
      NO_LAUNCH=true
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      missing "Unknown option: $1"
      usage >&2
      exit 1
      ;;
  esac
  shift
done

install_user_shim() {
  if [ "$INSTALL_USER_SHIM" != true ]; then
    note "Skipping user-facing sonex command because --no-user-shim was provided."
    return
  fi

  if [ ! -x "$LAUNCHER" ]; then
    missing "Expected launcher to be executable: $LAUNCHER"
    exit 1
  fi

  mkdir -p "$USER_BIN"

  if [ -e "$USER_SHIM" ] || [ -L "$USER_SHIM" ]; then
    if [ -L "$USER_SHIM" ] && [ "$(readlink "$USER_SHIM")" = "$LAUNCHER" ]; then
      ok "user-facing sonex command: $USER_SHIM"
    elif [ "$FORCE_USER_SHIM" = true ]; then
      note "Replacing existing sonex command at $USER_SHIM"
      rm -f "$USER_SHIM"
      ln -s "$LAUNCHER" "$USER_SHIM"
      ok "user-facing sonex command: $USER_SHIM"
    else
      missing "A sonex command already exists at $USER_SHIM. Re-run with --force-user-shim to replace it."
      exit 1
    fi
  else
    ln -s "$LAUNCHER" "$USER_SHIM"
    ok "user-facing sonex command: $USER_SHIM"
  fi

  case ":$PATH:" in
    *":$USER_BIN:"*) ;;
    *) warn "$USER_BIN is not in PATH. Add it to your shell profile to run sonex directly." ;;
  esac
}

cd "$ROOT_DIR"

printf 'Sonex installer\n'
printf 'Project: %s\n\n' "$ROOT_DIR"

require_cmd python3.12 "Install Python 3.12 first, then rerun this script."
PYTHON_BIN="$REQUIRED_CMD"
require_cmd node "Install Node.js first, then rerun this script."
require_cmd npm "Install npm first, then rerun this script."
NPM_BIN="$REQUIRED_CMD"

if [ ! -d "$VENV_DIR" ]; then
  note "Creating virtualenv at $VENV_DIR"
  "$PYTHON_BIN" -m venv "$VENV_DIR"
else
  note "Reusing virtualenv at $VENV_DIR"
fi

if [ ! -x "$VENV_PY" ]; then
  missing "Expected $VENV_PY to exist after virtualenv creation."
  exit 1
fi

note "Installing Python package and dependencies"
"$VENV_PY" -m pip install --upgrade pip
"$VENV_PY" -m pip install -e .
ok "Python package installed"

if [ ! -f "$CLI_UI_DIR/package-lock.json" ]; then
  missing "Missing $CLI_UI_DIR/package-lock.json; npm ci requires the lockfile."
  exit 1
fi

note "Installing TUI dependencies with npm ci"
"$NPM_BIN" --prefix "$CLI_UI_DIR" ci
ok "Node dependencies installed"

note "Building React + Ink TUI"
"$NPM_BIN" --prefix "$CLI_UI_DIR" run build
ok "TUI built"

install_user_shim

if command -v vlc >/dev/null 2>&1 || command -v mpv >/dev/null 2>&1; then
  ok "Optional local player found"
else
  note "Optional player missing: install vlc or mpv for local/YouTube playback."
fi

printf '\nInstall complete.\n'
if [ "$NO_LAUNCH" = true ]; then
  printf 'Run Sonex:\n'
else
  printf 'Run Sonex now:\n'
fi
printf '  sonex\n\n'
printf 'Internal command for debugging:\n'
printf '  %s/bin/sonex\n' "$VENV_DIR"
