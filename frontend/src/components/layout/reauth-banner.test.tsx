import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CalendarConnection, GithubConnection, GmailConnection } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'
import { ReauthBanner } from '@/components/layout/reauth-banner'

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

function stubApi(routes: Record<string, () => Response>) {
  const fetchMock = vi.fn(async (url: string) => {
    const pathOnly = url.split('?')[0]
    const path = Object.keys(routes).find((key) => pathOnly.endsWith(key))
    if (!path) throw new Error(`Unexpected request: ${url}`)
    return routes[path]()
  })
  vi.stubGlobal('fetch', fetchMock)
  return fetchMock
}

function renderBanner(ui: ReactElement = <ReauthBanner />) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

const GMAIL_CONNECTED: GmailConnection = {
  id: 'g1',
  google_email: 'aziz@gmail.com',
  status: 'connected',
  last_synced_at: null,
  last_sync_error: null,
  created_at: '2026-09-22T10:00:00Z',
}

const CALENDAR_CONNECTED: CalendarConnection = {
  id: 'c1',
  google_email: 'aziz@gmail.com',
  status: 'connected',
  last_error: null,
  created_at: '2026-09-22T10:00:00Z',
}

const GITHUB_CONNECTED: GithubConnection = {
  id: 'gh1',
  github_login: 'aziz',
  status: 'connected',
  installations: [],
  last_error: null,
  created_at: '2026-09-22T10:00:00Z',
}

beforeEach(() => {
  useAuthStore.setState({ accessToken: 'token' })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('ReauthBanner', () => {
  it('renders nothing when every connection is healthy', async () => {
    const fetchMock = stubApi({
      '/gmail/connection': () => json(GMAIL_CONNECTED),
      '/calendar/connection': () => json(CALENDAR_CONNECTED),
      '/github/connection': () => json(GITHUB_CONNECTED),
    })

    renderBanner()

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })

  it('surfaces a single connection that needs reconnecting', async () => {
    stubApi({
      '/gmail/connection': () => json({ ...GMAIL_CONNECTED, status: 'needs_reauth' }),
      '/calendar/connection': () => json(CALENDAR_CONNECTED),
      '/github/connection': () => json(GITHUB_CONNECTED),
    })

    renderBanner()

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Gmail')
    expect(alert).toHaveTextContent('needs to be reconnected')
  })

  it('surfaces every connection that needs reconnecting, not just the first', async () => {
    stubApi({
      '/gmail/connection': () => json({ ...GMAIL_CONNECTED, status: 'needs_reauth' }),
      '/calendar/connection': () => json({ ...CALENDAR_CONNECTED, status: 'needs_reauth' }),
      '/github/connection': () => json(GITHUB_CONNECTED),
    })

    renderBanner()

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent('Gmail')
    expect(alert).toHaveTextContent('Calendar')
    expect(alert).not.toHaveTextContent('GitHub')
  })

  it('says nothing about a connection that was simply never connected', async () => {
    const fetchMock = stubApi({
      '/gmail/connection': () => json({ detail: 'Not found' }, 404),
      '/calendar/connection': () => json(CALENDAR_CONNECTED),
      '/github/connection': () => json(GITHUB_CONNECTED),
    })

    renderBanner()

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(3))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
