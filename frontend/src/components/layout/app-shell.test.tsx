import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, render, screen } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/auth'
import { AppShell } from '@/components/layout/app-shell'

// AppShell renders ReauthBanner, which reads the auth token and queries each
// integration's connection status — needs a logged-in token, a QueryClientProvider,
// and a stubbed fetch, the same setup reauth-banner.test.tsx uses for that component
// directly. None of these tests care about the banner's own content, so every
// connection is stubbed "not connected" (404), which renders nothing.
function renderShell(path: string) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[path]}>
        <AppShell />
      </MemoryRouter>
    </QueryClientProvider>
  )
}

beforeEach(() => {
  useAuthStore.setState({ accessToken: 'token' })
  vi.stubGlobal(
    'fetch',
    vi.fn(async () => new Response(JSON.stringify({ detail: 'Not found' }), { status: 404 }))
  )
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

describe('AppShell', () => {
  it('points the Dashboard tab at /dashboard now that / is the public landing page', () => {
    renderShell('/dashboard')

    expect(screen.getByRole('link', { name: 'Dashboard' })).toHaveAttribute('href', '/dashboard')
  })

  it('links to the landing page from the footer without any auth gate', () => {
    renderShell('/dashboard')

    expect(screen.getByRole('link', { name: 'About Personal AI Agent' })).toHaveAttribute('href', '/')
  })
})
