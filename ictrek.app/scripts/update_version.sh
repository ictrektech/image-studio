#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
VERSION_FILE="${ROOT_DIR}/VERSION"
PART="${1:-patch}"

current="$(tr -d '[:space:]' < "$VERSION_FILE")"
IFS=. read -r major minor patch <<EOF_VERSION
$current
EOF_VERSION

case "$PART" in
  major) major=$((major + 1)); minor=0; patch=0 ;;
  minor) minor=$((minor + 1)); patch=0 ;;
  patch) patch=$((patch + 1)) ;;
  *) echo "usage: update_version.sh [major|minor|patch]" >&2; exit 1 ;;
esac

next="${major}.${minor}.${patch}"
echo "$next" > "$VERSION_FILE"
echo "[INFO] bumped Image Studio to ${next}"
echo "[INFO] create release tag after committing: vos-image-studio-v${next}"

