#!/usr/bin/env bash
# scripts/vos-dev.sh — VOS 平台内联调（免 git push / 免构建推镜像 / 免重装应用）
#
# 一条命令起前后端、装 Traefik 临时路由（priority 高于平台正式路由，流量切到 dev），
# 前台跟随日志；Ctrl-C 统一收尾（撤路由 + 停两端）。平台上已安装的应用全程不动。
#
# 用法：
#   make vos-dev                 前端走 vite dev server（HMR，默认），后端 dev 容器热重载
#   VOS_DEV_WEB=0 make vos-dev   保真模式：构建 dist-vos 产物 + nginx 容器（二选一）
#   make vos-dev-down            撤临时路由 + 停止前后端
#   scripts/vos-dev.sh status    查看容器/前端/路由/健康状态
#   scripts/vos-dev.sh logs      跟随 dev 容器日志
#   scripts/vos-dev.sh route-off 只撤临时路由（流量切回平台已安装应用）
#
# 可覆盖的环境变量：
#   VOS_DEV_WEB(1)                  1=前端跑 vite dev server；0=改用 dist-vos 产物（保真）
#   VOS_DEV_PORT(38088)             后端宿主端口（compose 内 VOS_DEV_PORT 同名联动）
#   VOS_DEV_WEB_PORT(38089)         vite dev server 宿主端口
#   VOS_DEV_DIST_PORT(38090)        保真模式 nginx 宿主端口
#   VOS_HOST_GW_IP(172.17.0.1)      Traefik 回源宿主的网关 IP
#   VOS_TRAEFIK_CONTAINER(traefik)  Traefik 容器名
#   VOS_DEV_HEALTH_TIMEOUT(300)     等待 dev 容器健康的秒数
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

APP_ID="com.ictrek.image-studio"
BASE_PATH="/app/${APP_ID}"
API_PORT="${VOS_DEV_PORT:-38088}"
WEB_PORT="${VOS_DEV_WEB_PORT:-38089}"
DIST_PORT="${VOS_DEV_DIST_PORT:-38090}"
HOST_GW="${VOS_HOST_GW_IP:-172.17.0.1}"
TRAEFIK_CONTAINER="${VOS_TRAEFIK_CONTAINER:-traefik}"
ROUTE_DIR="${VOS_TRAEFIK_DYNAMIC_DIR:-/etc/traefik/dynamic-conf}"   # traefik 容器内路径
ROUTE_FILE="${ROUTE_DIR}/${APP_ID}.dev.yml"
ROUTE_TMPL="docker/vos-dev/traefik.dev.yml.tmpl"

log()  { printf '\033[36m[vos-dev]\033[0m %s\n' "$*"; }
warn() { printf '\033[33m[vos-dev] %s\033[0m\n' "$*" >&2; }
die()  { printf '\033[31m[vos-dev][ERROR]\033[0m %s\n' "$*" >&2; exit 1; }

use_vite() { [ "${VOS_DEV_WEB:-1}" = "1" ]; }

# profile 只在保真模式下激活（vite 模式不起 nginx 容器；down 时也要带上才能删干净）
profile_args() {
  if use_vite; then echo ""; else echo "--profile web-dist"; fi
}

compose() {
  # shellcheck disable=SC2046
  docker compose --env-file docker/.env.dev \
    -f docker/docker-compose.dev.yml -f docker/docker-compose.vos-dev.yml \
    $(profile_args) "$@"
}

port_in_use() { (exec 3<>"/dev/tcp/127.0.0.1/$1") 2>/dev/null; }

ensure_port_free() {
  if port_in_use "$1"; then
    die "端口 $1 已被占用（多半是残留的 vite/容器）。先释放，或换端口：VOS_DEV_WEB_PORT=38091 make vos-dev"
  fi
}

build_web() {
  log "构建前端：vite base=${BASE_PATH}/ → frontend/dist-vos（不污染普通 dev 的 dist/）"
  [ -d frontend/node_modules ] || (cd frontend && bun install)
  (cd frontend && bunx vite build --outDir dist-vos)
}

cmd_route_on() {
  local web_port="$1"
  if ! docker ps --format '{{.Names}}' | grep -qx "$TRAEFIK_CONTAINER"; then
    warn "未发现 Traefik 容器 ${TRAEFIK_CONTAINER}：临时路由未写入，仅能本机直连 :${API_PORT}${BASE_PATH}/"
    return 0
  fi
  sed -e "s|__HOST__|${HOST_GW}|g" \
      -e "s|__API_PORT__|${API_PORT}|g" \
      -e "s|__WEB_PORT__|${web_port}|g" \
      -e "s|__APP_ID__|${APP_ID}|g" \
      -e "s|__BASE_PATH__|${BASE_PATH}|g" \
      "$ROUTE_TMPL" \
    | docker exec -i "$TRAEFIK_CONTAINER" sh -c "cat > '${ROUTE_FILE}'"
  log "已写入临时路由 ${ROUTE_FILE}（web→:${web_port}，api→:${API_PORT}；route-off 即回退）"
}

cmd_route_off() {
  docker ps --format '{{.Names}}' | grep -qx "$TRAEFIK_CONTAINER" || return 0
  docker exec -i "$TRAEFIK_CONTAINER" sh -c "rm -f '${ROUTE_FILE}'" 2>/dev/null || true
  log "已删除临时路由，流量回到平台上已安装的应用"
}

