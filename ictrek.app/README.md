# Image Studio VOS 应用打包说明

本目录包含 VOS app `com.ictrek.image-studio` 的安装包模板。
正式发布流程以 `update_version.sh` 触发的 GitHub Actions 为准。

## 打包

正式发布不要在本地读取飞书并打包。发布入口是 `scripts/update_version.sh`：
它更新 `VERSION`、提交 release commit、推送 `vos-image-studio-v${VERSION}`
触发 tag；GitHub Actions 收到 tag 后读取飞书组件版本、生成 pull 包并发布
GitHub release / VOS App Store。

本地 `package.sh` 只用于调试模板或手动验证。它不会递增或写回 `VERSION`；
未设置 `PACKAGE_VERSION` 时读取当前 `ictrek.app/VERSION`，CI 会显式传入
tag 中解析出的 `PACKAGE_VERSION`。

```bash
cd apps/image-studio/ictrek.app
./scripts/package.sh
```

脚本只生成一个 pull 模式安装包：

```text
dist/image_studio_${VERSION}_pull.tar
```

外层 tar 仅包含 `app.tar.gz`。包内 `.env` 由飞书组件表生成，`docker-compose.yml`
中的镜像变量会在打包时渲染为完整 registry 地址；包内不嵌入容器镜像或模型权重。

## Profiles

Image Studio 使用 6 个 Docker Compose profile：

| Profile | 飞书 sheet | 说明 |
| --- | --- | --- |
| `amd` | `AMD_with_mxn100` | AMD64 CPU / 非 NVIDIA runtime |
| `amd-cuda` | `AMD_with_cuda` | AMD64 NVIDIA runtime |
| `arm` | `ARM_without_cuda`、`SOPHON_bm1688` | ARM64 CPU / 非 NVIDIA runtime |
| `arm-cuda` | `ARM_with_cuda` | ARM64 NVIDIA runtime |
| `l4t` | `l4t` | Jetson / L4T NVIDIA runtime |
| `thor` | `thor_spark` | Thor NVIDIA runtime |

CPU 与 CUDA/L4T/Thor 镜像 tag 分开维护，不假设带加速环境的镜像可在无 CUDA
设备上通用。

## VOS 集成

`manifest.yml` 声明依赖 `com.ictrek.v-scheduler`，依赖版本在打包时核验最新正式发布；模型文件由 V-Scheduler 模型管理服务维护，
Image Studio 只读挂载共享目录。用户界面使用 VOS OIDC Fastpath 获取当前平台
用户 token，后端通过 VOS `/v1000/oauth2/userinfo` 校验后，将语言设置、生成任务
和输出文件写入 `${VOS_APP_STORAGE_PATH}/data` 下当前 VOS 用户上下文对应的数据目录。该私有目录不再作为安装参数或跨应用共享目录暴露。

包内用户文档来自 `src/README.zh-CN.md` 和 `src/README.en.md`。本文件只维护
打包、发布和 profile 说明。
