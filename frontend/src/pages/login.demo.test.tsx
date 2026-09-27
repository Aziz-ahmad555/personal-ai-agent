import { MemoryRouter } from 'react-router-dom'
import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

// isDemoMode is read once at module load from import.meta.env, so the only way to exercise
// the demo branch is to mock the module itself, in a file of its own (vi.mock is hoisted and
// applies for the whole file).
vi.mock('@/lib/demo', () => ({ isDemoMode: true }))

import { LoginPage } from './login'

function renderLoginPage() {
  return render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>
  )
}

describe('LoginPage (demo build)', () => {
  it('offers a one-click demo sign-in instead of the real login form', () => {
    renderLoginPage()

    expect(screen.getByRole('heading', { name: /Demo/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /view the demo/i })).toBeInTheDocument()
    expect(screen.queryByLabelText('Email')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Password')).not.toBeInTheDocument()
  })
})
