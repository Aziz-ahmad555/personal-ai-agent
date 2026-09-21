import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { Application, ApplicationEvent, ApplicationStatus } from '@/lib/api'
import { FollowUpChip, MatchChip } from '@/features/applications/badges'
import { ApplicationCard } from '@/features/applications/ApplicationCard'
import { Board } from '@/features/applications/Board'
import { dueFollowUps } from '@/features/applications/followUps'
import { StatusChangeForm } from '@/features/applications/StatusChangeForm'
import { Timeline } from '@/features/applications/Timeline'

function application(overrides: Partial<Application> = {}): Application {
  return {
    id: 'a1',
    job_posting_id: 'j1',
    status: 'applied',
    notes: null,
    applied_on: '2026-09-10',
    next_action_text: null,
    next_action_on: null,
    follow_up_state: null,
    job: {
      id: 'j1',
      title: 'ML Engineer',
      company_name: 'Acme Corp',
      location: null,
      remote_type: 'remote',
      source_url: null,
    },
    match: null,
    allowed_transitions: [],
    reopen_targets: [],
    created_at: '2026-09-01T00:00:00Z',
    updated_at: '2026-09-01T00:00:00Z',
    ...overrides,
  }
}

function event(overrides: Partial<ApplicationEvent> = {}): ApplicationEvent {
  return {
    id: 'e1',
    event_type: 'status_change',
    from_status: null,
    to_status: 'saved',
    occurred_on: '2026-09-10',
    body: null,
    snapshot: null,
    created_at: '2026-09-10T00:00:00Z',
    ...overrides,
  }
}

describe('FollowUpChip', () => {
  it('shows nothing when there is no follow-up', () => {
    const { container } = render(<FollowUpChip state={null} text={null} on={null} />)
    expect(container).toBeEmptyDOMElement()
  })

  it('distinguishes overdue, due today, and upcoming', () => {
    const { rerender } = render(
      <FollowUpChip state="overdue" text="Email recruiter" on="2026-09-01" />
    )
    expect(screen.getByText(/Overdue · Email recruiter/)).toBeInTheDocument()

    rerender(<FollowUpChip state="due_today" text="Email recruiter" on="2026-09-21" />)
    expect(screen.getByText(/Due today · Email recruiter/)).toBeInTheDocument()

    rerender(<FollowUpChip state="upcoming" text="Email recruiter" on="2026-09-30" />)
    // The date follows the user's locale, so match its parts, not one format.
    expect(screen.getByText(/Email recruiter · .*30.*2026/)).toBeInTheDocument()
  })

  it('falls back to a generic label when no text was written', () => {
    render(<FollowUpChip state="overdue" text={null} on="2026-09-01" />)
    expect(screen.getByText(/Overdue · Follow up/)).toBeInTheDocument()
  })
})

describe('MatchChip', () => {
  it('flags a low-confidence score right beside the number', () => {
    render(<MatchChip match={{ score_percent: 72, low_confidence: true }} />)
    expect(screen.getByText(/72% · low confidence/)).toBeInTheDocument()
  })

  it('shows a plain score otherwise, and nothing when there is none', () => {
    const { rerender, container } = render(
      <MatchChip match={{ score_percent: 80, low_confidence: false }} />
    )
    expect(screen.getByText('80% match')).toBeInTheDocument()

    rerender(<MatchChip match={{ score_percent: null, low_confidence: true }} />)
    expect(container).toBeEmptyDOMElement()
    rerender(<MatchChip match={null} />)
    expect(container).toBeEmptyDOMElement()
  })
})

