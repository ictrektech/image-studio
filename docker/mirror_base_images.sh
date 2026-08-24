#!/usr/bin/env bash
set -euo pipefail

REGISTRY="${REGISTRY:-swr.cn-southwest-2.myhuaweicloud.com/ictrek}"
ACCELERATOR="${GITHUB_ACCELERATOR:-docker.1ms.run}"

usage() {
  cat <<'EOF'
Usage: ./docker/mirror_base_images.sh PROFILE

Profiles and intended hosts:
  amd        tc232
  amd-cuda   tc232
  arm        tc192
  arm-cuda   tc192
  l4t        tc192
  thor       tc97

The script pulls Docker Hub base images through an accelerator, tags them into
the ictrek registry, and pushes them for use as Dockerfile base images.
EOF
}

[ $# -eq 1 ] || { usage; exit 1; }
PROFILE="$1"

mirror() {
  src="$1"
  dst="$2"
  echo "[INFO] pull ${ACCELERATOR}/${src}"
  docker pull "${ACCELERATOR}/${src}" || docker pull "$src"
  docker tag "$src" "$dst" 2>/dev/null || docker tag "${ACCELERATOR}/${src}" "$dst"
  docker push "$dst"
}

case "$PROFILE" in
  amd|amd-cuda)
    mirror python:3.12-slim "${REGISTRY}/python:amd_3.12-slim"
    mirror node:22-alpine "${REGISTRY}/node:amd_22-alpine"
    mirror nginx:alpine "${REGISTRY}/nginx:amd_alpine"
    ;;
  arm|arm-cuda)
    mirror python:3.12-slim "${REGISTRY}/python:arm_3.12-slim"
    mirror node:22-alpine "${REGISTRY}/node:arm_22-alpine"
    mirror nginx:alpine "${REGISTRY}/nginx:arm_alpine"
    ;;
  l4t)
    mirror python:3.12-slim "${REGISTRY}/python:l4t_3.12"
    mirror node:22-alpine "${REGISTRY}/node:arm_22-alpine"
    mirror nginx:alpine "${REGISTRY}/nginx:arm_alpine"
    ;;
  thor)
    mirror python:3.12-slim "${REGISTRY}/python:thor_3.12"
    mirror node:22-alpine "${REGISTRY}/node:thor_22-alpine"
    mirror nginx:alpine "${REGISTRY}/nginx:thor_alpine"
    ;;
  *)
    echo "[ERROR] unsupported profile: $PROFILE" >&2
    exit 1
    ;;
esac
