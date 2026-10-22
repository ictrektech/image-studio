import { test } from 'node:test'
import assert from 'node:assert/strict'
import { repairLegacyL4TDefaults } from '../src/generationDefaults.ts'
import type { GeneratePayload } from '../src/api/client.ts'

test('L4T preset migration preserves user content and custom runtime choices', () => {
  const defaults = { weight_type: 'q4_0', max_vram: 1.5, vae_tile_size: '128x128', clip_on_cpu: true }
  const saved = { model_key: 'sd-turbo', model_variant: '', weight_type: 'f16', max_vram: 0,
    vae_tile_size: '128x128', clip_on_cpu: false, prompt: 'saved draft', width: 768, seed: 42 } as GeneratePayload
  for (const payload of [saved, { ...saved, weight_type: 'q4_0', max_vram: 2, vae_tile_size: '' }]) {
    const result = repairLegacyL4TDefaults(payload, defaults)
    assert.deepEqual(result, { ...payload, ...defaults })
    assert.equal(result.prompt, 'saved draft')
    assert.equal(result.width, 768)
    assert.equal(result.seed, 42)
  }
  for (const custom of [{ ...saved, max_vram: 3 }, { ...saved, weight_type: 'q8_0' }, { ...saved, model_variant: 'q4' }]) {
    assert.equal(repairLegacyL4TDefaults(custom, defaults), custom)
  }
  assert.equal(repairLegacyL4TDefaults(saved, { weight_type: 'f16', max_vram: 0 }), saved)
})
