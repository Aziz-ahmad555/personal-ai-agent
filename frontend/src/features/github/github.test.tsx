import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { GithubConnection, Integration } from '@/lib/api'
import { accessSummary } from '@/features/github/access'
import { GithubPage } from '@/pages/github'
import { IntegrationsPage } from '@/pages/integrations'
import { useAuthStore } from '@/stores/auth'

const CONNECTION: GithubConnection = {
  id: 'c1',
  github_login: 'aziz-ahmad555',
  status: 'connected',
  installations: [],
  last_error: null,
  created_at: '2026-09-22T10:00:00Z',
}

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

/** Routes by path suffix; anything unlisted is a test bug, so it fails loudly. */
function stubApi(routes: Record<string, (init?: RequestInit) => Response>) {
  const calls: { path: string; method: string }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const path = Object.keys(routes).find((key) => url.endsWith(key))
      calls.push({ path: path ?? url, method: init?.method ?? 'GET' })
      if (!path) throw new Error(`Unexpected request: ${url}`)
      return routes[path](init)
    })
  )
  return calls
}

function renderAt(ui: React.ReactElement, url = '/github') {
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
  cleanup() // unmount first: components read the token, so clearing it underneath them throws
  vi.unstubAllGlobals()
  useAuthStore.setState({ accessToken: null })
})

describe('accessSummary', () => {
  it('says public only when the app is installed nowhere', () => {
    expect(accessSummary(CONNECTION)).toBe('Public information only')
  })

  it('names the accounts the app is installed on, still read-only', () => {
    const summary = accessSummary({
      ...CONNECTION,
      installations: [
        { id: 1, account: 'aziz-ahmad555', repository_selection: 'selected', permissions: { metadata: 'read' } },
      ],
    })

    expect(summary).toContain('aziz-ahmad555')
    expect(summary).toContain('read-only')
  })
})

