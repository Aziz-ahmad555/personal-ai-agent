import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { CareerJob, JobMatch, MatchComponent } from '@/lib/api'
import { MatchBadge } from '@/features/career/badges'
import { MatchPanel } from '@/features/career/MatchPanel'

function component(overrides: Partial<MatchComponent>): MatchComponent {
  return {
    key: 'required_skills',
    label: 'Required skills',
    weight: 35,
    status: 'assessed',
    fraction: 1,
    points: 35,
    summary: '2 listed: 2 exact, 0 missing.',
    reason: null,
    details: [],
    ...overrides,
  }
}

const NOT_ASSESSED = (key: string, label: string, weight: number): MatchComponent =>
  component({
    key,
    label,
    weight,
    status: 'not_assessed',
    fraction: null,
    points: null,
    summary: '',
    reason: `the posting doesn't state ${label.toLowerCase()}.`,
  })

function match(overrides: Partial<JobMatch> = {}): JobMatch {
  return {
    id: 'm1',
    status: 'completed',
    error: null,
    score_percent: 88,
    assessed_weight: 80,
    low_confidence: false,
    components: [component({})],
    uncertainties: [],
    deal_breaker_check: 'none_set',
    deal_breaker_hits: [],
    is_stale: false,
    computed_at: '2026-09-21T10:00:00Z',
    ...overrides,
  }
}

function job(m: JobMatch | null, overrides: Partial<CareerJob> = {}): CareerJob {
  return {
    id: 'j1',
    source_channel: 'manual_paste',
    external_id: null,
    source_url: null,
    company_name: 'Acme Corp',
    company_domain: null,
    title: 'ML Engineer',
    location: null,
    remote_type: 'remote',
    salary_min: null,
    salary_max: null,
    salary_currency: null,
    description_text: null,
    posted_at: null,
    discovered_at: '2026-09-21T09:00:00Z',
    employer_verification: null,
    fraud_assessment: null,
    match: m,
    ...overrides,
  }
}

function renderPanel(m: JobMatch | null, overrides: Partial<CareerJob> = {}, onRematch = vi.fn()) {
  render(<MatchPanel job={job(m, overrides)} onRematch={onRematch} isStarting={false} />)
  return onRematch
}

