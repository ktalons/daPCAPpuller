#!/usr/bin/env bash
set -euo pipefail
# Build .deb, .rpm, and .tar.zst packages for the Linux GUI binary using fpm.
# Requirements: fpm (gem install fpm), Linux binary at dist/PCAPpullerGUI-linux
# Usage: packaging/linux/build_fpm.sh

if ! command -v fpm >/dev/null 2>&1; then
  echo "fpm not found. Install with: gem install fpm" >&2
  exit 1
fi

ROOT_DIR=$(cd "$(dirname "$0")/../.." && pwd)
cd "$ROOT_DIR"

VERSION=$(grep -E '^version\s*=\s*"[0-9]+\.[0-9]+\.[0-9]+"' pyproject.toml | sed -E 's/.*"([0-9]+\.[0-9]+\.[0-9]+)"/\1/')
if [[ -z "${VERSION:-}" ]]; then
  echo "Could not parse version from pyproject.toml" >&2
  exit 1
fi

BIN_SRC="dist/PCAPpullerGUI-linux"
if [[ ! -f "$BIN_SRC" ]]; then
  echo "Linux GUI binary not found at $BIN_SRC" >&2
  echo "Build it first on Linux CI using PyInstaller (see .github/workflows/release.yml)" >&2
  exit 1
fi

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/usr/local/bin"
cp "$BIN_SRC" "$STAGE/usr/local/bin/pcappuller-gui"
chmod 0755 "$STAGE/usr/local/bin/pcappuller-gui"

OUTDIR="packaging/artifacts"
mkdir -p "$OUTDIR"

NAME="pcappuller-gui"
DESC="PCAPpuller GUI: fast PCAP window selector, merger, trimmer"
URL="https://github.com/ktalons/daPCAPpuller"
LICENSE="MIT"
MAINTAINER="Kyle Versluis"

# Debian (.deb)
fpm -s dir -t deb -n "$NAME" -v "$VERSION" \
  --license "$LICENSE" --url "$URL" --maintainer "$MAINTAINER" \
  --description "$DESC" \
  -C "$STAGE" --prefix / \
  -p "$OUTDIR/${NAME}_${VERSION}_amd64.deb"

# RPM (.rpm)
fpm -s dir -t rpm -n "$NAME" -v "$VERSION" \
  --license "$LICENSE" --url "$URL" --maintainer "$MAINTAINER" \
  --description "$DESC" \
  -C "$STAGE" --prefix / \
  -p "$OUTDIR/${NAME}-${VERSION}-1.x86_64.rpm"

# tar.zst (no package manager)
TARSTAGE=$(mktemp -d)
trap 'rm -rf "$TARSTAGE"' EXIT
mkdir -p "$TARSTAGE/usr/local/bin"
cp "$BIN_SRC" "$TARSTAGE/usr/local/bin/pcappuller-gui"
mkdir -p "$OUTDIR"
( cd "$TARSTAGE" && tar --zstd -cf "$OUTDIR/${NAME}-${VERSION}-linux-amd64.tar.zst" usr )

echo "Artifacts written to $OUTDIR/"
