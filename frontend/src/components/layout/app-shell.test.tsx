import { MemoryRouter } from 'react-router-dom'
import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import { AppShell } from '@/components/layout/app-shell'

describe('AppShell', () => {
  it('points the Dashboard tab at /dashboard now that / is the public landing page', () => {
    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <AppShell />
      </MemoryRouter>
    )

    expect(screen.getByRole('link', { name: 'Dashboard' })).toHaveAttribute('href', '/dashboard')
  })

  it('links to the landing page from the footer without any auth gate', () => {
    render(
      <MemoryRouter initialEntries={['/dashboard']}>
        <AppShell />
      </MemoryRouter>
    )

    expect(screen.getByRole('link', { name: 'About Personal AI Agent' })).toHaveAttribute('href', '/')
  })
})
