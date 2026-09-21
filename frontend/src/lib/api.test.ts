import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { ApiError, authApi, configureAuthHooks } from '@/lib/api'
import type { TokenPair } from '@/lib/api'

const NEW_TOKENS: TokenPair = { access_token: 'new-access', refresh_token: 'new-refresh', token_type: 'bearer' }
const ME = { id: 'u1', email: 'a@b.c', full_name: null, is_active: true, created_at: '2026-01-01T00:00:00Z' }

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function bearer(init: RequestInit | undefined): string | null {
  return new Headers(init?.headers).get('Authorization')
}

describe('apiFetch token refresh', () => {
  const onRefreshed = vi.fn()
  const onExpired = vi.fn()
  let refreshToken: string | null

  beforeEach(() => {
    refreshToken = 'old-refresh'
    onRefreshed.mockReset()
    onExpired.mockReset()
    configureAuthHooks({ getRefreshToken: () => refreshToken, onRefreshed, onExpired })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
  })

  it('refreshes once on a 401 and retries the request with the new token', async () => {
    const seen: string[] = []
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.endsWith('/auth/refresh')) return json(NEW_TOKENS)
        seen.push(bearer(init) ?? '')
        return bearer(init) === 'Bearer new-access' ? json(ME) : json({ detail: 'expired' }, 401)
      })
    )

    const me = await authApi.me('old-access')

    expect(me.email).toBe('a@b.c')
    expect(seen).toEqual(['Bearer old-access', 'Bearer new-access'])
    expect(onRefreshed).toHaveBeenCalledWith(NEW_TOKENS)
    expect(onExpired).not.toHaveBeenCalled()
  })

  it('ends the session when the refresh itself is rejected', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) =>
        url.endsWith('/auth/refresh') ? json({ detail: 'Invalid refresh token' }, 401) : json({ detail: 'expired' }, 401)
      )
    )

    await expect(authApi.me('old-access')).rejects.toMatchObject({ status: 401 })

    expect(onExpired).toHaveBeenCalledOnce()
    expect(onRefreshed).not.toHaveBeenCalled()
  })

  it('ends the session if the request is still refused after a successful refresh', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string) =>
        url.endsWith('/auth/refresh') ? json(NEW_TOKENS) : json({ detail: 'nope' }, 401)
      )
    )

    await expect(authApi.me('old-access')).rejects.toBeInstanceOf(ApiError)

    expect(onExpired).toHaveBeenCalledOnce()
  })

  it('signs out straight away when there is no refresh token to try', async () => {
    refreshToken = null
    const fetchMock = vi.fn(async () => json({ detail: 'expired' }, 401))
    vi.stubGlobal('fetch', fetchMock)

    await expect(authApi.me('old-access')).rejects.toMatchObject({ status: 401 })

    expect(onExpired).toHaveBeenCalledOnce()
    expect(fetchMock).toHaveBeenCalledTimes(1) // never even called /auth/refresh
  })

  it('shares a single refresh between requests that all expire together', async () => {
    let refreshCalls = 0
    vi.stubGlobal(
      'fetch',
      vi.fn(async (url: string, init?: RequestInit) => {
        if (url.endsWith('/auth/refresh')) {
          refreshCalls += 1
          await new Promise((resolve) => setTimeout(resolve, 10))
          return json(NEW_TOKENS)
        }
        return bearer(init) === 'Bearer new-access' ? json(ME) : json({ detail: 'expired' }, 401)
      })
    )

    const results = await Promise.all([authApi.me('old-access'), authApi.me('old-access'), authApi.me('old-access')])

    expect(results).toHaveLength(3)
    expect(refreshCalls).toBe(1)
  })

  it('does not try to refresh a failed login — that 401 just means wrong credentials', async () => {
    const fetchMock = vi.fn(async () => json({ detail: 'Incorrect email or password' }, 401))
    vi.stubGlobal('fetch', fetchMock)

    await expect(authApi.login('a@b.c', 'wrong')).rejects.toMatchObject({
      status: 401,
      message: 'Incorrect email or password',
    })

    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(onExpired).not.toHaveBeenCalled()
  })
})
