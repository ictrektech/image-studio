import type { GeneratePayload } from './api/client'

/** Migrate the two previously published automatic L4T presets, preserving custom input. */
export function repairLegacyL4TDefaults(current: GeneratePayload, defaults: Partial<GeneratePayload>): GeneratePayload {
  if (current.model_key !== 'sd-turbo' || current.model_variant || defaults.weight_type !== 'q4_0'
    || !defaults.max_vram || !defaults.clip_on_cpu) return current
  const generic = ['', 'f16'].includes(current.weight_type || '') && current.max_vram === 0 && current.vae_tile_size === '128x128'
  const previousL4T = current.weight_type === 'q4_0' && current.max_vram === 2
    && ['', '128x128'].includes(current.vae_tile_size || '') && !current.clip_on_cpu
  if (!generic && !previousL4T) return current
  return { ...current, weight_type: defaults.weight_type, max_vram: defaults.max_vram,
    vae_tile_size: defaults.vae_tile_size ?? '', clip_on_cpu: defaults.clip_on_cpu }
}
