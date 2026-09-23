import type { ReactElement } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { DigestData, WeeklyDigest, WeeklyDigestSummary } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'
import { DigestPanel } from '@/features/reporting/DigestPanel'
import { DigestView } from '@/features/reporting/DigestView'

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

type Handler = (init?: RequestInit) => Response

function stubApi(routes: Record<string, Handler>) {
  const calls: { path: string; method: string; url: string }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const pathOnly = url.split('?')[0]
      const path = Object.keys(routes).find((key) => pathOnly.endsWith(key))
      calls.push({ path: path ?? url, method: init?.method ?? 'GET', url })
      if (!path) throw new Error(`Unexpected request: ${url}`)
      return routes[path](init)
    })
  )
  return calls
}

function renderAt(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>)
}

beforeEach(() => {
  useAuthStore.setState({ accessToken: 'token' })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  useAuthStore.setState({ accessToken: null })
})

function digestData(overrides: Partial<DigestData> = {}): DigestData {
  return {
    period: { start: '2026-09-16', end: '2026-09-23' },
    generated_at: '2026-09-23T10:00:00Z',
    career: {
      jobs_discovered: { count: 0, items: [] },
      matches_computed: { count: 0, items: [] },
      high_risk_postings: { count: 0, items: [] },
      application_status_changes: { count: 0, by_status: {}, items: [] },
      cover_letters_drafted: { count: 0, items: [] },
      resumes_drafted: { count: 0, items: [] },
      practice_sessions: {
        count: 0,
        items: [],
        verdict_tally: { addressed: 0, partially_addressed: 0, missed: 0, unclear: 0, unanswered: 0 },
      },
    },
    research: {
      queries_run: { count: 0, items: [] },
      queries_completed: { count: 0 },
      claims_added: { count: 0, by_status: {} },
    },
    gmail: { connected: false },
    github: { connected: false },
    calendar: { connected: false },
    attention: {
      follow_ups_overdue: [],
      follow_ups_due_today: [],
      stale_matches: [],
      stale_resumes: [],
      stale_cover_letters: [],
      stalled_runs: [],
      connections_needing_reauth: [],
      pending_audit_approvals: { count: 0 },
      pending_skill_proposals: { count: 0 },
    },
    ...overrides,
  }
}

function digest(overrides: Partial<WeeklyDigest> = {}): WeeklyDigest {
  return {
    id: 'd1',
    period_start: '2026-09-16',
    period_end: '2026-09-23',
    generated_at: '2026-09-23T10:00:00Z',
    data: digestData(),
    ...overrides,
  }
}

function summaryOf(d: WeeklyDigest): WeeklyDigestSummary {
  const { id, period_start, period_end, generated_at } = d
  return { id, period_start, period_end, generated_at }
}

describe('DigestPanel', () => {
  it('shows an empty state before any digest exists', async () => {
    stubApi({ '/reporting/digests': () => json([]) })
    renderAt(<DigestPanel />)

    expect(await screen.findByText('No digests yet')).toBeInTheDocument()
  })

  it('generates a digest and shows it immediately', async () => {
    const generated = digest()
    let created = false
    const calls = stubApi({
      '/reporting/digests': (init) => {
        if (init?.method === 'POST') {
          created = true
          return json(generated, 201)
        }
        return json(created ? [summaryOf(generated)] : [])
      },
    })
    renderAt(<DigestPanel />)

    fireEvent.click(await screen.findByRole('button', { name: 'Generate digest' }))

    expect(await screen.findByText('2026-09-16 to 2026-09-23')).toBeInTheDocument()
    expect(
      calls.some((c) => c.method === 'POST' && c.path === '/reporting/digests')
    ).toBe(true)
  })

  it('switches between past digests', async () => {
    const latest = digest({ id: 'd2', generated_at: '2026-09-23T10:00:00Z' })
    const older = digest({
      id: 'd1',
      generated_at: '2026-09-16T10:00:00Z',
      data: digestData({ period: { start: '2026-09-09', end: '2026-09-16' } }),
    })
    stubApi({
      '/reporting/digests': () => json([summaryOf(latest), summaryOf(older)]),
      '/reporting/digests/d2': () => json(latest),
      '/reporting/digests/d1': () => json(older),
    })
    renderAt(<DigestPanel />)

    await screen.findByRole('button', { name: 'Latest' })
    expect(await screen.findByText('2026-09-16 to 2026-09-23')).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: '9/16/2026' }))
    expect(await screen.findByText('2026-09-09 to 2026-09-16')).toBeInTheDocument()
  })

  it('deletes a digest', async () => {
    const one = digest()
    const calls = stubApi({
      '/reporting/digests': () => json([summaryOf(one)]),
      '/reporting/digests/d1': (init) =>
        init?.method === 'DELETE' ? json(null, 204) : json(one),
    })
    renderAt(<DigestPanel />)

    fireEvent.click(await screen.findByRole('button', { name: 'Delete this digest' }))

    await waitFor(() =>
      expect(calls.some((c) => c.method === 'DELETE' && c.path === '/reporting/digests/d1')).toBe(
        true
      )
    )
  })
})

