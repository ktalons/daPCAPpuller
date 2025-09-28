#!/usr/bin/env bash
set -euo pipefail
# Tag a release from the version in pyproject.toml and push it.
# Usage: scripts/tag_release.sh

ROOT_DIR=$(cd "$(dirname "$0")/.." && pwd)
cd "$ROOT_DIR"

VERSION=$(grep -E '^version\s*=\s*"[0-9]+\.[0-9]+\.[0-9]+"' pyproject.toml | sed -E 's/.*"([0-9]+\.[0-9]+\.[0-9]+)"/\1/')
if [[ -z "${VERSION:-}" ]]; then
  echo "Could not parse version from pyproject.toml" >&2
  exit 1
fi
TAG="v${VERSION}"

echo "Tagging ${TAG}..."
git tag "${TAG}" || { echo "Failed to create tag" >&2; exit 1; }

echo "Pushing ${TAG}..."
git push origin "${TAG}"

echo "Done. The Release workflow will build and publish binaries."