wait_healthy() {
  local timeout="${VOS_DEV_HEALTH_TIMEOUT:-300}" waited=0
  local url="http://127.0.0.1:${API_PORT}/health"
  while [ "$waited" -lt "$timeout" ]; do
    if curl -fsS -m 3 "$url" >/dev/null 2>&1; then
      [ "$waited" -gt 0 ] && echo
      return 0
    fi
    printf '\r\033[36m[vos-dev]\033[0m 等待 dev 容器就绪（首次构建镜像较慢）… %ss/%ss' "$waited" "$timeout"
    sleep 5
    waited=$((waited + 5))
  done
  echo
  return 1
}

VITE_PID=""

kill_vite() {
  [ -n "$VITE_PID" ] || return 0
  kill "$VITE_PID" 2>/dev/null || true
  wait "$VITE_PID" 2>/dev/null || true
  VITE_PID=""
}

start_vite_bg() {
  [ -d frontend/node_modules ] || (cd frontend && bun install)
  ensure_port_free "$WEB_PORT"
  log "启动 vite dev server：http://127.0.0.1:${WEB_PORT}${BASE_PATH}/（HMR；日志与本终端共用）"
  (
    cd frontend
    VITE_ALLOWED_HOSTS=true BACKEND_ORIGIN="http://127.0.0.1:${API_PORT}" \
      exec bunx vite --port "$WEB_PORT" --strictPort --clearScreen false
  ) &
  VITE_PID=$!
}

cleanup_on_exit() {
  local rc=$?
  printf '\n'
  log "退出联调：撤路由 + 停两端"
  set +e
  kill_vite
  cmd_route_off
  compose down
  return "$rc"
}

cmd_up() {
  command -v docker >/dev/null || die "缺少 docker"
  command -v curl >/dev/null || die "缺少 curl"
  [ -f "$ROUTE_TMPL" ] || die "缺少路由模板 $ROUTE_TMPL"

  if use_vite; then
    ensure_port_free "$WEB_PORT"
  else
    ensure_port_free "$DIST_PORT"
    if [ -f frontend/dist-vos/index.html ]; then
      log "复用已有 frontend/dist-vos（改前端后需重跑 make vos-dev-web）"
    else
      build_web
    fi
  fi

  log "启动 dev 容器（后端 :${API_PORT}，uvicorn --reload + VOS SSO）"
  compose up -d

  if ! wait_healthy; then
    warn "dev 容器 ${VOS_DEV_HEALTH_TIMEOUT:-300}s 内未就绪，**未**切换平台路由（平台仍走已安装应用）"
    warn "容器保留运行以便排查：make vos-dev-logs ；就绪后重跑 make vos-dev 即可"
    exit 1
  fi
  log "dev 容器健康（http://127.0.0.1:${API_PORT}/health）"

  if use_vite; then
    start_vite_bg
    cmd_route_on "$WEB_PORT"
  else
    cmd_route_on "$DIST_PORT"
  fi

  log "就绪：在 VOS 平台侧边栏打开 Image Studio（或刷新平台内 iframe）"
  if use_vite; then
    log "  前端：vite dev server（HMR，保存即热更新）:${WEB_PORT}"
  else
    log "  前端：dist-vos 产物（保真模式）:${DIST_PORT}"
  fi
  log "  后端：uvicorn --reload :${API_PORT}；跨应用直连：其他应用用 image-studio-backend-dev:25050"
  log "  Ctrl-C 退出联调（撤路由 + 停两端）；下面开始跟随容器日志"
  printf '\n'

  trap 'cleanup_on_exit' EXIT
  compose logs -f backend
}

cmd_down() {
  set +e
  # 残留的 vite 进程（上次异常退出留下的）
  pkill -f "vite --port ${WEB_PORT}" 2>/dev/null
  cmd_route_off
  compose down
  log "dev 容器已停止"
}

cmd_status() {
  echo "── dev 容器（后端 :${API_PORT}）──"
  compose ps backend --format '  {{.Name}}\t{{.Status}}\t{{.Ports}}' 2>/dev/null || echo "  （未运行）"
  echo "── 前端 ──"
  if use_vite; then
    if curl -fsS -m 3 "http://127.0.0.1:${WEB_PORT}${BASE_PATH}/" >/dev/null 2>&1; then
      echo "  vite dev server 在跑（:${WEB_PORT}，HMR）"
    else
      echo "  vite dev server 未在跑（:${WEB_PORT} 无响应；若临时路由指向它则平台会 502）"
    fi
  else
    if docker ps --format '{{.Names}}' | grep -qx 'image-studio-vos-dev-web'; then
      echo "  nginx 产物容器在跑（:${DIST_PORT}，保真模式）"
    else
      echo "  nginx 产物容器未运行（--profile web-dist 才会启动）"
    fi
  fi
  echo "── 后端健康 ──"
  if curl -fsS -m 3 "http://127.0.0.1:${API_PORT}/health" >/dev/null 2>&1; then
    echo "  OK（http://127.0.0.1:${API_PORT}/health）"
  else
    echo "  不可达（未启动或仍在构建）"
  fi
  echo "── 临时 Traefik 路由 ${ROUTE_FILE} ──"
  docker exec -i "$TRAEFIK_CONTAINER" sh -c "test -f '${ROUTE_FILE}' && cat '${ROUTE_FILE}' || echo '  （未启用 → 平台走已安装应用）'" 2>/dev/null || echo "  （traefik 容器不可用）"
}

case "${1:-up}" in
  up)        cmd_up ;;
  down)      cmd_down ;;
  route-off) cmd_route_off ;;
  status)    cmd_status ;;
  logs)      compose logs -f backend ;;
  -h|--help|help)
    awk 'NR>1 { if ($0 ~ /^#/) print; else exit }' "$0" ;;
  *) die "未知子命令：$1（up|down|route-off|status|logs）" ;;
esac
