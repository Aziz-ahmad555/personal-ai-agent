import { MemoryRouter } from 'react-router-dom'
import { render, screen, within } from '@testing-library/react'
import { afterEach, beforeAll, describe, expect, it, vi } from 'vitest'
import LandingPage from '@/features/landing/LandingPage'
import { EVIDENCE, HERO, LADDER } from '@/features/landing/copy'
import { useAuthStore } from '@/stores/auth'

// jsdom cannot create a WebGL context, so this exercises the real fallback path end to end.
beforeAll(() => {
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
  window.matchMedia ??= ((query: string) => ({
    matches: false,
    media: query,
    addEventListener: () => {},
    removeEventListener: () => {},
    addListener: () => {},
    removeListener: () => {},
    onchange: null,
    dispatchEvent: () => false,
  })) as typeof window.matchMedia
})

afterEach(() => {
  useAuthStore.setState({ accessToken: null })
})

function renderLanding() {
  return render(
    <MemoryRouter>
      <LandingPage />
    </MemoryRouter>
  )
}

describe('LandingPage without WebGL', () => {
  it('uses no canvas and shows a static visual for every scene', () => {
    const { container } = renderLanding()

    expect(container.querySelector('canvas')).toBeNull()
    expect(container.querySelectorAll('svg.lp-fallback, svg.lp-fallback-hero')).toHaveLength(4)
  })

  it('leads with the headline and says what the page is about', () => {
    renderLanding()

    expect(screen.getByRole('heading', { level: 1, name: HERO.headline })).toBeInTheDocument()
    expect(
      screen.getByText(
        "Personal AI Agent researches your job leads, verifies employers, and scores every match against real evidence — before any of it reaches you. When it can't confirm something, it says so."
      )
    ).toBeInTheDocument()
  })

  it('shows the evidence card as an example, with its score, reasons and uncertainty', () => {
    renderLanding()
    const card = screen.getByRole('article', { name: /Example: AI\/ML Engineer/ })

    expect(within(card).getByText(EVIDENCE.exampleLabel)).toBeInTheDocument()
    expect(within(card).getByText('87%')).toBeInTheDocument()
    expect(within(card).getByText(EVIDENCE.scoreLabel)).toBeInTheDocument()
    expect(within(card).getByText('Required skills present — Python, PyTorch, computer vision')).toBeInTheDocument()
    expect(within(card).getByText('Employer verified — official source, checked 2 hours ago')).toBeInTheDocument()
    expect(within(card).getByText('One uncertainty — salary range not published')).toBeInTheDocument()
    expect(
      within(card).getByText('source: careers.employer.com · fetched 2h ago · tier: official')
    ).toBeInTheDocument()
  })

  it('lists the five source tiers from official down to forums', () => {
    renderLanding()
    const names = LADDER.tiers.map((tier) => tier.name)

    expect(names).toEqual(['Official', 'Government', 'Documentation', 'Reputable secondary', 'Forums, as anecdote'])
    for (const name of names) expect(screen.getByText(name)).toBeInTheDocument()
    for (const note of [
      "The employer's own domain, primary documents, and direct postings.",
      'Regulatory filings, court records, and official registries.',
      'Authoritative vendor and technical references.',
      'Outlets with real editorial standards, used to corroborate — not originate — a claim.',
      'Anecdotal color only. Never the sole basis for a fact.',
    ])
      expect(screen.getByText(note)).toBeInTheDocument()
  })

  it('explains all three risk levels', () => {
    renderLanding()

    for (const name of ['Green', 'Yellow', 'Red'])
      expect(screen.getByRole('heading', { level: 3, name })).toBeInTheDocument()
    expect(screen.getByText('Reads and analyzes. Runs on its own — nothing leaves your data.')).toBeInTheDocument()
    expect(screen.getByText('Drafts something real, like a reply or a post. Waits for you to approve it.')).toBeInTheDocument()
    expect(
      screen.getByText('Sends, applies, or commits to something. Needs your approval and a second check.')
    ).toBeInTheDocument()
  })

  it('offers sign-in to a visitor who is not logged in', () => {
    renderLanding()

    const links = screen.getAllByRole('link', { name: HERO.signedOut.label })
    expect(links.length).toBeGreaterThan(0)
    for (const link of links) expect(link).toHaveAttribute('href', HERO.signedOut.to)
  })

  it('offers the app to a logged-in visitor', () => {
    useAuthStore.setState({ accessToken: 'token' })
    renderLanding()

    const links = screen.getAllByRole('link', { name: HERO.signedIn.label })
    expect(links.length).toBeGreaterThan(0)
    for (const link of links) expect(link).toHaveAttribute('href', HERO.signedIn.to)
  })
})
