import { MemoryRouter } from 'react-router-dom'
import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { LoginPage } from './login'

function renderLoginPage() {
  return render(
    <MemoryRouter>
      <LoginPage />
    </MemoryRouter>
  )
}

describe('LoginPage', () => {
  it('renders the sign-in form', () => {
    renderLoginPage()

    expect(screen.getByRole('heading', { name: 'Sign in' })).toBeInTheDocument()
    expect(screen.getByLabelText('Email')).toBeInTheDocument()
    expect(screen.getByLabelText('Password')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /sign in/i })).toBeInTheDocument()
  })

  it('updates input values as the user types', () => {
    renderLoginPage()

    const emailInput = screen.getByLabelText('Email') as HTMLInputElement
    fireEvent.change(emailInput, { target: { value: 'aziz@example.com' } })

    expect(emailInput.value).toBe('aziz@example.com')
  })
})
