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
  if [[ -f "dist/PCAPpullerGUI" ]]; then
    BIN_SRC="dist/PCAPpullerGUI"
  else
    echo "Linux GUI binary not found at dist/PCAPpullerGUI-linux or dist/PCAPpullerGUI" >&2
    echo "Build it first using PyInstaller: scripts/build_gui.sh" >&2
    exit 1
  fi
fi

STAGE=$(mktemp -d)
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/usr/local/bin"
cp "$BIN_SRC" "$STAGE/usr/local/bin/pcappuller-gui"
chmod 0755 "$STAGE/usr/local/bin/pcappuller-gui"

# Desktop entry for application menu integration
mkdir -p "$STAGE/usr/share/applications"
ICON_NAME="pcappuller"
cat > "$STAGE/usr/share/applications/pcappuller-gui.desktop" <<'EOF'
[Desktop Entry]
Name=PCAPpuller
GenericName=PCAP window selector, merger, trimmer
Comment=Select PCAPs by time and merge/trim with optional Wireshark display filter
Exec=pcappuller-gui
Terminal=false
Type=Application
Categories=Network;Utility;
Icon=pcappuller
EOF

# Install application icon(s) if available at assets/icons/pcappuller.png (or assets/icons/pcap.png)
SRC_ICON=""
if [[ -f "assets/icons/pcappuller.png" ]]; then
  SRC_ICON="assets/icons/pcappuller.png"
elif [[ -f "assets/icons/pcap.png" ]]; then
  SRC_ICON="assets/icons/pcap.png"
fi
if [[ -n "$SRC_ICON" ]]; then
  mkdir -p "$STAGE/usr/share/icons/hicolor/512x512/apps" "$STAGE/usr/share/icons/hicolor/256x256/apps"
  # Try to generate sizes with convert; otherwise copy as-is
  if command -v convert >/dev/null 2>&1; then
    convert "$SRC_ICON" -resize 512x512 "$STAGE/usr/share/icons/hicolor/512x512/apps/${ICON_NAME}.png"
    convert "$SRC_ICON" -resize 256x256 "$STAGE/usr/share/icons/hicolor/256x256/apps/${ICON_NAME}.png"
  else
    cp "$SRC_ICON" "$STAGE/usr/share/icons/hicolor/512x512/apps/${ICON_NAME}.png"
  fi
else
  echo "Warning: no icon found at assets/icons/pcappuller.png or assets/icons/pcap.png; proceeding without icon" >&2
fi

OUTDIR="$ROOT_DIR/packaging/artifacts"
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
