#!/usr/bin/env bash
set -euo pipefail
# Update or generate Homebrew formula for the latest macOS release asset.
# Requires: gh (GitHub CLI) or curl+jq, shasum
# Usage:
#   packaging/homebrew/update_formula.sh vX.Y.Z   # specific tag
#   packaging/homebrew/update_formula.sh latest   # latest release (default)

TAG="${1:-latest}"
OWNER_REPO="ktalons/daPCAPpuller"
ASSET_NAME="PCAPpullerGUI-macos"
FORMULA_PATH="packaging/homebrew/Formula/pcappuller.rb"

get_download_url() {
  if command -v gh >/dev/null 2>&1; then
    if [ "$TAG" = "latest" ]; then
      gh release view -R "$OWNER_REPO" --json assets,tagName --jq \
        ".assets[] | select(.name == \"$ASSET_NAME\") | .url"
    else
      gh release view "$TAG" -R "$OWNER_REPO" --json assets --jq \
        ".assets[] | select(.name == \"$ASSET_NAME\") | .url"
    fi
  else
    if ! command -v jq >/dev/null 2>&1; then
      echo "Install jq or GitHub CLI (gh)." >&2
      exit 1
    fi
    if [ "$TAG" = "latest" ]; then
      api_url="https://api.github.com/repos/$OWNER_REPO/releases/latest"
    else
      api_url="https://api.github.com/repos/$OWNER_REPO/releases/tags/$TAG"
    fi
    curl -sSL "$api_url" | jq -r ".assets[] | select(.name == \"$ASSET_NAME\") | .browser_download_url"
  fi
}

# Resolve version from tag
if [ "$TAG" = "latest" ]; then
  if command -v gh >/dev/null 2>&1; then
    TAG=$(gh release view -R "$OWNER_REPO" --json tagName --jq .tagName)
  else
    TAG=$(curl -sSL "https://api.github.com/repos/$OWNER_REPO/releases/latest" | jq -r .tag_name)
  fi
fi
VERSION="${TAG#v}"

URL=$(get_download_url)
if [ -z "$URL" ] || [ "$URL" = "null" ]; then
  echo "Could not determine download URL for $ASSET_NAME in tag $TAG" >&2
  exit 1
fi

tmpdir=$(mktemp -d)
trap 'rm -rf "$tmpdir"' EXIT
cd "$tmpdir"
curl -sSLO "$URL"
FILE="$ASSET_NAME"
SHA=$(shasum -a 256 "$FILE" | awk '{print $1}')

cd - >/dev/null

# Update formula
sed -i.bak -e "s/^  version \".*\"/  version \"$VERSION\"/" \
           -e "s#^  url \".*\"#  url \"$URL\"#" \
           -e "s/^  sha256 \".*\"/  sha256 \"$SHA\"/" "$FORMULA_PATH"
rm -f "$FORMULA_PATH.bak"

echo "Updated $FORMULA_PATH to version $VERSION with sha256 $SHA"