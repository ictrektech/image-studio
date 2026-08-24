# Image Studio

Image Studio 是基于 `stable-diffusion.cpp` 的本地图像生成工作台，提供文生图、
任务记录、输出文件访问和模型管理。

## 功能

- 在 VOS 页面中输入 prompt 并提交生成任务。
- 生成任务和输出文件按当前 VOS 用户上下文自动隔离。
- 同账户应用可通过 `/api/com.ictrek.image-studio` 调用生成 API。
- 模型文件由 Model Hub 管理，Image Studio 只读挂载共享模型目录。
- 页面支持中文和 English，用户切换后会保存到当前 VOS 用户的应用设置。

## 模型

默认模型为 `vivibit/stable-diffusion-v1-5`，预期路径：

```text
/modelhub/export/ms/vivibit/stable-diffusion-v1-5/current/v1-5-pruned-emaonly.safetensors
```

如模型未就绪，可在“模型管理”标签页触发 Model Hub 下载或同步。
