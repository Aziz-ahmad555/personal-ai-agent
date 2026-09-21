import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { ResumeChange, TailoredResume } from '@/lib/api'
import { ChangeCard } from '@/features/resume/ChangeCard'
import { diffWords } from '@/features/resume/diff'
import { TailorResults } from '@/features/resume/TailorResults'

function change(overrides: Partial<ResumeChange> = {}): ResumeChange {
  return {
    id: 'c1',
    change_type: 'rewrite',
    target_id: 'exp:e1',
    target_label: 'Vaultic — University',
    before_text: 'Built a fraud detection app using Flask.',
    after_text: 'Developed a fraud detection app with Flask.',
    rationale: 'Leads with the application-building the posting cares about.',
    addresses: [{ requirement: 'Python', quote: 'strong Python skills' }],
    decision: 'pending',
    position: 0,
    ...overrides,
  }
}

function resume(overrides: Partial<TailoredResume> = {}): TailoredResume {
  return {
    id: 'r1',
    job_posting_id: 'j1',
    status: 'completed',
    error: null,
    is_stale: false,
    started_at: '2026-09-21T10:00:00Z',
    changes: [change()],
    gaps: [],
    dropped: [],
    counts: { accepted: 0, rejected: 0, pending: 1 },
    preview_markdown: '# ML Engineer\n',
    ...overrides,
  }
}

const flatten = (segments: { text: string; kind: string }[]) =>
  segments.map((s) => `${s.kind}:${s.text}`)

describe('diffWords', () => {
  it('marks nothing when the texts are identical', () => {
    const { before, after } = diffWords('Built a thing', 'Built a thing')

    expect(flatten(before)).toEqual(['same:Built a thing'])
    expect(flatten(after)).toEqual(['same:Built a thing'])
  })

  it('shows replaced words as removed on one side and added on the other', () => {
    const { before, after } = diffWords(
      'Built a fraud app using Flask',
      'Developed a fraud app with Flask'
    )

    expect(flatten(before)).toEqual(['removed:Built', 'same:a fraud app', 'removed:using', 'same:Flask'])
    expect(flatten(after)).toEqual(['added:Developed', 'same:a fraud app', 'added:with', 'same:Flask'])
  })

  it('handles pure insertions and deletions', () => {
    expect(flatten(diffWords('Built it', 'Built it well').after)).toEqual(['same:Built it', 'added:well'])
    expect(flatten(diffWords('Built it well', 'Built it').before)).toEqual(['same:Built it', 'removed:well'])
  })

  it('merges adjacent changed words into one highlighted phrase', () => {
    const { after } = diffWords('Built it', 'Designed and built it')

    expect(flatten(after)[0]).toBe('added:Designed and built')
  })

  it('copes with empty text', () => {
    expect(diffWords('', '')).toEqual({ before: [], after: [] })
    expect(flatten(diffWords('', 'New words').after)).toEqual(['added:New words'])
  })
})

describe('ChangeCard', () => {
  it('shows what the change is, why, and which posting requirement it speaks to', () => {
    render(<ChangeCard change={change()} onDecide={vi.fn()} disabled={false} />)

    expect(screen.getByText('Vaultic — University')).toBeInTheDocument()
    expect(screen.getByText(/Leads with the application-building/)).toBeInTheDocument()
    const chip = screen.getByText('Python')
    expect(chip).toHaveAttribute('title', 'Posting: “strong Python skills”')
    expect(screen.getByText('Needs your decision')).toBeInTheDocument()
  })

  it('highlights removed words in Before and added words in After', () => {
    const { container } = render(<ChangeCard change={change()} onDecide={vi.fn()} disabled={false} />)

    const marks = [...container.querySelectorAll('mark')].map((m) => m.textContent)
    expect(marks).toEqual(['Built', 'using', 'Developed', 'with'])
  })

  it('accepts or rejects by change id', () => {
    const onDecide = vi.fn()
    render(<ChangeCard change={change({ id: 'abc' })} onDecide={onDecide} disabled={false} />)

    fireEvent.click(screen.getByRole('button', { name: /Accept/ }))
    fireEvent.click(screen.getByRole('button', { name: /Reject/ }))

    expect(onDecide).toHaveBeenNthCalledWith(1, 'abc', 'accepted')
    expect(onDecide).toHaveBeenNthCalledWith(2, 'abc', 'rejected')
  })

  it('offers only Undo once decided, which puts it back to pending', () => {
    const onDecide = vi.fn()
    render(<ChangeCard change={change({ decision: 'accepted' })} onDecide={onDecide} disabled={false} />)

    expect(screen.getByText('Accepted')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /Accept/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Undo/ }))
    expect(onDecide).toHaveBeenCalledWith('c1', 'pending')
  })

  it('disables the controls while a decision is being saved', () => {
    render(<ChangeCard change={change()} onDecide={vi.fn()} disabled />)

    expect(screen.getByRole('button', { name: /Accept/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Reject/ })).toBeDisabled()
  })

  it('shows a skills reorder as two lists, marking what moved', () => {
    render(
      <ChangeCard
        change={change({
          change_type: 'skills_order',
          target_label: 'Skills',
          before_text: 'FastAPI\nPython\nLinux',
          after_text: 'Python\nFastAPI\nLinux',
          addresses: [],
        })}
        onDecide={vi.fn()}
        disabled={false}
      />
    )

    const after = screen.getByRole('list', { name: 'Skills after' })
    expect(within(after).getAllByText('moved')).toHaveLength(2) // Python and FastAPI swapped
    expect(within(after).getByText('Linux').closest('li')).not.toHaveTextContent('moved')
  })
})

