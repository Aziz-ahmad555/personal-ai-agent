import { cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it } from 'vitest'
import type { CalendarConnection } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'
import { ConnectionCard } from './ConnectionCard'

function connection(status: CalendarConnection['status']): CalendarConnection {
  return { id: 'c1', google_email: 'owner@example.com', last_error: null, created_at: '2026-09-16T07:00:00Z', status } as CalendarConnection
}

function renderCard(status: CalendarConnection['status']) {
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

describe('Calendar ConnectionCard reconnect', () => {
  it.each(['disconnected', 'needs_reauth'] as const)('offers Reconnect when status is %s', (status) => {
    renderCard(status)

    expect(screen.getByRole('button', { name: 'Reconnect' })).toBeEnabled()
  })
})
