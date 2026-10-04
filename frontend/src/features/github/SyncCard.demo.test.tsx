import { cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { GithubConnection } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

// See login.demo.test.tsx: isDemoMode is read once from import.meta.env, so exercising the
// demo branch needs its own file with the module mocked before import.
vi.mock('@/lib/demo', () => ({ isDemoMode: true }))

import { SyncCard } from './SyncCard'

const CONNECTION: GithubConnection = {
  id: 'c1',
  github_login: 'alex-rivera-demo',
  status: 'connected',
  installations: [],
  last_error: null,
  created_at: '2026-09-16T07:00:00Z',
}

function renderCard() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify([]), { status: 200 }))
  )
  return render(
    <QueryClientProvider client={client}>
      <SyncCard connection={CONNECTION} />
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

describe('GitHub SyncCard (demo build)', () => {
  it('disables Sync now and explains why, for an already-connected seeded account', async () => {
    renderCard()

    expect(await screen.findByRole('button', { name: /sync now/i })).toBeDisabled()
    expect(screen.getByText(/not available in this demo/i)).toBeInTheDocument()
  })
})
