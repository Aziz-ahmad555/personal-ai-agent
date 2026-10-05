import type { ReactElement } from 'react'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { cleanup, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { CareerJob, PracticeQuestion, PracticeSession, PracticeSessionSummary } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'
import { PracticePanel } from '@/features/practice/PracticePanel'
import { PracticeSessionView } from '@/features/practice/PracticeSessionView'
import { QuestionCard } from '@/features/practice/QuestionCard'

function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

type Handler = (init?: RequestInit) => Response

function stubApi(routes: Record<string, Handler>) {
  const calls: { path: string; method: string; url: string; body?: unknown }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const pathOnly = url.split('?')[0]
      const path = Object.keys(routes).find((key) => pathOnly.endsWith(key))
      calls.push({
        path: path ?? url,
        method: init?.method ?? 'GET',
        url,
        body: init?.body ? JSON.parse(init.body as string) : undefined,
      })
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

function job(overrides: Partial<CareerJob> = {}): CareerJob {
  return {
    id: 'job-1',
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
    description_text: 'text',
    posted_at: null,
    discovered_at: '2026-09-01T00:00:00Z',
    employer_verification: null,
    fraud_assessment: null,
    match: {
      id: 'm1',
      status: 'completed',
      error: null,
      score_percent: 80,
      assessed_weight: 80,
      low_confidence: false,
      components: [],
      uncertainties: [],
      deal_breaker_check: 'none_set',
      deal_breaker_hits: [],
      is_stale: false,
      computed_at: '2026-09-01T00:00:00Z',
    },
    ...overrides,
  }
}

function question(overrides: Partial<PracticeQuestion> = {}): PracticeQuestion {
  return {
    id: 'q1',
    position: 0,
    text: 'How have you used Python day to day?',
    category: 'technical',
    ref_type: 'posting_requirement',
    ref_name: 'Python',
    ref_excerpt: 'strong Python skills',
    answer_text: null,
    answered_at: null,
    verdict: null,
    feedback_text: null,
    ...overrides,
  }
}

function session(overrides: Partial<PracticeSession> = {}): PracticeSession {
  return {
    id: 's1',
    job_posting_id: 'job-1',
    application_id: null,
    status: 'ready_for_answers',
    error: null,
    started_at: '2026-09-22T10:00:00Z',
    created_at: '2026-09-22T10:00:00Z',
    question_count: 1,
    counts: { addressed: 0, partially_addressed: 0, missed: 0, unclear: 0, unanswered: 1 },
    questions: [question()],
    dropped: [],
    ...overrides,
  }
}

function summaryOf(s: PracticeSession): PracticeSessionSummary {
  const { id, status, error, started_at, created_at, question_count, counts } = s
  return { id, status, error, started_at, created_at, question_count, counts }
}

describe('QuestionCard', () => {
  it('lets you type an answer in editable mode', () => {
    const onChange = vi.fn()
    render(<QuestionCard question={question()} index={0} editable value="" onChange={onChange} />)

    fireEvent.change(screen.getByLabelText(/Your answer to/), { target: { value: 'I use it daily.' } })

    expect(onChange).toHaveBeenCalledWith('I use it daily.')
  })

  it('shows the given answer and feedback, or says none was given', () => {
    const { unmount } = render(
      <QuestionCard question={question({ answer_text: null })} index={0} editable={false} />
    )
    expect(screen.getByText('No answer was given.')).toBeInTheDocument()
    unmount()

    render(
      <QuestionCard
        question={question({
          answer_text: 'I use Python daily.',
          verdict: 'addressed',
          feedback_text: 'The candidate addresses the requirement directly.',
        })}
        index={0}
        editable={false}
      />
    )
    expect(screen.getByText(/I use Python daily\./)).toBeInTheDocument()
    expect(screen.getByText('Addressed')).toBeInTheDocument()
    expect(screen.getByText('The candidate addresses the requirement directly.')).toBeInTheDocument()
  })

  it('discloses what the question is grounded in', () => {
    render(<QuestionCard question={question()} index={0} editable={false} />)

    expect(screen.getByText(/From the posting: Python/)).toBeInTheDocument()
    expect(screen.getByText('strong Python skills')).toBeInTheDocument()
  })
})

describe('PracticeSessionView', () => {
  it('shows a loading state while questions are being written', async () => {
    stubApi({ '/career/practice-sessions/s1': () => json(session({ status: 'questions_running' })) })
    renderAt(<PracticeSessionView sessionId="s1" jobId="job-1" />)

    expect(await screen.findByText(/Writing practice questions/)).toBeInTheDocument()
  })

  it('shows a loading state while feedback is being generated', async () => {
    stubApi({ '/career/practice-sessions/s1': () => json(session({ status: 'feedback_running' })) })
    renderAt(<PracticeSessionView sessionId="s1" jobId="job-1" />)

    expect(await screen.findByText(/Checking your answers/)).toBeInTheDocument()
  })

  it('submits answers for every question, including ones left blank', async () => {
    const calls = stubApi({
      '/career/practice-sessions/s1/answers': () => json({ status: 'feedback_started' }, 202),
      '/career/practice-sessions/s1': () =>
        json(session({ questions: [question({ id: 'q1' }), question({ id: 'q2', position: 1 })] })),
    })
    renderAt(<PracticeSessionView sessionId="s1" jobId="job-1" />)

    const [first] = await screen.findAllByLabelText(/Your answer to/)
    fireEvent.change(first, { target: { value: 'I ship Python services weekly.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Submit for feedback' }))

    await waitFor(() =>
      expect(calls.some((c) => c.method === 'PATCH' && c.path === '/career/practice-sessions/s1/answers')).toBe(
        true
      )
    )
    const patch = calls.find((c) => c.method === 'PATCH')
    expect(patch?.body).toEqual({
      answers: [
        { question_id: 'q1', answer_text: 'I ship Python services weekly.' },
        { question_id: 'q2', answer_text: '' },
      ],
    })
  })

  it('shows verdicts, feedback, and a plain tally once completed', async () => {
    stubApi({
      '/career/practice-sessions/s1': () =>
        json(
          session({
            status: 'completed',
            questions: [
              question({
                answer_text: 'I use Python daily.',
                verdict: 'addressed',
                feedback_text: 'Matches the requirement.',
              }),
            ],
            counts: { addressed: 1, partially_addressed: 0, missed: 0, unclear: 0, unanswered: 0 },
          })
        ),
    })
    renderAt(<PracticeSessionView sessionId="s1" jobId="job-1" />)

    expect(await screen.findByText('1 addressed')).toBeInTheDocument()
    expect(screen.getByText('Matches the requirement.')).toBeInTheDocument()
    expect(screen.queryByLabelText(/Your answer to/)).not.toBeInTheDocument() // read-only, not editable
  })

  it('offers a retry with existing answers when feedback failed, but not when questions never generated', async () => {
    stubApi({
      '/career/practice-sessions/s1': () =>
        json(
          session({
            status: 'failed',
            error: 'Gemini call failed: 429 RESOURCE_EXHAUSTED',
            questions: [question({ answer_text: 'I use Python daily.' })],
          })
        ),
    })
    renderAt(<PracticeSessionView sessionId="s1" jobId="job-1" />)

    expect(await screen.findByText("Couldn't get feedback")).toBeInTheDocument()
    const retry = screen.getByRole('button', { name: 'Retry feedback' })
    expect(retry).toBeInTheDocument()
    expect(screen.getByLabelText(/Your answer to/)).toHaveValue('I use Python daily.')
  })

  it('offers no retry when no questions could be grounded at all', async () => {
    stubApi({
      '/career/practice-sessions/s1': () =>
        json(session({ status: 'failed', error: 'No requirements could be read.', questions: [] })),
    })
    renderAt(<PracticeSessionView sessionId="s1" jobId="job-1" />)

    expect(await screen.findByText("Couldn't write questions")).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Retry|Submit/ })).not.toBeInTheDocument()
  })

  it('notes when a proposed question could not be grounded and was skipped', async () => {
    stubApi({
      '/career/practice-sessions/s1': () =>
        json(session({ dropped: [{ question: 'How would you use Rust?', reason: "it referenced 'Rust'" }] })),
    })
    renderAt(<PracticeSessionView sessionId="s1" jobId="job-1" />)

    expect(await screen.findByText(/1 proposed question couldn.t be grounded/)).toBeInTheDocument()
  })
})

