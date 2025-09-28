#!/usr/bin/env bash
set -euo pipefail
# Verify Wireshark CLI tools are available and provide install hints by OS.
# Usage: scripts/verify_wireshark_tools.sh

TOOLS=(mergecap editcap capinfos tshark)
MISSING=()

for t in "${TOOLS[@]}"; do
  if ! command -v "$t" >/dev/null 2>&1; then
    MISSING+=("$t")
  fi
done

if [ ${#MISSING[@]} -eq 0 ]; then
  echo "All required tools found: ${TOOLS[*]}"
  exit 0
fi

echo "Missing tools: ${MISSING[*]}" >&2
OS=$(uname -s || true)
case "$OS" in
  Darwin)
    echo "Install via Homebrew: brew install wireshark" >&2 ;;
  Linux)
    if command -v apt-get >/dev/null 2>&1; then
      echo "Debian/Ubuntu: sudo apt-get update && sudo apt-get install -y wireshark" >&2
    elif command -v dnf >/dev/null 2>&1; then
      echo "Fedora/RHEL/CentOS: sudo dnf install -y wireshark" >&2
    elif command -v pacman >/dev/null 2>&1; then
      echo "Arch/Manjaro: sudo pacman -Syu wireshark" >&2
    else
      echo "Install Wireshark CLI tools using your distribution's package manager." >&2
    fi ;;
  MINGW*|MSYS*|CYGWIN*|Windows_NT)
    echo "Windows: winget install WiresharkFoundation.Wireshark" >&2
    echo "Add Wireshark install dir (e.g. C:\\Program Files\\Wireshark) to PATH if needed." >&2 ;;
  *)
    echo "Unknown OS. Install Wireshark CLI tools from https://www.wireshark.org/download.html" >&2 ;;
 esac
exit 1
