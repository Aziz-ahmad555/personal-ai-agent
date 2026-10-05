import { cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { GmailConnection } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'
import { ConnectionCard } from './ConnectionCard'

function connection(status: GmailConnection['status']): GmailConnection {
  return { id: 'c1', google_email: 'owner@example.com', last_synced_at: null, last_sync_error: null, created_at: '2026-09-16T07:00:00Z', status } as GmailConnection
}

function renderCard(status: GmailConnection['status']) {
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

describe('Gmail ConnectionCard reconnect', () => {
  it.each(['disconnected', 'needs_reauth'] as const)('offers Reconnect when status is %s', (status) => {
    renderCard(status)

    expect(screen.getByRole('button', { name: 'Reconnect' })).toBeEnabled()
  })
})