describe('DigestView', () => {
  it('says nothing needs attention when there is nothing to flag', () => {
    renderAt(<DigestView digest={digest()} />)

    expect(screen.getByText('Nothing needs your attention right now.')).toBeInTheDocument()
  })

  it('lists every kind of attention signal', () => {
    renderAt(
      <DigestView
        digest={digest({
          data: digestData({
            attention: {
              follow_ups_overdue: [
                { id: 'j1', title: 'ML Engineer', company_name: 'Acme', next_action_text: 'Call recruiter' },
              ],
              follow_ups_due_today: [],
              stale_matches: [{ id: 'j2', title: 'Data Scientist', company_name: 'Beta' }],
              stale_resumes: [],
              stale_cover_letters: [],
              stalled_runs: [{ kind: 'sync', integration: 'gmail' }],
              connections_needing_reauth: ['github'],
              pending_audit_approvals: { count: 2 },
              pending_skill_proposals: { count: 1 },
            },
          }),
        })}
      />
    )

    expect(screen.getByText(/Follow-up overdue: ML Engineer — Acme — Call recruiter/)).toBeInTheDocument()
    expect(screen.getByText(/Match is stale: Data Scientist — Beta/)).toBeInTheDocument()
    expect(screen.getByText(/A sync didn.t finish and needs a retry: gmail/)).toBeInTheDocument()
    expect(screen.getByText(/Github needs to be reconnected/)).toBeInTheDocument()
    expect(screen.getByText(/2 action\(s\) awaiting your approval/)).toBeInTheDocument()
    expect(screen.getByText(/1 GitHub skill proposal\(s\) awaiting review/)).toBeInTheDocument()
  })

  it('shows career activity counts and the practice verdict tally', () => {
    renderAt(
      <DigestView
        digest={digest({
          data: digestData({
            career: {
              jobs_discovered: { count: 3, items: [] },
              matches_computed: {
                count: 1,
                items: [{ id: 'j1', title: 'ML Engineer', company_name: 'Acme', score_percent: 80, low_confidence: false }],
              },
              high_risk_postings: { count: 0, items: [] },
              application_status_changes: {
                count: 1,
                by_status: { interviewing: 1 },
                items: [],
              },
              cover_letters_drafted: { count: 1, items: [] },
              resumes_drafted: { count: 1, items: [] },
              practice_sessions: {
                count: 1,
                items: [],
                verdict_tally: { addressed: 2, partially_addressed: 0, missed: 1, unclear: 0, unanswered: 0 },
              },
            },
          }),
        })}
      />
    )

    expect(screen.getByText('3 new job(s) discovered')).toBeInTheDocument()
    expect(screen.getByText(/Match computed for ML Engineer — Acme: 80%/)).toBeInTheDocument()
    expect(screen.getByText(/1 application\(s\) moved to/)).toBeInTheDocument()
    expect(screen.getByText('interviewing')).toBeInTheDocument()
    expect(screen.getByText(/2 addressed.*1 missed/)).toBeInTheDocument()
  })

  it('reports gmail, github, and calendar honestly when not connected', () => {
    renderAt(<DigestView digest={digest()} />)

    expect(screen.getAllByText('Not connected.')).toHaveLength(2)
    expect(screen.getByText('Calendar is not connected.')).toBeInTheDocument()
  })

  it('lists upcoming interviews and deadlines when calendar is connected', () => {
    renderAt(
      <DigestView
        digest={digest({
          data: digestData({
            calendar: {
              connected: true,
              status: 'connected',
              upcoming_interviews: [
                { summary: 'Interview with Acme', start_at: '2026-09-25T15:00:00Z', is_all_day: false, job: null },
              ],
              upcoming_deadlines: [
                { summary: 'Apply by Friday', start_at: '2026-09-26T00:00:00Z', is_all_day: true, job: null },
              ],
            },
          }),
        })}
      />
    )

    expect(screen.getByText(/Interview: Interview with Acme/)).toBeInTheDocument()
    expect(screen.getByText(/Deadline: Apply by Friday/)).toBeInTheDocument()
  })

  it('downloads the export as a PDF blob', async () => {
    const createObjectURL = vi.fn(() => 'blob:mock')
    const revokeObjectURL = vi.fn()
    vi.stubGlobal('URL', { ...URL, createObjectURL, revokeObjectURL })
    stubApi({
      '/reporting/digests/d1/export': () =>
        new Response(new Blob([new Uint8Array([1, 2, 3])]), {
          status: 200,
          headers: { 'Content-Disposition': 'attachment; filename="weekly-digest-x.pdf"' },
        }),
    })
    renderAt(<DigestView digest={digest()} />)

    fireEvent.click(screen.getByRole('button', { name: /Export PDF/ }))

    await waitFor(() => expect(createObjectURL).toHaveBeenCalledOnce())
  })
})