function renderResults(r: TailoredResume, props: Partial<Parameters<typeof TailorResults>[0]> = {}) {
  const handlers = {
    onDecide: vi.fn(),
    onRegenerate: vi.fn(),
    onCopy: vi.fn(),
    onDownload: vi.fn(),
  }
  render(<TailorResults resume={r} isBusy={false} notice={null} {...handlers} {...props} />)
  return handlers
}

describe('TailorResults', () => {
  it('says nothing changes until accepted, and summarizes the review state', () => {
    renderResults(resume({ counts: { accepted: 1, rejected: 2, pending: 3 } }))

    expect(screen.getByText('Nothing changes until you accept it')).toBeInTheDocument()
    expect(screen.getByText('3 to review · 1 accepted · 2 rejected')).toBeInTheDocument()
  })

  it('reports discarded suggestions with the reason for each, never showing them as options', () => {
    renderResults(
      resume({
        dropped: [
          { source: 'AegisAI — Individual', reason: "it claims 'Kubernetes', which your profile doesn't support for this item" },
          { source: 'Professional summary', reason: 'it adds number(s) not in the original: 5' },
        ],
      })
    )

    expect(screen.getByText('2 suggestions were discarded')).toBeInTheDocument()
    expect(screen.getByText(/it claims 'Kubernetes'/)).toBeInTheDocument()
    expect(screen.getByText(/it adds number\(s\) not in the original: 5/)).toBeInTheDocument()
  })

  it('uses the singular for one discarded suggestion', () => {
    renderResults(resume({ dropped: [{ source: 'Summary', reason: 'because' }] }))

    expect(screen.getByText('1 suggestion was discarded')).toBeInTheDocument()
  })

  it('lists skills the posting wants that the profile cannot back up, and says none were added', () => {
    renderResults(
      resume({
        gaps: [
          { skill: 'Kubernetes', kind: 'required', reason: "it isn't in your profile" },
          { skill: 'Docker', kind: 'preferred', reason: "it's in your profile, but with no evidence recorded" },
        ],
      })
    )

    expect(screen.getByText(/can.t back up/)).toBeInTheDocument()
    expect(screen.getByText(/None of these were added to your resume/)).toBeInTheDocument()
    expect(screen.getByText('Kubernetes')).toBeInTheDocument()
    expect(screen.getByText(/with no evidence recorded/)).toBeInTheDocument()
  })

  it('says so when there is nothing honest to suggest', () => {
    renderResults(
      resume({
        changes: [],
        counts: { accepted: 0, rejected: 0, pending: 0 },
        gaps: [{ skill: 'Rust', kind: 'required', reason: "it isn't in your profile" }],
      })
    )

    expect(screen.getByText('No changes to suggest')).toBeInTheDocument()
    expect(screen.getByText(/See the gaps below/)).toBeInTheDocument()
  })

  it('warns when the profile changed after the draft was made', () => {
    renderResults(resume({ is_stale: true }))

    expect(screen.getByText('Your profile changed since this draft was made')).toBeInTheDocument()
  })

  it('shows the resume as it currently stands', () => {
    renderResults(resume({ preview_markdown: '# Aziz\n## Summary\nBuilds ML systems.\n' }))

    expect(screen.getByText(/Builds ML systems\./)).toBeInTheDocument()
    expect(screen.getByText(/0 accepted changes applied/)).toBeInTheDocument()
  })

  it('makes regenerating a two-step action, and warns when it would discard decisions', () => {
    const handlers = renderResults(resume({ counts: { accepted: 1, rejected: 0, pending: 0 } }))

    fireEvent.click(screen.getByRole('button', { name: /Regenerate/ }))
    expect(handlers.onRegenerate).not.toHaveBeenCalled()
    expect(screen.getByText(/discards the draft and your accept\/reject choices/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    expect(handlers.onRegenerate).not.toHaveBeenCalled()

    fireEvent.click(screen.getByRole('button', { name: /Regenerate/ }))
    fireEvent.click(screen.getAllByRole('button', { name: 'Regenerate' })[0])
    expect(handlers.onRegenerate).toHaveBeenCalledOnce()
  })

  it('wires copy, download, and shows the export notice', () => {
    const handlers = renderResults(resume(), { notice: 'Copied. Add your contact details.' })

    fireEvent.click(screen.getByRole('button', { name: /Copy Markdown/ }))
    fireEvent.click(screen.getByRole('button', { name: /Download/ }))

    expect(handlers.onCopy).toHaveBeenCalledOnce()
    expect(handlers.onDownload).toHaveBeenCalledOnce()
    expect(screen.getByText('Copied. Add your contact details.')).toBeInTheDocument()
  })

  it('routes a decision made on a card up to the caller', () => {
    const handlers = renderResults(resume())

    fireEvent.click(screen.getByRole('button', { name: /Accept/ }))

    expect(handlers.onDecide).toHaveBeenCalledWith('c1', 'accepted')
  })
})
