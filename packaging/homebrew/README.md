# Homebrew Tap

This repository includes a Homebrew formula template to install the macOS GUI binary from Releases.

Steps:
1) Create a tap repository on GitHub (recommended):
   - ktalons/homebrew-tap
2) Copy the formula:
   - From packaging/homebrew/Formula/pcappuller.rb into your tap at Formula/pcappuller.rb
3) Update formula to latest release:
   - Install GitHub CLI (gh) or jq
   - Run: packaging/homebrew/update_formula.sh latest
   - Commit and push formula changes to your tap
4) Install from the tap:
   - brew tap ktalons/tap
   - brew install pcappuller

Notes:
- The formula installs the single-file GUI binary (pcappuller-gui)
- Wireshark CLI tools must be installed on the system PATH
- On macOS, Gatekeeper may require allowing the app in Settings -> Privacy & Security
