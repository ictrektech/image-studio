# Image Studio Makefile
#
# Dev（容器内热加载，CUDA 版 sd-cli）: docker/docker-compose.dev.yml
#   源码 volume 挂载 + uvicorn --reload + GPU（nvidia-container-toolkit）
# 不使用容器、本机直跑后端：./run_dev.sh
#
# 用法:
#   make dev          启动开发容器（加 OPTS=-d 后台）
#   make dev-build    构建开发镜像
#   make dev-logs     跟踪日志
#   make dev-shell    进容器调试
#   make dev-down     停止并移除容器
#
# 前端（宿主机，连到容器后端 25050）:
#   cd frontend && BACKEND_ORIGIN=http://127.0.0.1:25050 bun dev

OPTS ?=  # 传给 docker compose 的额外参数（如 -d、--no-cache）

DEV_COMPOSE  := docker/docker-compose.dev.yml
DEV_ENV_FILE := docker/.env.dev
DEV_CMD      := docker compose --env-file $(DEV_ENV_FILE) -f $(DEV_COMPOSE)
DEV_SERVICE  := backend

.DEFAULT_GOAL := help
help:  ## 显示帮助
	@grep -Eh '^[a-zA-Z_.-]+:.*## ' $(MAKEFILE_LIST) | sort | \
	awk 'BEGIN {FS = ":.*## "}; {printf "\033[36m%-28s\033[0m %s\n", $$1, $$2}'

.PHONY: dev dev-build dev-down dev-restart dev-logs dev-ps dev-shell dev-test dev-config

# 源码是 volume 挂载的，改 app/ 下代码由 uvicorn --reload 生效，不需要重新构建。
# 只有下面三类改动才需要 make dev-build：Dockerfile.dev、pyproject.toml / uv.lock、install_sd_cpp.sh
dev:        ## [Dev] 启动开发容器（OPTS=-d 后台；镜像不存在时自动构建一次）
	$(DEV_CMD) up $(OPTS) $(DEV_SERVICE)

dev-build:  ## [Dev] 重新构建开发镜像（改 Dockerfile/依赖清单后执行，OPTS=--no-cache 全量）
	$(DEV_CMD) build $(OPTS) $(DEV_SERVICE)

dev-restart: ## [Dev] 重启容器（不重建镜像，用于重跑 uv sync / 清状态）
	$(DEV_CMD) restart $(DEV_SERVICE)

dev-down:   ## [Dev] 停止并移除容器
	$(DEV_CMD) down

dev-logs:   ## [Dev] 查看日志
	$(DEV_CMD) logs -f $(DEV_SERVICE)

dev-ps:     ## [Dev] 查看容器状态
	$(DEV_CMD) ps

dev-shell:  ## [Dev] 进入容器（sd-cli / python / pytest 调试）
	$(DEV_CMD) exec $(DEV_SERVICE) bash

dev-test:   ## [Dev] 在容器内跑后端单测
	$(DEV_CMD) exec $(DEV_SERVICE) python -m unittest discover -s tests -v

dev-config: ## [Dev] 打印解析后的 compose 配置（校验用）
	$(DEV_CMD) config