describe('MatchPanel', () => {
  it('offers to match a job that has not been matched yet', () => {
    const onRematch = renderPanel(null)

    fireEvent.click(screen.getByRole('button', { name: 'Match to my profile' }))

    expect(onRematch).toHaveBeenCalledOnce()
  })

  it('shows progress while a match is running', () => {
    renderPanel(match({ status: 'running' }))

    expect(screen.getByText(/comparing them with your profile/i)).toBeInTheDocument()
  })

  it('shows the failure reason and lets the user retry', () => {
    const onRematch = renderPanel(match({ status: 'failed', error: 'Gemini call failed: 503' }))

    expect(screen.getByText('Gemini call failed: 503')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Try again' }))
    expect(onRematch).toHaveBeenCalledOnce()
  })

  it('shows a plain score with no warning when enough of it could be assessed', () => {
    renderPanel(match({ score_percent: 88, assessed_weight: 80, low_confidence: false }))

    expect(screen.getByText('88%')).toBeInTheDocument()
    expect(screen.getByText('match')).toBeInTheDocument()
    expect(screen.queryByText(/low confidence/i)).not.toBeInTheDocument()
  })

  it('warns prominently, ahead of the number, when most components are unknown', () => {
    renderPanel(
      match({
        score_percent: 100,
        assessed_weight: 35,
        low_confidence: true,
        components: [
          component({}),
          NOT_ASSESSED('experience', 'Years of experience', 20),
          NOT_ASSESSED('salary', 'Salary', 10),
        ],
      })
    )

    const warning = screen.getByText('Low confidence — most components unknown')
    expect(warning).toBeInTheDocument()
    expect(screen.getByText(/Only 35 of 100 points could be measured/)).toBeInTheDocument()
    expect(screen.getByText(/partial read, not a verdict/)).toBeInTheDocument()
    expect(screen.getByText(/years of experience, salary/i)).toBeInTheDocument()
    // The number is presented as a slice, not as "a 100% match".
    expect(screen.getByText('of what could be measured')).toBeInTheDocument()
    expect(screen.queryByText('match')).not.toBeInTheDocument()

    // The warning comes before the score in the document.
    const score = screen.getByText('100%')
    expect(warning.compareDocumentPosition(score) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy()
  })

  it('says it cannot score — rather than showing 0 — when nothing was assessable', () => {
    renderPanel(
      match({
        score_percent: null,
        assessed_weight: 0,
        low_confidence: true,
        components: [NOT_ASSESSED('required_skills', 'Required skills', 35)],
      })
    )

    expect(screen.getByText("Can't score this job")).toBeInTheDocument()
    expect(screen.queryByText('0%')).not.toBeInTheDocument()
  })

  it('lists components that were not assessed, with the reason', () => {
    renderPanel(
      match({ components: [component({}), NOT_ASSESSED('salary', 'Salary', 10)] })
    )

    expect(screen.getByText(/10 pts unmeasured/)).toBeInTheDocument()
    expect(screen.getByText(/Couldn't judge: the posting doesn't state salary/)).toBeInTheDocument()
  })

  it('reports deal-breaker hits with the posting quote', () => {
    renderPanel(
      match({
        deal_breaker_check: 'checked',
        deal_breaker_hits: [{ deal_breaker: 'weekend on-call', quote: 'On-call weekends are required' }],
      })
    )

    expect(screen.getByText('Triggers your deal-breakers')).toBeInTheDocument()
    expect(screen.getByText('weekend on-call')).toBeInTheDocument()
    expect(screen.getByText(/On-call weekends are required/)).toBeInTheDocument()
  })

  it('does not let a failed deal-breaker check read as "clear"', () => {
    renderPanel(match({ deal_breaker_check: 'unavailable' }))

    expect(screen.getByText("Deal-breakers weren't checked")).toBeInTheDocument()
    expect(screen.getByText(/does not mean this posting is clear/)).toBeInTheDocument()
  })

  it('flags a stale match and offers to re-match', () => {
    renderPanel(match({ is_stale: true }))

    expect(screen.getByText('Your profile changed since this was computed')).toBeInTheDocument()
  })

  it('warns that a good score does not make a high-fraud-risk posting safe', () => {
    renderPanel(match({}), {
      fraud_assessment: {
        id: 'f1',
        risk_level: 'high',
        risk_score: 80,
        signals: [],
        assessed_at: '2026-09-21T10:00:00Z',
      },
    })

    expect(screen.getByText("Don't let this score reassure you")).toBeInTheDocument()
    expect(screen.getByText(/high fraud risk/)).toBeInTheDocument()
  })

  it('reveals the evidence behind a skill match, including the posting quote', () => {
    renderPanel(
      match({
        components: [
          component({
            details: [
              {
                requirement: 'Python',
                quote: 'strong Python skills',
                match_type: 'exact',
                profile_skill: 'Python',
                level: 'advanced',
                evidence: 'Built production ML services in Python.',
              },
              { requirement: 'Rust', quote: 'Rust a plus', match_type: 'missing' },
            ],
          }),
        ],
      })
    )

    expect(screen.getByText(/Posting: “strong Python skills”/)).toBeInTheDocument()
    expect(screen.getByText(/Your evidence \(advanced\): Built production ML services in Python\./)).toBeInTheDocument()
    expect(screen.getByText('Missing')).toBeInTheDocument()
  })
})

describe('MatchBadge', () => {
  it('flags low confidence right next to the number', () => {
    render(<MatchBadge match={match({ score_percent: 72, assessed_weight: 40, low_confidence: true })} />)

    expect(screen.getByText(/72% · low confidence/)).toBeInTheDocument()
  })

  it('shows a plain badge when confidence is fine', () => {
    render(<MatchBadge match={match({ score_percent: 72 })} />)

    expect(screen.getByText('72% match')).toBeInTheDocument()
  })

  it('distinguishes never-matched, unscorable, and failed', () => {
    const { rerender } = render(<MatchBadge match={null} />)
    expect(screen.getByText('Not matched')).toBeInTheDocument()

    rerender(<MatchBadge match={match({ score_percent: null })} />)
    expect(screen.getByText("Can't score")).toBeInTheDocument()

    rerender(<MatchBadge match={match({ status: 'failed' })} />)
    expect(screen.getByText('Match failed')).toBeInTheDocument()
  })
})
