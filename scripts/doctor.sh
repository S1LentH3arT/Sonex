#!/usr/bin/env bash
set -u

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI_UI_DIR="$ROOT_DIR/src/cli-ui"
VENV_DIR="$ROOT_DIR/.venv"
VENV_PY="$VENV_DIR/bin/python3.12"
LAUNCHER="$ROOT_DIR/scripts/sonex"
USER_BIN="${SONEX_USER_BIN:-$HOME/.local/bin}"
EXPECTED_USER_SHIM="$USER_BIN/sonex"
RUNTIME_NODE_PACKAGES=(
  react
  ink
  ink-image
  ink-text-input
  terminal-image
  ws
)
STATUS=0

ok() {
  printf 'OK        %s\n' "$1"
}

missing() {
  printf 'MISSING   %s\n' "$1"
  STATUS=1
}

optional() {
  printf 'OPTIONAL  %s\n' "$1"
}

info() {
  printf 'INFO      %s\n' "$1"
}

check_cmd() {
  local cmd="$1"
  local label="$2"
  if command -v "$cmd" >/dev/null 2>&1; then
    ok "$label: $(command -v "$cmd")"
  else
    missing "$label is not installed"
  fi
}

printf 'Sonex doctor\n'
printf 'Project: %s\n\n' "$ROOT_DIR"

check_cmd python3.12 "python3.12"
check_cmd node "node"
check_cmd npm "npm"

if [ -x "$VENV_PY" ]; then
  ok "virtualenv Python: $VENV_PY"
else
  missing "virtualenv Python missing: run ./scripts/install.sh"
fi

if [ -x "$VENV_DIR/bin/sonex" ]; then
  ok "internal sonex command: $VENV_DIR/bin/sonex"
else
  missing "sonex command missing from .venv/bin"
fi

if [ -x "$LAUNCHER" ]; then
  ok "bootstrap launcher: $LAUNCHER"
else
  missing "bootstrap launcher missing or not executable: $LAUNCHER"
fi

if [ -L "$EXPECTED_USER_SHIM" ] && [ "$(readlink "$EXPECTED_USER_SHIM")" = "$LAUNCHER" ]; then
  ok "user-facing sonex shim: $EXPECTED_USER_SHIM"
elif [ -e "$EXPECTED_USER_SHIM" ]; then
  missing "user-facing sonex exists but does not point to this checkout: $EXPECTED_USER_SHIM"
else
  missing "user-facing sonex command missing: run ./scripts/install.sh"
fi

if command -v sonex >/dev/null 2>&1; then
  RESOLVED_SONEX="$(command -v sonex)"
  if [ "$RESOLVED_SONEX" = "$EXPECTED_USER_SHIM" ]; then
    ok "PATH resolves sonex to expected shim: $RESOLVED_SONEX"
  else
    missing "PATH resolves sonex to $RESOLVED_SONEX, expected $EXPECTED_USER_SHIM"
  fi
else
  missing "sonex is not available on PATH"
fi

if [ -x "$VENV_PY" ]; then
  if "$VENV_PY" -c "import typer, rich, fastapi, uvicorn, spotipy, yt_dlp" >/dev/null 2>&1; then
    ok "Python runtime dependencies import"
  else
    missing "Python dependencies are incomplete; rerun ./scripts/install.sh"
  fi
fi

if [ -d "$CLI_UI_DIR/node_modules" ]; then
  ok "TUI node_modules present"
else
  missing "TUI node_modules missing"
fi

for package in "${RUNTIME_NODE_PACKAGES[@]}"; do
  if [ -f "$CLI_UI_DIR/node_modules/$package/package.json" ]; then
    ok "TUI dependency present: $package"
  else
    missing "TUI dependency missing: $package"
  fi
done

if [ -f "$CLI_UI_DIR/dist/index.js" ]; then
  ok "TUI dist/index.js present"
else
  missing "TUI build output missing"
fi

if [ -d "$HOME/.sonex" ]; then
  ok "Sonex home exists: $HOME/.sonex"
else
  optional "Sonex home not created yet: $HOME/.sonex"
fi

if command -v vlc >/dev/null 2>&1; then
  ok "VLC player found"
elif command -v mpv >/dev/null 2>&1; then
  ok "mpv player found"
else
  optional "No vlc/mpv player found; local and YouTube playback may be unavailable"
fi

if [ -x "$VENV_PY" ]; then
  SPOTIFY_STATUS="$("$VENV_PY" -c 'from src.auth.spotify import SpotifyConfigMissingError, load_spotify_token, spotify_app_credentials
try:
    spotify_app_credentials()
    app = "app credentials configured"
except SpotifyConfigMissingError:
    app = "app credentials missing"
token = load_spotify_token()
oauth = "oauth token configured" if token and token.access_token else "oauth token missing"
print(f"{app}; {oauth}")' 2>/dev/null)"
  if [ -n "$SPOTIFY_STATUS" ]; then
    info "Spotify: $SPOTIFY_STATUS"
  else
    optional "Spotify status unavailable"
  fi
fi

printf '\n'
if [ "$STATUS" -eq 0 ]; then
  ok "Sonex looks ready"
else
  missing "Sonex is not fully installed. Run ./scripts/install.sh"
fi

exit "$STATUS"
