import { cleanup, render, screen } from '@testing-library/react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { useAuthStore } from '@/stores/auth'

// See login.demo.test.tsx: isDemoMode is read once from import.meta.env, so exercising the
// demo branch needs its own file with the module mocked before import.
vi.mock('@/lib/demo', () => ({ isDemoMode: true }))

import { CaptureJobForm } from './CaptureJobForm'

beforeEach(() => {
  useAuthStore.setState({ accessToken: 'token' })
})

afterEach(() => {
  cleanup()
  useAuthStore.setState({ accessToken: null })
})

function renderForm() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <CaptureJobForm onCreated={() => {}} />
    </QueryClientProvider>
  )
}

describe('CaptureJobForm (demo build)', () => {
  it('disables capture-by-URL and explains why, leaving paste enabled', () => {
    renderForm()

    expect(screen.getByRole('tab', { name: 'From URL' })).toBeDisabled()
    expect(screen.getByRole('tab', { name: 'Paste text' })).not.toBeDisabled()
    expect(screen.getByText(/capturing a posting by url is disabled/i)).toBeInTheDocument()
  })
})
