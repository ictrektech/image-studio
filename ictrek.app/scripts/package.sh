#!/usr/bin/env bash
set -euo pipefail

APP_NAME="image_studio"
APP_ID="com.ictrek.image-studio"
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC_DIR="${ROOT_DIR}/src"
DIST_DIR="${ROOT_DIR}/dist"
STAGE_DIR="${DIST_DIR}/staging"
PACKAGE_ROOT="${DIST_DIR}/package-root"
VERSION_FILE="${ROOT_DIR}/VERSION"

VERSION="$(tr -d '[:space:]' < "$VERSION_FILE")"

PROFILES="amd amd-cuda arm arm-cuda l4t thor"
COMPONENTS="FRONTEND image-studio-frontend swr.cn-southwest-2.myhuaweicloud.com/ictrek/image-studio-frontend
BACKEND image-studio-backend swr.cn-southwest-2.myhuaweicloud.com/ictrek/image-studio-backend"

env_key() {
  printf '%s' "$1" | tr '[:lower:]-' '[:upper:]_'
}

tag_for_profile() {
  case "$1" in
    amd) printf 'amd_%s\n' "$(date +%Y%m%d)" ;;
    amd-cuda) printf 'amd_cuda_%s\n' "$(date +%Y%m%d)" ;;
    arm) printf 'arm_%s\n' "$(date +%Y%m%d)" ;;
    arm-cuda) printf 'arm_cuda_%s\n' "$(date +%Y%m%d)" ;;
    l4t) printf 'l4t_%s\n' "$(date +%Y%m%d)" ;;
    thor) printf 'thor_%s\n' "$(date +%Y%m%d)" ;;
  esac
}

render_template() {
  src="$1"
  dst="$2"
  sed "s/__APP_VERSION__/${VERSION}/g" "$src" > "$dst"
}

rm -rf "$DIST_DIR"
mkdir -p "$STAGE_DIR" "$PACKAGE_ROOT"

for file in manifest.yml docker-compose.yml configs.yml routers.yml README.zh-CN.md README.en.md; do
  render_template "$SRC_DIR/$file" "$STAGE_DIR/$file"
done

{
  while read -r kind component repo; do
    [ -n "$kind" ] || continue
    for profile in $PROFILES; do
      suffix="$(env_key "$profile")"
      tag="$(tag_for_profile "$profile")"
      printf 'IMAGE_STUDIO_%s_%s_IMAGE=%s:%s\n' "$kind" "$suffix" "$repo" "$tag"
    done
  done <<EOF_COMPONENTS
$COMPONENTS
EOF_COMPONENTS
} > "$STAGE_DIR/.env"

python3 - "$STAGE_DIR/.env" "$STAGE_DIR/docker-compose.yml" <<'PY'
import re
import sys

env_path, compose_path = sys.argv[1], sys.argv[2]
values = {}
with open(env_path, "r", encoding="utf-8") as f:
    for line in f:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key] = value

text = open(compose_path, "r", encoding="utf-8").read()

def replace(match):
    expr = match.group(1)
    if ":-" in expr:
        key, default = expr.split(":-", 1)
        return values.get(key, default)
    return values.get(expr, match.group(0))

text = re.sub(r"\$\{([^}]+)\}", replace, text)
open(compose_path, "w", encoding="utf-8").write(text)
PY

tar -C "$STAGE_DIR" -czf "$DIST_DIR/app.tar.gz" .
cp "$DIST_DIR/app.tar.gz" "$PACKAGE_ROOT/app.tar.gz"
tar -C "$PACKAGE_ROOT" -cf "$DIST_DIR/${APP_NAME}_${VERSION}_pull.tar" app.tar.gz

tar -tf "$DIST_DIR/${APP_NAME}_${VERSION}_pull.tar" | grep -qx 'app.tar.gz'
tar -tzf "$DIST_DIR/app.tar.gz" | grep -qx './manifest.yml'
tar -tzf "$DIST_DIR/app.tar.gz" | grep -qx './routers.yml'
! grep -R "__APP_VERSION__" "$STAGE_DIR"
! grep -R '\${IMAGE_STUDIO_.*_IMAGE}' "$STAGE_DIR/docker-compose.yml"

echo "[INFO] package written: $DIST_DIR/${APP_NAME}_${VERSION}_pull.tar"
