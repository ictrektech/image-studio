# Image Studio

Image Studio is a local image generation workspace powered by
`stable-diffusion.cpp`. It provides prompt-based generation, job history,
generated-file access, and model management.

## Features

- Submit text-to-image jobs from the VOS page.
- Separate jobs and generated files automatically by current VOS user context.
- Same-account apps can call `/api/com.ictrek.image-studio`.
- Model files are owned by Model Hub and mounted read-only into Image Studio.
- The UI supports Chinese and English, and saves the language choice in the
  current VOS user's app settings.
- The app prefers VOS OIDC Fastpath for the current platform user. Jobs,
  language settings, and generated files are separated by user context without
  exposing internal user directories in the UI.

## Model

Default model: `vivibit/stable-diffusion-v1-5`.

Expected path:

```text
/modelhub/export/ms/vivibit/stable-diffusion-v1-5/current/v1-5-pruned-emaonly.safetensors
```

If the model is missing, use the Models tab to trigger Model Hub pull or sync.
