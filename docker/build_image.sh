#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

REGISTRY="${REGISTRY:-swr.cn-southwest-2.myhuaweicloud.com/ictrek}"
BACKEND_REPOSITORY="${REGISTRY}/image-studio-backend"
FRONTEND_REPOSITORY="${REGISTRY}/image-studio-frontend"
TODAY="$(date +%Y%m%d)"
TAG_OVERRIDE=""
TARGET_SHEET=""
COMPONENT="all"
PUSH=1

usage() {
  cat <<'EOF'
Usage: ./docker/build_image.sh --sheet SHEET [--component backend|frontend|all] [--tag TAG] [--no-push]

Sheets:
  AMD_with_cuda      -> profile amd-cuda, tag amd_cuda_<date>
  AMD_with_mxn100    -> profile amd,      tag amd_<date>
  ARM_with_cuda      -> profile arm-cuda, tag arm_cuda_<date>
  ARM_without_cuda   -> profile arm,      tag arm_<date>
  l4t                -> profile l4t,      tag l4t_<date>
  thor_spark         -> profile thor,     tag thor_<date>
EOF
}

die() { echo "[ERROR] $*" >&2; exit 1; }
log() { echo "[INFO] $*"; }

profile_spec() {
  case "$1" in
    AMD_with_cuda) printf '%s|%s|%s|%s|%s\n' amd-cuda amd_cuda docker/Dockerfile.amd-cuda amd_22-alpine amd_alpine ;;
    AMD_with_mxn100) printf '%s|%s|%s|%s|%s\n' amd amd docker/Dockerfile.cpu amd_22-alpine amd_alpine ;;
    ARM_with_cuda) printf '%s|%s|%s|%s|%s\n' arm-cuda arm_cuda docker/Dockerfile.arm-cuda arm_22-alpine arm_alpine ;;
    ARM_without_cuda) printf '%s|%s|%s|%s|%s\n' arm arm docker/Dockerfile.cpu arm_22-alpine arm_alpine ;;
    l4t) printf '%s|%s|%s|%s|%s\n' l4t l4t docker/Dockerfile.l4t arm_22-alpine arm_alpine ;;
    thor_spark) printf '%s|%s|%s|%s|%s\n' thor thor docker/Dockerfile.thor thor_22 thor_alpine ;;
    *) return 1 ;;
  esac
}

while [ $# -gt 0 ]; do
  case "$1" in
    --sheet) TARGET_SHEET="${2:-}"; shift 2 ;;
    --component) COMPONENT="${2:-}"; shift 2 ;;
    --tag) TAG_OVERRIDE="${2:-}"; shift 2 ;;
    --no-push) PUSH=0; shift ;;
    -h|--help) usage; exit 0 ;;
    *) die "unknown argument: $1" ;;
  esac
done

[ -n "$TARGET_SHEET" ] || die "--sheet is required"
SPEC="$(profile_spec "$TARGET_SHEET")" || die "unsupported sheet: $TARGET_SHEET"
IFS='|' read -r PROFILE TAG_PREFIX BACKEND_DOCKERFILE NODE_TAG NGINX_TAG <<EOF_SPEC
$SPEC
EOF_SPEC

TAG="${TAG_PREFIX}_${TAG_OVERRIDE:-$TODAY}"
BACKEND_IMAGE="${BACKEND_REPOSITORY}:${TAG}"
FRONTEND_IMAGE="${FRONTEND_REPOSITORY}:${TAG}"

build() {
  docker buildx build --load --provenance=false --sbom=false "$@"
}

if [ "$COMPONENT" = "all" ] || [ "$COMPONENT" = "backend" ]; then
  log "building backend ${BACKEND_IMAGE}"
  build -f "$BACKEND_DOCKERFILE" -t "$BACKEND_IMAGE" .
  [ "$PUSH" = 0 ] || docker push "$BACKEND_IMAGE"
fi

if [ "$COMPONENT" = "all" ] || [ "$COMPONENT" = "frontend" ]; then
  log "building frontend ${FRONTEND_IMAGE}"
  build \
    --build-arg "NODE_BASE_IMAGE=${REGISTRY}/node:${NODE_TAG}" \
    --build-arg "NGINX_BASE_IMAGE=${REGISTRY}/nginx:${NGINX_TAG}" \
    -f frontend/Dockerfile -t "$FRONTEND_IMAGE" frontend
  [ "$PUSH" = 0 ] || docker push "$FRONTEND_IMAGE"
fi

log "built profile=${PROFILE} tag=${TAG}"
log "Feishu update is intentionally not embedded yet; write ${TAG} under image-studio-backend and image-studio-frontend for ${TARGET_SHEET}."

