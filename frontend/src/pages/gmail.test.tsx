import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import { GmailPage } from '@/pages/gmail'
import { useAuthStore } from '@/stores/auth'

beforeEach(() => {
  useAuthStore.setState({ accessToken: 'token' })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  useAuthStore.setState({ accessToken: null })
})

it('keeps the connection error on screen after clearing it from the URL', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) =>
      url.endsWith('/gmail/sync')
        ? new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } })
        : new Response('{"detail":"Not found"}', { status: 404, headers: { 'Content-Type': 'application/json' } })
    )
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/gmail?error=access_denied']}>
        <GmailPage />
      </MemoryRouter>
    </QueryClientProvider>
  )

  expect(await screen.findByText("Couldn't connect Gmail")).toBeInTheDocument()
  expect(await screen.findByRole('button', { name: /Connect Gmail/ })).toBeInTheDocument()
  expect(screen.getByText('access_denied')).toBeInTheDocument()
})

it('offers a reconnect button instead of Sync now once Gmail is disconnected', async () => {
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string) => {
      if (url.endsWith('/gmail/connection')) {
        return new Response(
          JSON.stringify({
            id: 'c1',
            google_email: 'owner@example.com',
            status: 'disconnected',
            last_synced_at: null,
            last_sync_error: null,
            created_at: '2026-09-16T07:00:00Z',
          }),
          { status: 200, headers: { 'Content-Type': 'application/json' } }
        )
      }
      if (url.endsWith('/gmail/sync')) {
        return new Response('[]', { status: 200, headers: { 'Content-Type': 'application/json' } })
      }
      return new Response('{"detail":"Not found"}', { status: 404, headers: { 'Content-Type': 'application/json' } })
    })
  )
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })

  render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={['/gmail']}>
        <GmailPage />
      </MemoryRouter>
    </QueryClientProvider>
  )

  expect(await screen.findByRole('heading', { name: 'Reconnect Gmail' })).toBeInTheDocument()
  expect(screen.getByRole('button', { name: 'Reconnect Gmail (read-only)' })).toBeInTheDocument()
  expect(screen.queryByRole('button', { name: /sync now/i })).not.toBeInTheDocument()
})
