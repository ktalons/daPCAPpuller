#!/usr/bin/env bash
set -euo pipefail
# Build GUI binary/app with PyInstaller
# Usage: scripts/build_gui.sh

if ! command -v pyinstaller >/dev/null 2>&1; then
  echo "PyInstaller not found. Install with: python3 -m pip install pyinstaller" >&2
  exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
PROJECT_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
cd "$PROJECT_ROOT"

PLATFORM=$(uname -s)

if [[ "$PLATFORM" == "Darwin" ]]; then
  # On macOS, prefer an .app bundle so Finder launches it as an application
  pyinstaller --windowed \
    --name PCAPpullerGUI \
    gui_pcappuller.py
  echo "Build complete. See dist/PCAPpullerGUI.app"
else
  # On Linux/Windows, onefile binaries are convenient
  pyinstaller --onefile --windowed \
    --name PCAPpullerGUI \
    gui_pcappuller.py
  echo "Build complete. See dist/PCAPpullerGUI (or PCAPpullerGUI.exe on Windows)."
fi
