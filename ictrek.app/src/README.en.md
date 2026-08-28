# Image Studio

Image Studio is a local image generation workspace powered by
`stable-diffusion.cpp`. It provides prompt-based generation, job history,
generated-file access, and model management.

> ⚠️ **Prerequisite: Model Hub**
>
> This app relies on Model Hub for the model lifecycle. Install and start Model Hub before installing Image Studio.
>
> At install time, set `MODEL_HUB_SHARED_MODELS_PATH` to the same shared directory used by Model Hub. Built-in Image Studio models are pulled by Model Hub from dedicated `vivibit/image-studio-*` ModelScope runtime repositories; use the Models tab to trigger pull or sync.

## Features

- Submit text-to-image jobs from the VOS page.
- Separate jobs and generated files automatically by current VOS user context.
- Same-account apps can call `/api/com.ictrek.image-studio`.
- Model files are owned by Model Hub and mounted through the same shared model directory.
- The UI supports Chinese and English, and saves the language choice in the
  current VOS user's app settings.
- The app prefers VOS OIDC Fastpath for the current platform user. Jobs,
  language settings, and generated files are separated by user context without
  exposing internal user directories in the UI.

## Model

Default model: `vivibit/image-studio-sd15`.

Expected path:

```text
/modelhub/export/ms/vivibit/image-studio-sd15/current/v1-5-pruned-emaonly.safetensors
```

If the model is missing, use the Models tab to trigger Model Hub pull or sync.

## Install-Time Choices

After uploading the package, the installer shows the install location,
compute profile, and runtime parameters.

### Main Runtime Parameters

| Parameter | Default | Description |
| --- | --- | --- |
| `MODEL_HUB_SHARED_MODELS_PATH` | `/data/vos_workspace/model_hub` | Model Hub shared model root; select the same public directory as Model Hub |
| `MODEL_HUB_API_URL` | `http://model-hub-backend:5005` | Model Hub backend API inside the VOS network |

User sessions, generation jobs, uploaded references, and outputs are stored in `${VOS_APP_STORAGE_PATH}/data`, assigned by VOS, and are no longer exposed as a public directory in the install form.
