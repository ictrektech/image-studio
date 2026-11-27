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

## Remote Compute

Grant the Image Studio service identity access to the target and repository in V-Scheduler. A system administrator can then open **Models → Remote compute backends → Manage deployments**. Select a node, start its backend, and choose **Prepare and register** for a model prepared on the main node. Image Studio verifies and loads the weights from a read-only NFS share when available. If the share is unavailable, it copies the weights in chunks. Registration requires verified weights and an approved configuration for the actual target. To resume an interrupted copy, select the same deployment and model.

Signed-in users can select a registered deployment under **Generate → Compute node**. API callers send `compute_deployment_id` to `POST /api/v1/generate` and use the existing job and output routes. Use the approved dimensions, step count, reference mode and runtime settings for the target. Open **API → Complete API and request/response fields** for the contract.

The preparation panel shows the current step. Source verification, copying, and target verification each show a percentage based on the bytes processed for that step. Older compute backends need an updated image to report verification progress.

## Install-Time Choices

After uploading the package, the installer shows the install location,
compute profile, and runtime parameters.

### Main Runtime Parameters

| Parameter | Default | Description |
| --- | --- | --- |
| `MODEL_HUB_SHARED_MODELS_PATH` | `/data/vos_workspace/model_hub` | Model Hub shared model root; select the same public directory as Model Hub |
| `MODEL_HUB_API_URL` | `http://v-scheduler-model-hub:6005` | V-Scheduler model-management API inside the VOS network; compatible configuration key |

User sessions, generation jobs, uploaded references, and outputs are stored in `${VOS_APP_STORAGE_PATH}/data`, assigned by VOS, and are no longer exposed as a public directory in the install form.