describe('PracticePanel', () => {
  it('asks to score the match first, and offers no start button yet', async () => {
    stubApi({})
    renderAt(<PracticePanel job={job({ match: null })} />)

    expect(await screen.findByText(/Score this job.s match above first/)).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Start new practice session/ })).not.toBeInTheDocument()
  })

  it('starts a session and lists it once created', async () => {
    let started = false
    stubApi({
      '/career/jobs/job-1/practice-sessions': (init) => {
        if (init?.method === 'POST') {
          started = true
          return json({ status: 'questions_started' }, 202)
        }
        return json(started ? [summaryOf(session({ status: 'questions_running' }))] : [])
      },
      '/career/practice-sessions/s1': () => json(session({ status: 'questions_running' })),
    })
    renderAt(<PracticePanel job={job()} />)

    expect(await screen.findByText('No practice sessions yet.')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Start new practice session' }))

    expect(await screen.findByText(/Writing practice questions/)).toBeInTheDocument()
  })

  it('disables starting a new session while one is already active', async () => {
    stubApi({
      '/career/jobs/job-1/practice-sessions': () => json([summaryOf(session({ status: 'ready_for_answers' }))]),
      '/career/practice-sessions/s1': () => json(session()),
    })
    renderAt(<PracticePanel job={job()} />)

    const button = await screen.findByRole('button', { name: 'A session is already in progress' })
    expect(button).toBeDisabled()
  })

  it('switches between past sessions and deletes one', async () => {
    const older = session({ id: 's0', status: 'completed', created_at: '2026-09-20T10:00:00Z' })
    const latest = session({ id: 's1', status: 'ready_for_answers' })
    const calls = stubApi({
      '/career/jobs/job-1/practice-sessions': () => json([summaryOf(latest), summaryOf(older)]),
      '/career/practice-sessions/s1': () => json(latest),
      '/career/practice-sessions/s0': () => json(older, 200),
    })
    renderAt(<PracticePanel job={job()} />)

    await screen.findByRole('button', { name: 'Latest' })
    expect(await screen.findByLabelText(/Your answer to/)).toBeInTheDocument() // s1 is editable

    fireEvent.click(screen.getByRole('button', { name: '9/20/2026' }))
    await waitFor(() => expect(screen.queryByLabelText(/Your answer to/)).not.toBeInTheDocument())

    fireEvent.click(screen.getAllByRole('button', { name: 'Delete this practice session' })[0])
    await waitFor(() =>
      expect(calls.some((c) => c.method === 'DELETE' && c.path.startsWith('/career/practice-sessions/'))).toBe(
        true
      )
    )
  })
})
