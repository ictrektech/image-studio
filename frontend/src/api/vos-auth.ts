export interface VOSTokenSet {
  access_token: string
  token_type?: string
  expires_in?: number
  refresh_token?: string
  id_token?: string
  scope?: string
}

interface VOSOAuth2 {
  authorize(params: {
    client_id: string
    response_type: 'code'
    scope: string
    state: string
    code_challenge: string
    code_challenge_method: 'S256'
    nonce?: string
  }): Promise<{ code: string; state: string }>
  token(params: {
    grant_type: 'authorization_code'
    code: string
    code_verifier: string
    client_id: string
  }): Promise<VOSTokenSet>
}

declare global {
  interface Window {
    vos_platform?: {
      api?: {
        v1000?: {
          oauth2?: VOSOAuth2
        }
      }
    }
    __VOS_APP_CONTEXT__?: {
      accessToken?: string
      token?: string
    }
    __VOS_ACCESS_TOKEN__?: string
  }
}

const CLIENT_ID = 'com.ictrek.image-studio'
const SCOPE = 'openid profile email'
const TOKEN_CACHE_KEY = 'image_studio_vos_token'

let tokenPromise: Promise<string | null> | null = null

export async function getVOSBearerToken(): Promise<string | null> {
  if (tokenPromise) return tokenPromise
  tokenPromise = resolveVOSBearerToken().finally(() => {
    tokenPromise = null
  })
  return tokenPromise
}

async function resolveVOSBearerToken(): Promise<string | null> {
  const cached = readCachedToken()
  if (cached) return cached

  const fastpath = await requestFastpathToken()
  if (fastpath) {
    cacheToken(fastpath)
    return fastpath.access_token
  }

  return tokenFromInjectedContext() || tokenFromLocalStorage()
}

function readCachedToken(): string | null {
  try {
    const raw = sessionStorage.getItem(TOKEN_CACHE_KEY)
    if (!raw) return null
    const data = JSON.parse(raw)
    if (!data?.access_token || Date.now() > Number(data.expires_at || 0)) return null
    return data.access_token
  } catch {
    return null
  }
}

function cacheToken(token: VOSTokenSet) {
  try {
    const ttl = Math.max(60, Number(token.expires_in || 3600) - 60)
    sessionStorage.setItem(TOKEN_CACHE_KEY, JSON.stringify({
      access_token: token.access_token,
      expires_at: Date.now() + ttl * 1000,
    }))
  } catch {
    // Best-effort cache only. Requests still carry the in-memory token.
  }
}

async function requestFastpathToken(): Promise<VOSTokenSet | null> {
  const oauth2 = await waitForOAuth2()
  if (!oauth2) return null

  const verifier = randomBase64url()
  const state = randomBase64url()
  const nonce = randomBase64url()
  const codeChallenge = await sha256Base64url(verifier)
  const auth = await oauth2.authorize({
    client_id: CLIENT_ID,
    response_type: 'code',
    scope: SCOPE,
    state,
    code_challenge: codeChallenge,
    code_challenge_method: 'S256',
    nonce,
  })
  if (auth.state !== state) throw new Error('VOS OIDC state mismatch')
  const token = await oauth2.token({
    grant_type: 'authorization_code',
    code: auth.code,
    code_verifier: verifier,
    client_id: CLIENT_ID,
  })
  return token?.access_token ? token : null
}

async function waitForOAuth2(timeoutMs = 3000): Promise<VOSOAuth2 | null> {
  const existing = window.vos_platform?.api?.v1000?.oauth2
  if (isOAuth2(existing)) return existing

  const start = Date.now()
  return new Promise(resolve => {
    const timer = window.setInterval(() => {
      const oauth2 = window.vos_platform?.api?.v1000?.oauth2
      if (isOAuth2(oauth2)) {
        window.clearInterval(timer)
        resolve(oauth2)
      } else if (Date.now() - start >= timeoutMs) {
        window.clearInterval(timer)
        resolve(null)
      }
    }, 50)
  })
}

function isOAuth2(value: VOSOAuth2 | undefined): value is VOSOAuth2 {
  return typeof value?.authorize === 'function' && typeof value?.token === 'function'
}

function tokenFromInjectedContext(): string | null {
  const token = window.__VOS_APP_CONTEXT__?.accessToken ||
    window.__VOS_APP_CONTEXT__?.token ||
    window.__VOS_ACCESS_TOKEN__
  return typeof token === 'string' && token.trim() ? token.trim() : null
}

function tokenFromLocalStorage(): string | null {
  try {
    const directKeys = ['core-access', 'VIVIBIT-core-access']
    for (const key of directKeys) {
      const token = tokenFromAccessStore(localStorage.getItem(key))
      if (token) return token
    }
    for (let i = 0; i < localStorage.length; i += 1) {
      const key = localStorage.key(i)
      if (!key || !key.endsWith('-core-access')) continue
      const token = tokenFromAccessStore(localStorage.getItem(key))
      if (token) return token
    }
  } catch {
    return null
  }
  return null
}

function tokenFromAccessStore(raw: string | null): string | null {
  if (!raw) return null
  try {
    const data = JSON.parse(raw)
    const token = data?.accessToken || data?.access_token || data?.token
    return typeof token === 'string' && token.trim() ? token.trim() : null
  } catch {
    return null
  }
}

function randomBase64url(byteLength = 32): string {
  const bytes = new Uint8Array(byteLength)
  crypto.getRandomValues(bytes)
  return base64url(bytes)
}

async function sha256Base64url(input: string): Promise<string> {
  const bytes = new TextEncoder().encode(input)
  const digest = await crypto.subtle.digest('SHA-256', bytes)
  return base64url(new Uint8Array(digest))
}

function base64url(bytes: Uint8Array): string {
  let raw = ''
  for (let i = 0; i < bytes.length; i += 1) {
    raw += String.fromCharCode(bytes[i])
  }
  return btoa(raw).replace(/\+/g, '-').replace(/\//g, '_').replace(/=+$/, '')
}
