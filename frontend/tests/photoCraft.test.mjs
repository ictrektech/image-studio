import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFile } from 'node:fs/promises'
import ts from 'typescript'

test('PhotoCraft handoff keeps the output path and uses its own VOS identity', async () => {
  const source = (await readFile(new URL('../src/api/photoCraft.ts', import.meta.url), 'utf8'))
    .replace("import { api } from './client'", "const api = { photoCraftHandoff: async () => ({url: '/api/com.ictrek.image-studio/api/v1/photocraft/handoffs/opaque/output.png'}) }")
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.ESNext } }).outputText
  const helper = await import(`data:text/javascript;base64,${Buffer.from(code).toString('base64')}`)
  const output = '/api/com.ictrek.image-studio/api/v1/photocraft/handoffs/opaque/output.png'
  const url = new URL(helper.photoCraftUrl(output, '图片.png'), 'http://vos.test')
  assert.equal(url.pathname, '/app/com.ictrek.photocraft/')
  assert.equal(url.searchParams.get('open'), output)
  assert.equal(url.searchParams.get('name'), '图片.png')
  assert.equal(url.searchParams.get('source'), 'com.ictrek.image-studio')
  assert.ok(!url.href.includes('access_token'))
  const saved = globalThis.window
  try {
    let fallback
    globalThis.window = { open: value => { fallback = value } }
    await helper.openInPhotoCraft('job', '图片.png')
    assert.equal(fallback, helper.photoCraftUrl(output, '图片.png'))
    let opened
    globalThis.window = { vos_platform: { platform: { openTab: async value => { opened = value } } } }
    await helper.openInPhotoCraft('job', '图片.png', 'PhotoCraft')
    assert.deepEqual(opened, { url: helper.photoCraftUrl(output, '图片.png'), title: 'PhotoCraft' })
  } finally {
    if (saved === undefined) delete globalThis.window
    else globalThis.window = saved
  }
})
