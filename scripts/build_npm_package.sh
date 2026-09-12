#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CLI_UI_DIR="$ROOT_DIR/src/cli-ui"
VENDOR_DIR="$CLI_UI_DIR/vendor"
PYTHON_BIN="${PYTHON_BIN:-python3.12}"
UV_BIN="${UV_BIN:-uv}"

cd "$ROOT_DIR"

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  printf 'Python 3.12 is required to build the npm runtime payload.\n' >&2
  exit 1
fi
if ! command -v "$UV_BIN" >/dev/null 2>&1; then
  printf 'uv is required to resolve the reproducible Python runtime lock.\n' >&2
  exit 1
fi

npm_version="$(node -p 'require(process.argv[1]).version' "$CLI_UI_DIR/package.json")"
python_version="$("$PYTHON_BIN" -c 'import pathlib, tomllib; print(tomllib.loads(pathlib.Path("pyproject.toml").read_text())["project"]["version"])')"
if [ "$npm_version" != "$python_version" ]; then
  printf 'Package version mismatch: npm=%s python=%s\n' "$npm_version" "$python_version" >&2
  exit 1
fi

mkdir -p "$VENDOR_DIR"
find "$VENDOR_DIR" -maxdepth 1 -type f -name 'sonex-*.whl' -delete
rm -f "$VENDOR_DIR/requirements-linux-py312.txt"

if [ ! -f "$VENDOR_DIR/youtube-runtime/server/build/main.js" ] || [ -d "$VENDOR_DIR/youtube-runtime/server/src" ]; then
  "$ROOT_DIR/scripts/build_youtube_runtime_bundle.sh" "$VENDOR_DIR/youtube-runtime"
fi

# The release build only needs tsc; dependency install scripts belong to the
# consumer install and are not required to compile the already locked TUI.
npm --prefix "$CLI_UI_DIR" ci --ignore-scripts
npm --prefix "$CLI_UI_DIR" run build
"$UV_BIN" build --wheel --no-create-gitignore --out-dir "$VENDOR_DIR" "$ROOT_DIR"
"$UV_BIN" pip compile "$ROOT_DIR/pyproject.toml" \
  --python-version 3.12 \
  --generate-hashes \
  --output-file "$VENDOR_DIR/requirements-linux-py312.txt"

wheel_count="$(find "$VENDOR_DIR" -maxdepth 1 -type f -name 'sonex-*.whl' | wc -l)"
if [ "$wheel_count" -ne 1 ]; then
  printf 'Expected exactly one Sonex wheel in %s.\n' "$VENDOR_DIR" >&2
  exit 1
fi

printf 'Npm package payload prepared in %s.\n' "$CLI_UI_DIR"
printf 'Run: (cd src/cli-ui && npm pack --dry-run)\n'