describe('ApplicationCard', () => {
  it('shows the job, its match, and an overdue follow-up, and selects on click', () => {
    const onSelect = vi.fn()
    render(
      <ApplicationCard
        application={application({
          match: { score_percent: 64, low_confidence: false },
          follow_up_state: 'overdue',
          next_action_text: 'Nudge them',
          next_action_on: '2026-09-01',
        })}
        selected={false}
        onSelect={onSelect}
      />
    )

    expect(screen.getByText('ML Engineer')).toBeInTheDocument()
    expect(screen.getByText('Acme Corp')).toBeInTheDocument()
    expect(screen.getByText('64% match')).toBeInTheDocument()
    expect(screen.getByText(/Overdue · Nudge them/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button'))
    expect(onSelect).toHaveBeenCalledWith('a1')
  })

  it('labels closed applications with their outcome', () => {
    render(<ApplicationCard application={application({ status: 'rejected' })} selected onSelect={vi.fn()} />)

    expect(screen.getByText('Rejected')).toBeInTheDocument()
    expect(screen.getByRole('button')).toHaveAttribute('aria-pressed', 'true')
  })
})

describe('Board', () => {
  it('groups applications into pipeline columns, with every closed outcome in Closed', () => {
    const statuses: ApplicationStatus[] = ['saved', 'applied', 'interviewing', 'accepted', 'no_response']
    const apps = statuses.map((status, index) =>
      application({
        id: `a${index}`,
        status,
        job: { ...application().job!, title: `Role ${status}` },
      })
    )
    render(<Board applications={apps} selectedId={null} onSelect={vi.fn()} />)

    const column = (name: string) => screen.getByRole('region', { name })
    expect(within(column('Saved')).getByText('Role saved')).toBeInTheDocument()
    expect(within(column('Applied')).getByText('Role applied')).toBeInTheDocument()
    expect(within(column('Interviewing')).getByText('Role interviewing')).toBeInTheDocument()
    const closed = column('Closed')
    expect(within(closed).getByText('Role accepted')).toBeInTheDocument()
    expect(within(closed).getByText('Role no_response')).toBeInTheDocument()
    expect(within(column('Offer')).getByText('Nothing here.')).toBeInTheDocument()
  })
})

describe('Timeline', () => {
  it('titles each kind of event', () => {
    render(
      <Timeline
        events={[
          event({ id: '1', from_status: null, to_status: 'saved' }),
          event({ id: '2', from_status: 'saved', to_status: 'applied' }),
          event({ id: '3', event_type: 'interview', from_status: null, to_status: null, body: 'Phone screen' }),
          event({ id: '4', event_type: 'note', from_status: null, to_status: null, body: 'Referred by Sam' }),
          event({ id: '5', from_status: 'applied', to_status: 'no_response' }),
          event({ id: '6', from_status: 'no_response', to_status: 'interviewing', body: 'They replied!' }),
        ]}
      />
    )

    expect(screen.getByText('Started tracking (saved)')).toBeInTheDocument()
    expect(screen.getByText('Saved → Applied')).toBeInTheDocument()
    expect(screen.getByText('Interview')).toBeInTheDocument()
    expect(screen.getByText('Phone screen')).toBeInTheDocument()
    expect(screen.getByText('Note')).toBeInTheDocument()
    expect(screen.getByText('Applied → No response')).toBeInTheDocument()
    expect(screen.getByText('Reopened as interviewing')).toBeInTheDocument()
    expect(screen.getByText('They replied!')).toBeInTheDocument()
  })

  it('shows what was known when the user applied, low confidence included', () => {
    render(
      <Timeline
        events={[
          event({
            from_status: 'saved',
            to_status: 'applied',
            snapshot: {
              captured_at: '2026-09-10T00:00:00Z',
              match: { score_percent: 72, assessed_weight: 40, low_confidence: true },
              fraud_risk_level: 'medium',
              employer_verification: 'unconfirmed',
            },
          }),
        ]}
      />
    )

    const summary = screen.getByText(/When you applied:/).closest('p')!
    expect(summary).toHaveTextContent('72% match — low confidence (40/100 points assessed)')
    expect(summary).toHaveTextContent('fraud risk medium')
    expect(summary).toHaveTextContent('employer unconfirmed')
  })

  it('records absence plainly instead of implying a clean bill of health', () => {
    render(
      <Timeline
        events={[
          event({
            from_status: 'saved',
            to_status: 'applied',
            snapshot: {
              captured_at: '2026-09-10T00:00:00Z',
              match: null,
              fraud_risk_level: null,
              employer_verification: null,
            },
          }),
        ]}
      />
    )

    const summary = screen.getByText(/When you applied:/).closest('p')!
    expect(summary).toHaveTextContent('not matched to your profile')
    expect(summary).toHaveTextContent('fraud check not run')
    expect(summary).toHaveTextContent('employer not verified')
  })
})

describe('StatusChangeForm', () => {
  const noop = () => {}

  it('offers exactly the moves it is given, and submits the chosen one with its date and note', () => {
    const onSubmit = vi.fn()
    render(
      <StatusChangeForm
        allowed={['screening', 'interviewing', 'rejected']}
        reopenTargets={[]}
        isPending={false}
        error={null}
        onSubmit={onSubmit}
      />
    )

    const options = within(screen.getByLabelText('Move to')).getAllByRole('option')
    expect(options.map((o) => o.textContent)).toEqual(['Screening', 'Interviewing', 'Rejected'])

    fireEvent.change(screen.getByLabelText('Move to'), { target: { value: 'interviewing' } })
    fireEvent.change(screen.getByLabelText('Date it happened'), { target: { value: '2026-09-15' } })
    fireEvent.change(screen.getByLabelText('Note (optional)'), { target: { value: '  Went well ' } })
    fireEvent.click(screen.getByRole('button', { name: 'Update status' }))

    expect(onSubmit).toHaveBeenCalledWith({
      status: 'interviewing',
      occurred_on: '2026-09-15',
      note: 'Went well',
    })
  })

  it('labels reopening as its own explicit choice', () => {
    render(
      <StatusChangeForm
        allowed={[]}
        reopenTargets={['applied', 'interviewing']}
        isPending={false}
        error={null}
        onSubmit={noop}
      />
    )

    const options = within(screen.getByLabelText('Move to')).getAllByRole('option')
    expect(options.map((o) => o.textContent)).toEqual(['Reopen as Applied', 'Reopen as Interviewing'])
  })

  it('says so when an application is final, with nothing to submit', () => {
    render(
      <StatusChangeForm allowed={[]} reopenTargets={[]} isPending={false} error={null} onSubmit={noop} />
    )

    expect(screen.getByText(/This application is final/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Update status' })).not.toBeInTheDocument()
  })

  it('shows the server’s explanation when a move is refused', () => {
    render(
      <StatusChangeForm
        allowed={['applied']}
        reopenTargets={[]}
        isPending={false}
        error="Mark the application as 'applied' first."
        onSubmit={noop}
      />
    )

    expect(screen.getByText("Mark the application as 'applied' first.")).toBeInTheDocument()
  })
})

describe('dueFollowUps', () => {
  it('keeps only overdue and due-today, overdue first, oldest first within each', () => {
    const apps = [
      application({ id: 'today', follow_up_state: 'due_today', next_action_on: '2026-09-21' }),
      application({ id: 'later', follow_up_state: 'upcoming', next_action_on: '2026-09-30' }),
      application({ id: 'old', follow_up_state: 'overdue', next_action_on: '2026-09-01' }),
      application({ id: 'none', follow_up_state: null }),
      application({ id: 'newer', follow_up_state: 'overdue', next_action_on: '2026-09-10' }),
    ]

    expect(dueFollowUps(apps).map((a) => a.id)).toEqual(['old', 'newer', 'today'])
  })
})
