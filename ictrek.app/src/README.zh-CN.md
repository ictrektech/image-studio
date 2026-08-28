# Image Studio

Image Studio 是基于 `stable-diffusion.cpp` 的本地图像生成工作台，提供文生图、
任务记录、输出文件访问和模型管理。

> ⚠️ **前置依赖：Model Hub**
>
> 本应用的模型生命周期依赖 Model Hub 服务，请在安装本应用前确保 Model Hub 已安装且正常运行。
>
> 安装时 `MODEL_HUB_SHARED_MODELS_PATH` 应选择与 Model Hub 相同的共享目录。Image Studio 的内置模型均由 Model Hub 从 `vivibit/image-studio-*` ModelScope 独立运行仓库拉取，首次使用时可在“模型管理”页面触发下载或同步。

## 功能

- 在 VOS 页面中输入 prompt 并提交生成任务。
- 生成任务和输出文件按当前 VOS 用户上下文自动隔离。
- 同账户应用可通过 `/api/com.ictrek.image-studio` 调用生成 API。
- 模型文件由 Model Hub 管理，Image Studio 挂载同一个共享模型目录。
- 页面支持中文和 English，用户切换后会保存到当前 VOS 用户的应用设置。
- 应用优先使用 VOS OIDC Fastpath 识别当前平台用户；生成任务、语言设置和
  输出文件会自动按用户上下文分隔，界面不显示内部用户目录。

## 模型

默认模型为 `vivibit/image-studio-sd15`，预期路径：

```text
/modelhub/export/ms/vivibit/image-studio-sd15/current/v1-5-pruned-emaonly.safetensors
```

如模型未就绪，可在“模型管理”标签页触发 Model Hub 下载或同步。

## 安装时需要选择的内容

上传安装包后，安装界面会展示安装位置、计算平台 profile 和运行参数。

### 主要运行参数

| 参数 | 默认值 | 说明 |
| --- | --- | --- |
| `MODEL_HUB_SHARED_MODELS_PATH` | `/data/vos_workspace/model_hub` | Model Hub 共享模型根目录；安装时应选择与 Model Hub 相同的公共目录 |
| `MODEL_HUB_API_URL` | `http://model-hub-backend:5005` | VOS 网络内 Model Hub 后端 API 地址 |

用户会话、生成任务、上传参考图和输出文件写入 VOS 自动分配的 `${VOS_APP_STORAGE_PATH}/data`，不再作为公共目录显示在安装表单中。
