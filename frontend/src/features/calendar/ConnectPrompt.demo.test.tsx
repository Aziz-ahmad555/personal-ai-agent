import { cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/auth'

// See login.demo.test.tsx: isDemoMode is read once from import.meta.env, so exercising the
// demo branch needs its own file with the module mocked before import.
vi.mock('@/lib/demo', () => ({ isDemoMode: true }))

import { ConnectPrompt } from './ConnectPrompt'

beforeEach(() => {
  useAuthStore.setState({ accessToken: 'token' })
})

afterEach(() => {
  cleanup()
  useAuthStore.setState({ accessToken: null })
})

function renderPrompt() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <ConnectPrompt />
    </QueryClientProvider>
  )
}

describe('Calendar ConnectPrompt (demo build)', () => {
  it('disables the connect button and explains why', () => {
    renderPrompt()

    expect(screen.getByRole('button', { name: /connect calendar/i })).toBeDisabled()
    expect(screen.getByText(/not available in this demo/i)).toBeInTheDocument()
  })
})
