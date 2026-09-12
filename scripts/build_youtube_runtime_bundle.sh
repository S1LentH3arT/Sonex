#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST_DIR="${1:-$ROOT_DIR/src/cli-ui/vendor/youtube-runtime}"
PROVIDER_VERSION="${YOUTUBE_PROVIDER_VERSION:-1.3.2}"
ARCHIVE_URL="https://github.com/Brainicism/bgutil-ytdlp-pot-provider/archive/refs/tags/v${PROVIDER_VERSION}.tar.gz"

mkdir -p "$DEST_DIR"
staging_dir="$(mktemp -d)"
trap 'rm -rf "$staging_dir"' EXIT

curl --fail --location --retry 3 --output "$staging_dir/provider.tar.gz" "$ARCHIVE_URL"
mkdir -p "$staging_dir/provider"
tar -xzf "$staging_dir/provider.tar.gz" -C "$staging_dir/provider" --strip-components=1
npm ci --prefix "$staging_dir/provider/server" --ignore-scripts
npx --prefix "$staging_dir/provider/server" tsc

rm -rf "$DEST_DIR/server"
mkdir -p "$DEST_DIR"
cp -a "$staging_dir/provider/server" "$DEST_DIR/server"
printf '%s\n' "$PROVIDER_VERSION" > "$DEST_DIR/provider-version"
