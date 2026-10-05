import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CalendarConnection, CalendarEvent, CalendarSyncRun } from '@/lib/api'
import { CalendarPage } from '@/pages/calendar'
import { useAuthStore } from '@/stores/auth'

const CONNECTION: CalendarConnection = {
  id: 'c1',
  google_email: 'person-01@example.com',
  status: 'connected',
  last_error: null,
  created_at: '2026-09-22T10:00:00Z',
}

function syncRun(overrides: Partial<CalendarSyncRun> = {}): CalendarSyncRun {
  return {
    id: 'run-1',
    status: 'completed',
    started_at: '2026-09-22T10:00:00Z',
    completed_at: '2026-09-22T10:00:05Z',
    events_seen: 2,
    events_stored: 2,
    warnings: [],
    error: null,
    ...overrides,
  }
}

function event(overrides: Partial<CalendarEvent> = {}): CalendarEvent {
  return {
    id: 'e1',
    html_link: 'https://calendar.google.com/event?eid=e1',
    summary: 'Technical interview with Acme',
    description: null,
    location: null,
    start_at: '2026-09-25T15:00:00Z',
    end_at: '2026-09-25T16:00:00Z',
    is_all_day: false,
    organizer_email: null,
    attendees: [],
    kind: 'interview',
    match_reason: 'technical interview',
    user_confirmed: false,
    application: null,
    application_match_reason: null,
    ...overrides,
  }
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

  it('points to interview practice in Career rather than calling it unbuilt', async () => {
    stubApi({ '/calendar/connection': () => json({ detail: 'Not found' }, 404) })
    renderAt(<CalendarPage />)

    expect(await screen.findByText('Interview practice')).toBeInTheDocument()
    expect(screen.getByText(/lives in Career/)).toBeInTheDocument()
    expect(screen.queryByText('Not built yet:')).not.toBeInTheDocument()
    expect(screen.getByText(/look like interviews or application deadlines/)).toBeInTheDocument()
  })

  it('shows the connected account and its status', async () => {
    stubApi({ '/calendar/connection': () => json(CONNECTION) })
    renderAt(<CalendarPage />)

    expect(await screen.findByText('person-01@example.com')).toBeInTheDocument()
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

describe('Sync', () => {
  it('prompts to sync before anything has run', async () => {
    stubApi({
      '/calendar/connection': () => json(CONNECTION),
      '/calendar/sync': () => json([]),
      '/calendar/events': () => json([]),
    })
    renderAt(<CalendarPage />)

    expect(await screen.findByText(/Nothing synced yet/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sync now' })).toBeEnabled()
  })

  it('starts a sync and shows the result once it completes', async () => {
    const calls = stubApi({
      '/calendar/connection': () => json(CONNECTION),
      '/calendar/sync': (init) =>
        init?.method === 'POST' ? json(syncRun({ status: 'pending' })) : json([syncRun()]),
      '/calendar/events': () => json([]),
    })
    renderAt(<CalendarPage />)

    fireEvent.click(await screen.findByRole('button', { name: 'Sync now' }))

    expect(await screen.findByText(/2 events \(2 new\)/)).toBeInTheDocument()
    expect(calls.filter((call) => call.method === 'POST' && call.path === '/calendar/sync')).toHaveLength(1)
  })

  it('shows the last sync error and any warnings', async () => {
    stubApi({
      '/calendar/connection': () => json(CONNECTION),
      '/calendar/sync': () =>
        json([syncRun({ status: 'failed', error: 'Google returned a 500' })]),
      '/calendar/events': () => json([]),
    })
    renderAt(<CalendarPage />)

    expect(await screen.findByText('The last sync failed')).toBeInTheDocument()
    expect(screen.getByText('Google returned a 500')).toBeInTheDocument()
  })

  it('shows sync warnings when the last completed run had any', async () => {
    stubApi({
      '/calendar/connection': () => json(CONNECTION),
      '/calendar/sync': () => json([syncRun({ warnings: ['3 events had no start time and were skipped.'] })]),
      '/calendar/events': () => json([]),
    })
    renderAt(<CalendarPage />)

    expect(await screen.findByText('Worth knowing')).toBeInTheDocument()
    expect(screen.getByText('3 events had no start time and were skipped.')).toBeInTheDocument()
  })
})

describe('Events', () => {
  it('shows an empty state before any sync has completed', async () => {
    stubApi({
      '/calendar/connection': () => json(CONNECTION),
      '/calendar/sync': () => json([]),
      '/calendar/events': () => json([]),
    })
    renderAt(<CalendarPage />)

    expect(await screen.findByText('Nothing yet. Sync your calendar to see events here.')).toBeInTheDocument()
  })

  it('shows an empty state distinctly once a sync has completed but found nothing', async () => {
    stubApi({
      '/calendar/connection': () => json(CONNECTION),
      '/calendar/sync': () => json([syncRun({ events_seen: 0, events_stored: 0 })]),
      '/calendar/events': () => json([]),
    })
    renderAt(<CalendarPage />)

    expect(
      await screen.findByText('No events in the synced window (about a month back, six months ahead).')
    ).toBeInTheDocument()
  })

  it('lists events with their kind, evidence, and a link to Google Calendar', async () => {
    stubApi({
      '/calendar/connection': () => json(CONNECTION),
      '/calendar/sync': () => json([syncRun()]),
      '/calendar/events': () => json([event(), event({ id: 'e2', summary: 'Team lunch', kind: 'other', match_reason: null })]),
      '/career/applications': () => json([]),
    })
    renderAt(<CalendarPage />)

    const link = await screen.findByRole('link', { name: 'Technical interview with Acme' })
    expect(link).toHaveAttribute('href', 'https://calendar.google.com/event?eid=e1')
    expect(screen.getByText('Interview')).toBeInTheDocument()
    expect(screen.getByText(/Matched on the phrase.*technical interview/)).toBeInTheDocument()
    expect(screen.getByText('Team lunch')).toBeInTheDocument()
  })

  it('shows the linked application and marks a user override so it is not re-guessed', async () => {
    stubApi({
      '/calendar/connection': () => json(CONNECTION),
      '/calendar/sync': () => json([syncRun()]),
      '/calendar/events': () =>
        json([
          event({
            user_confirmed: true,
            application: {
              id: 'app-1',
              title: 'ML Engineer',
              company_name: 'Acme Corp',
              job_posting_id: 'job-1',
            },
            application_match_reason: 'attendee domain acme.com',
          }),
        ]),
      '/career/applications': () => json([]),
    })
    renderAt(<CalendarPage />)

    expect(await screen.findByText('Set by you')).toBeInTheDocument()
    expect(screen.getByText(/Linked to/)).toBeInTheDocument()
    expect(screen.getByText(/ML Engineer/)).toBeInTheDocument()
    expect(screen.getByText(/attendee domain acme.com/)).toBeInTheDocument()
    // A confirmed event no longer shows the automated match reason as evidence.
    expect(screen.queryByText(/Matched on the phrase/)).not.toBeInTheDocument()
  })

  it('lets the user correct the kind and the linked application, and persists it', async () => {
    const calls = stubApi({
      '/calendar/connection': () => json(CONNECTION),
      '/calendar/sync': () => json([syncRun()]),
      '/calendar/events': () => json([event()]),
      '/career/applications': () =>
        json([
          {
            id: 'app-1',
            job_posting_id: 'job-1',
            status: 'applied',
            notes: null,
            applied_on: null,
            next_action_text: null,
            next_action_on: null,
            follow_up_state: null,
            job: { id: 'job-1', title: 'ML Engineer', company_name: 'Acme Corp', location: null, remote_type: 'remote', source_url: null },
            match: null,
            allowed_transitions: [],
            reopen_targets: [],
            created_at: '2026-09-01T00:00:00Z',
            updated_at: '2026-09-01T00:00:00Z',
          },
        ]),
      '/calendar/events/e1/classify': () =>
        json(
          event({
            kind: 'other',
            user_confirmed: true,
            application: {
              id: 'app-1',
              title: 'ML Engineer',
              company_name: 'Acme Corp',
              job_posting_id: 'job-1',
            },
          })
        ),
    })
    renderAt(<CalendarPage />)

    fireEvent.click(await screen.findByRole('button', { name: 'Not right? Change it' }))
    fireEvent.change(screen.getByLabelText('Type'), { target: { value: 'other' } })
    fireEvent.change(screen.getByLabelText('Linked application'), { target: { value: 'app-1' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    await waitFor(() =>
      expect(calls.some((call) => call.method === 'POST' && call.path === '/calendar/events/e1/classify')).toBe(true)
    )
  })

  it('shows an error inline when saving a correction fails', async () => {
    stubApi({
      '/calendar/connection': () => json(CONNECTION),
      '/calendar/sync': () => json([syncRun()]),
      '/calendar/events': () => json([event()]),
      '/career/applications': () => json([]),
      '/calendar/events/e1/classify': () => json({ detail: 'boom' }, 500),
    })
    renderAt(<CalendarPage />)

    fireEvent.click(await screen.findByRole('button', { name: 'Not right? Change it' }))
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(await screen.findByText('Something went wrong')).toBeInTheDocument()
  })

  it('shows an error with a retry when events cannot be loaded', async () => {
    stubApi({
      '/calendar/connection': () => json(CONNECTION),
      '/calendar/sync': () => json([]),
      '/calendar/events': () => json({ detail: 'boom' }, 500),
    })
    renderAt(<CalendarPage />)

    expect(await screen.findByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})
