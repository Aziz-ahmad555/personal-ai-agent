import { cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { GithubConnection } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'
import { ConnectionCard } from './ConnectionCard'

function connection(status: GithubConnection['status']): GithubConnection {
  return { id: 'c1', github_login: 'owner-login', installations: [], last_error: null, created_at: '2026-09-16T07:00:00Z', status } as GithubConnection
}

function renderCard(status: GithubConnection['status']) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ConnectionCard connection={connection(status)} />
    </QueryClientProvider>
  )
}

beforeEach(() => {
  useAuthStore.setState({ accessToken: 'token' })
})

afterEach(() => {
  cleanup()
  useAuthStore.setState({ accessToken: null })
})

describe('GitHub ConnectionCard reconnect', () => {
  it.each(['disconnected', 'needs_reauth'] as const)('offers Reconnect when status is %s', (status) => {
    renderCard(status)

    expect(screen.getByRole('button', { name: 'Reconnect' })).toBeEnabled()
  })
})