describe('GithubPage', () => {
  it('offers a read-only connection with an explicit can and cannot list', async () => {
    stubApi({ '/github/connection': () => json({ detail: 'Not found' }, 404) })
    renderAt(<GithubPage />)

    expect(await screen.findByRole('button', { name: 'Connect GitHub (read-only)' })).toBeInTheDocument()
    expect(screen.getByText('It can')).toBeInTheDocument()
    expect(screen.getByText('It cannot')).toBeInTheDocument()
    expect(screen.getByText(/no commits, issues, comments, stars, forks or settings/)).toBeInTheDocument()
    expect(screen.getByText(/no permissions/)).toBeInTheDocument()
  })

  it('says plainly that the import and review are not built yet', async () => {
    stubApi({ '/github/connection': () => json({ detail: 'Not found' }, 404) })
    renderAt(<GithubPage />)

    expect(await screen.findByText('Not built yet:')).toBeInTheDocument()
  })

  it('shows the connected account, its status and what it can reach', async () => {
    stubApi({ '/github/connection': () => json(CONNECTION) })
    renderAt(<GithubPage />)

    const account = await screen.findByRole('link', { name: 'aziz-ahmad555' })
    expect(account).toHaveAttribute('href', 'https://github.com/aziz-ahmad555')
    expect(screen.getByText('Connected')).toBeInTheDocument()
    expect(screen.getByText('Public information only')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Disconnect' })).toBeInTheDocument()
  })

  it('explains why a reconnect is needed and offers it', async () => {
    stubApi({
      '/github/connection': () =>
        json({ ...CONNECTION, status: 'needs_reauth', last_error: 'GitHub access has expired or been revoked.' }),
    })
    renderAt(<GithubPage />)

    expect(await screen.findByText('Reconnect needed')).toBeInTheDocument()
    expect(screen.getByText(/has expired or been revoked\. Reconnect to keep using GitHub\./)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Reconnect' })).toBeInTheDocument()
  })

  it('goes back to the connect prompt after a disconnect', async () => {
    stubApi({ '/github/connection': () => json({ ...CONNECTION, status: 'disconnected' }) })
    renderAt(<GithubPage />)

    expect(await screen.findByRole('button', { name: 'Reconnect GitHub' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Disconnect' })).not.toBeInTheDocument()
  })

  it('shows the reason when the connection was refused', async () => {
    stubApi({ '/github/connection': () => json({ detail: 'Not found' }, 404) })
    renderAt(<GithubPage />, '/github?error=This%20GitHub%20App%20has%20write%20permissions')

    expect(await screen.findByText("Couldn't connect GitHub")).toBeInTheDocument()
    expect(screen.getByText('This GitHub App has write permissions')).toBeInTheDocument()
  })

  it('shows an error with a retry when the connection cannot be loaded', async () => {
    stubApi({ '/github/connection': () => json({ detail: 'boom' }, 500) })
    renderAt(<GithubPage />)

    expect(await screen.findByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })

  it('disconnects after confirmation and reports that GitHub confirmed the revocation', async () => {
    const calls = stubApi({
      '/github/connection': (init) =>
        init?.method === 'DELETE'
          ? json({ connection: { ...CONNECTION, status: 'disconnected' }, revoked_at_github: true })
          : json(CONNECTION),
    })
    renderAt(<GithubPage />)

    fireEvent.click(await screen.findByRole('button', { name: 'Disconnect' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/revokes the access token on GitHub/)).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: 'Disconnect' }))

    expect(await screen.findByText('GitHub confirmed the token was revoked.')).toBeInTheDocument()
    expect(calls.filter((call) => call.method === 'DELETE')).toHaveLength(1)
  })

  it('is honest when GitHub could not confirm the revocation', async () => {
    stubApi({
      '/github/connection': (init) =>
        init?.method === 'DELETE'
          ? json({ connection: { ...CONNECTION, status: 'disconnected' }, revoked_at_github: false })
          : json(CONNECTION),
    })
    renderAt(<GithubPage />)

    fireEvent.click(await screen.findByRole('button', { name: 'Disconnect' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Disconnect' }))

    expect(await screen.findByText(/couldn't be reached to revoke the token/)).toBeInTheDocument()
    expect(screen.getByText(/github\.com\/settings\/applications/)).toBeInTheDocument()
  })

  it('shows an error inside the dialog when disconnecting fails', async () => {
    stubApi({
      '/github/connection': (init) =>
        init?.method === 'DELETE' ? json({ detail: 'nope' }, 500) : json(CONNECTION),
    })
    renderAt(<GithubPage />)

    fireEvent.click(await screen.findByRole('button', { name: 'Disconnect' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Disconnect' }))

    await waitFor(() => expect(within(dialog).getByText('Something went wrong')).toBeInTheDocument())
  })
})

const INTEGRATIONS: Integration[] = [
  {
    key: 'github',
    label: 'GitHub',
    status: 'not_connected',
    summary: 'Read-only: your public repositories.',
    path: '/github',
    reason: null,
  },
  {
    key: 'gmail',
    label: 'Gmail',
    status: 'connected',
    summary: 'Read-only access to your mail.',
    path: '/gmail',
    reason: null,
  },
  ...['LinkedIn', 'Indeed', 'Fiverr'].map((label) => ({
    key: label.toLowerCase(),
    label,
    status: 'unavailable' as const,
    summary: 'Something.',
    path: null,
    reason: 'No authorized API access for a personal developer account.',
  })),
]

describe('IntegrationsPage', () => {
  it('links to the available integrations with the right call to action', async () => {
    stubApi({ '/integrations': () => json(INTEGRATIONS) })
    renderAt(<IntegrationsPage />, '/integrations')

    expect(await screen.findByRole('link', { name: 'Set up GitHub' })).toHaveAttribute('href', '/github')
    expect(screen.getByRole('link', { name: 'Open Gmail' })).toHaveAttribute('href', '/gmail')
  })

  it('shows LinkedIn, Indeed and Fiverr as unavailable with the reason and nothing to click', async () => {
    stubApi({ '/integrations': () => json(INTEGRATIONS) })
    renderAt(<IntegrationsPage />, '/integrations')

    await screen.findByText('LinkedIn')
    expect(screen.getAllByText('Unavailable')).toHaveLength(3)
    expect(screen.getAllByText(/No authorized API access for a personal developer account/)).toHaveLength(3)
    for (const label of ['LinkedIn', 'Indeed', 'Fiverr']) {
      expect(screen.queryByRole('link', { name: new RegExp(label) })).not.toBeInTheDocument()
      expect(screen.queryByRole('button', { name: new RegExp(label) })).not.toBeInTheDocument()
    }
  })

  it('shows an error with a retry when the list cannot be loaded', async () => {
    stubApi({ '/integrations': () => json({ detail: 'boom' }, 500) })
    renderAt(<IntegrationsPage />, '/integrations')

    expect(await screen.findByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})
