import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CalendarConnection } from '@/lib/api'
import { CalendarPage } from '@/pages/calendar'
import { useAuthStore } from '@/stores/auth'

const CONNECTION: CalendarConnection = {
  id: 'c1',
  google_email: 'aziz@gmail.com',
  status: 'connected',
  last_error: null,
  created_at: '2026-09-22T10:00:00Z',
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

type Handler = (init?: RequestInit) => Response

function stubApi(routes: Record<string, Handler>) {
  const calls: { path: string; method: string; url: string }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const pathOnly = url.split('?')[0]
      const path = Object.keys(routes).find((key) => pathOnly.endsWith(key))
      calls.push({ path: path ?? url, method: init?.method ?? 'GET', url })
      if (!path) throw new Error(`Unexpected request: ${url}`)
      return routes[path](init)
    })
  )
  return calls
}

function renderAt(ui: ReactElement, url = '/calendar') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  useAuthStore.setState({ accessToken: 'token' })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  useAuthStore.setState({ accessToken: null })
})

describe('CalendarPage', () => {
  it('offers a read-only connection with an explicit can and cannot list', async () => {
    stubApi({ '/calendar/connection': () => json({ detail: 'Not found' }, 404) })
    renderAt(<CalendarPage />)

    expect(
      await screen.findByRole('button', { name: 'Connect Calendar (read-only)' })
    ).toBeInTheDocument()
    expect(screen.getByText('It can')).toBeInTheDocument()
    expect(screen.getByText('It cannot')).toBeInTheDocument()
    expect(screen.getByText(/Create, edit, or delete anything on your calendar/)).toBeInTheDocument()
    expect(screen.getAllByText(/primary calendar/).length).toBeGreaterThan(0)
  })

  it('says plainly that reading events and detection are not built yet', async () => {
    stubApi({ '/calendar/connection': () => json({ detail: 'Not found' }, 404) })
    renderAt(<CalendarPage />)

    expect(await screen.findByText('Not built yet:')).toBeInTheDocument()
    expect(screen.getByText(/spotting interviews or deadlines/)).toBeInTheDocument()
  })

  it('shows the connected account and its status', async () => {
    stubApi({ '/calendar/connection': () => json(CONNECTION) })
    renderAt(<CalendarPage />)

    expect(await screen.findByText('aziz@gmail.com')).toBeInTheDocument()
    expect(screen.getByText('Connected')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Disconnect' })).toBeInTheDocument()
  })

  it('explains why a reconnect is needed and offers it', async () => {
    stubApi({
      '/calendar/connection': () =>
        json({ ...CONNECTION, status: 'needs_reauth', last_error: 'Calendar access has expired or been revoked.' }),
    })
    renderAt(<CalendarPage />)

    expect(await screen.findByText('Reconnect needed')).toBeInTheDocument()
    expect(
      screen.getByText(/has expired or been revoked\. Reconnect to keep using Calendar\./)
    ).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reconnect' })).toBeInTheDocument()
  })

  it('goes back to the connect prompt after a disconnect', async () => {
    stubApi({ '/calendar/connection': () => json({ ...CONNECTION, status: 'disconnected' }) })
    renderAt(<CalendarPage />)

    expect(await screen.findByRole('button', { name: 'Reconnect Calendar' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Disconnect' })).not.toBeInTheDocument()
  })

  it('shows the reason when the connection was refused', async () => {
    stubApi({ '/calendar/connection': () => json({ detail: 'Not found' }, 404) })
    renderAt(<CalendarPage />, '/calendar?error=access_denied')

    expect(await screen.findByText("Couldn't connect Calendar")).toBeInTheDocument()
    expect(screen.getByText('access_denied')).toBeInTheDocument()
  })

  it('shows an error with a retry when the connection cannot be loaded', async () => {
    stubApi({ '/calendar/connection': () => json({ detail: 'boom' }, 500) })
    renderAt(<CalendarPage />)

    expect(await screen.findByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('disconnects after confirmation and reports that Google confirmed the revocation', async () => {
    const calls = stubApi({
      '/calendar/connection': (init) =>
        init?.method === 'DELETE'
          ? json({ connection: { ...CONNECTION, status: 'disconnected' }, revoked_at_google: true })
          : json(CONNECTION),
    })
    renderAt(<CalendarPage />)

    fireEvent.click(await screen.findByRole('button', { name: 'Disconnect' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/revokes the access token on Google/)).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Disconnect' }))

    expect(await screen.findByText('Google confirmed the token was revoked.')).toBeInTheDocument()
    expect(calls.filter((call) => call.method === 'DELETE')).toHaveLength(1)
  })

  it('is honest when Google could not confirm the revocation', async () => {
    stubApi({
      '/calendar/connection': (init) =>
        init?.method === 'DELETE'
          ? json({ connection: { ...CONNECTION, status: 'disconnected' }, revoked_at_google: false })
          : json(CONNECTION),
    })
    renderAt(<CalendarPage />)

    fireEvent.click(await screen.findByRole('button', { name: 'Disconnect' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Disconnect' }))

    expect(await screen.findByText(/couldn't be reached to revoke the token/)).toBeInTheDocument()
    expect(screen.getByText(/myaccount\.google\.com\/permissions/)).toBeInTheDocument()
  })

  it('shows an error inside the dialog when disconnecting fails', async () => {
    stubApi({
      '/calendar/connection': (init) =>
        init?.method === 'DELETE' ? json({ detail: 'nope' }, 500) : json(CONNECTION),
    })
    renderAt(<CalendarPage />)

    fireEvent.click(await screen.findByRole('button', { name: 'Disconnect' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Disconnect' }))

    await waitFor(() => expect(within(dialog).getByText('Something went wrong')).toBeInTheDocument())
  })
})
