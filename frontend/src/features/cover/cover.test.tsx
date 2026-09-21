import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { CoverLetter, CoverParagraph } from '@/lib/api'
import { CoverResults } from '@/features/cover/CoverResults'
import { ParagraphCard } from '@/features/cover/ParagraphCard'

function paragraph(overrides: Partial<CoverParagraph> = {}): CoverParagraph {
  return {
    id: 'p1',
    position: 1,
    role: 'body',
    text: 'At Vaultic I built a fraud detection web application using Flask.',
    edited_text: null,
    is_edited: false,
    decision: 'pending',
    sentences: [
      {
        text: 'At Vaultic I built a fraud detection web application using Flask.',
        kind: 'fact',
        supports: [
          {
            type: 'profile_experience',
            ref: 'exp:e1',
            label: 'Vaultic — University',
            excerpt: 'Building a fraud detection web application using Flask.',
          },
        ],
      },
      { text: 'Thank you for your time.', kind: 'framing', supports: [] },
    ],
    ...overrides,
  }
}

function letter(overrides: Partial<CoverLetter> = {}): CoverLetter {
  return {
    id: 'l1',
    job_posting_id: 'j1',
    status: 'completed',
    error: null,
    is_stale: false,
    started_at: '2026-09-21T10:00:00Z',
    paragraphs: [paragraph()],
    gaps: [],
    dropped: [],
    counts: { accepted: 0, rejected: 0, pending: 1 },
    preview_text: '',
    ...overrides,
  }
}

function renderCard(p: CoverParagraph, disabled = false) {
  const handlers = { onDecide: vi.fn(), onEdit: vi.fn() }
  render(<ParagraphCard paragraph={p} disabled={disabled} {...handlers} />)
  return handlers
}

describe('ParagraphCard', () => {
  it('shows the paragraph and what it needs from the user', () => {
    renderCard(paragraph())

    expect(screen.getByText('Body paragraph')).toBeInTheDocument()
    expect(screen.getAllByText(/At Vaultic I built a fraud detection/)[0]).toBeInTheDocument()
    expect(screen.getByText('Needs your decision')).toBeInTheDocument()
  })

  it('lets you trace each claim to its source, and says framing states no facts', () => {
    render(
      <ParagraphCard
        paragraph={paragraph({
          sentences: [
            {
              text: 'I am applying for the role.',
              kind: 'fact',
              supports: [
                { type: 'posting_quote', ref: 'ML Engineer', label: 'The posting', excerpt: 'ML Engineer' },
              ],
            },
            ...paragraph().sentences,
          ],
        })}
        onDecide={vi.fn()}
        onEdit={vi.fn()}
        disabled={false}
      />
    )

    expect(screen.getByText('Where this comes from')).toBeInTheDocument()
    expect(screen.getByText('Your role')).toBeInTheDocument()
    expect(screen.getByText('Vaultic — University')).toBeInTheDocument()
    expect(screen.getByText(/Building a fraud detection web application using Flask\./)).toBeInTheDocument()
    expect(screen.getByText('The posting says')).toBeInTheDocument()
    expect(screen.getByText(/checked to contain none/)).toBeInTheDocument()
  })

  it('accepts or rejects by paragraph id, and offers only Undo once decided', () => {
    const handlers = renderCard(paragraph({ id: 'abc' }))

    fireEvent.click(screen.getByRole('button', { name: /Accept/ }))
    fireEvent.click(screen.getByRole('button', { name: /Reject/ }))
    expect(handlers.onDecide).toHaveBeenNthCalledWith(1, 'abc', 'accepted')
    expect(handlers.onDecide).toHaveBeenNthCalledWith(2, 'abc', 'rejected')
  })

  it('shows Undo (and no Accept) for a decided paragraph', () => {
    const handlers = renderCard(paragraph({ decision: 'accepted' }))

    expect(screen.getByText('Accepted')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Accept/ })).not.toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: /Undo/ }))
    expect(handlers.onDecide).toHaveBeenCalledWith('p1', 'pending')
  })

  it('edits in place, saves the trimmed text, and warns that edits are not fact-checked', () => {
    const handlers = renderCard(paragraph())

    fireEvent.click(screen.getByRole('button', { name: /Edit/ }))
    expect(screen.getByText(/isn.t fact-checked/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Edit paragraph'), {
      target: { value: '  My own wording.  ' },
    })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))

    expect(handlers.onEdit).toHaveBeenCalledWith('p1', 'My own wording.')
  })

  it('does not count an unchanged save as an edit, and cannot save empty text', () => {
    const handlers = renderCard(paragraph())

    fireEvent.click(screen.getByRole('button', { name: /Edit/ }))
    expect(screen.getByLabelText('Edit paragraph')).toHaveValue(paragraph().text)
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(handlers.onEdit).toHaveBeenCalledWith('p1', null) // same as the original: not an edit

    fireEvent.click(screen.getByRole('button', { name: /Edit/ }))
    fireEvent.change(screen.getByLabelText('Edit paragraph'), { target: { value: '   ' } })
    expect(screen.getByRole('button', { name: 'Save' })).toBeDisabled()
  })

  it('cancelling an edit changes nothing', () => {
    const handlers = renderCard(paragraph())

    fireEvent.click(screen.getByRole('button', { name: /Edit/ }))
    fireEvent.change(screen.getByLabelText('Edit paragraph'), { target: { value: 'Something else' } })
    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))

    expect(handlers.onEdit).not.toHaveBeenCalled()
    expect(screen.queryByLabelText('Edit paragraph')).not.toBeInTheDocument()
  })

  it('marks an edited paragraph as not fact-checked, keeps the original, and can restore it', () => {
    const handlers = renderCard(paragraph({ is_edited: true, edited_text: 'My own wording.' }))

    expect(screen.getByText('Edited by you — not fact-checked')).toBeInTheDocument()
    expect(screen.getByText('My own wording.')).toBeInTheDocument()
    expect(screen.getByText('See the fact-checked original')).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Restore original' }))
    expect(handlers.onEdit).toHaveBeenCalledWith('p1', null)
  })

  it('disables every control while something is being saved', () => {
    renderCard(paragraph(), true)

    for (const name of [/Accept/, /Reject/, /Edit/]) {
      expect(screen.getByRole('button', { name })).toBeDisabled()
    }
  })
})

function renderResults(l: CoverLetter, props: Partial<Parameters<typeof CoverResults>[0]> = {}) {
  const handlers = {
    onDecide: vi.fn(),
    onEdit: vi.fn(),
    onRegenerate: vi.fn(),
    onDelete: vi.fn(),
    onCopy: vi.fn(),
    onDownload: vi.fn(),
  }
  render(<CoverResults letter={l} isBusy={false} notice={null} {...handlers} {...props} />)
  return handlers
}

describe('CoverResults', () => {
  it('says nothing goes in until accepted, and summarizes the review state', () => {
    renderResults(letter({ counts: { accepted: 1, rejected: 1, pending: 2 } }))

    expect(screen.getByText('Nothing goes in the letter until you accept it')).toBeInTheDocument()
    expect(screen.getByText('2 to review · 1 accepted · 1 rejected')).toBeInTheDocument()
  })

  it('reports discarded sentences with the reason for each', () => {
    renderResults(
      letter({
        dropped: [
          { sentence: 'I have deep Kubernetes experience.', reason: "it mentions 'Kubernetes', which your profile doesn't support" },
          { sentence: 'I led a team of 12.', reason: 'it states number(s) not in the profile item it cites: 12' },
        ],
      })
    )

    expect(screen.getByText('2 sentences were discarded')).toBeInTheDocument()
    expect(screen.getByText(/I have deep Kubernetes experience\./)).toBeInTheDocument()
    expect(screen.getByText(/it mentions 'Kubernetes'/)).toBeInTheDocument()
    expect(screen.getByText(/number\(s\) not in the profile item it cites: 12/)).toBeInTheDocument()
  })

  it('uses the singular for one discarded sentence', () => {
    renderResults(letter({ dropped: [{ sentence: 'x', reason: 'y' }] }))

    expect(screen.getByText('1 sentence was discarded')).toBeInTheDocument()
  })

  it('lists skills the posting wants that the profile cannot back up, and says the letter never claims them', () => {
    renderResults(
      letter({ gaps: [{ skill: 'Kubernetes', kind: 'required', reason: "it isn't in your profile" }] })
    )

    expect(screen.getByText(/The letter never claims these/)).toBeInTheDocument()
    expect(screen.getByText('Kubernetes')).toBeInTheDocument()
  })

  it('warns when the profile changed after the draft', () => {
    renderResults(letter({ is_stale: true }))

    expect(screen.getByText('Your profile changed since this draft was written')).toBeInTheDocument()
  })

  it('shows the letter as it stands, or asks for a first accepted paragraph', () => {
    const { unmount } = render(
      <CoverResults
        letter={letter()}
        isBusy={false}
        notice={null}
        onDecide={vi.fn()}
        onEdit={vi.fn()}
        onRegenerate={vi.fn()}
        onDelete={vi.fn()}
        onCopy={vi.fn()}
        onDownload={vi.fn()}
      />
    )
    expect(screen.getByText('Accept at least one paragraph to start building the letter.')).toBeInTheDocument()
    unmount()

    renderResults(
      letter({
        counts: { accepted: 1, rejected: 0, pending: 0 },
        preview_text: 'Dear Hiring Team,\n\nHello.\n\nSincerely,\nAziz\n',
      })
    )
    expect(screen.getByText(/Dear Hiring Team,/)).toBeInTheDocument()
  })

  it('keeps export disabled until something is accepted, then wires copy and download', () => {
    const { unmount } = render(
      <CoverResults
        letter={letter()}
        isBusy={false}
        notice={null}
        onDecide={vi.fn()}
        onEdit={vi.fn()}
        onRegenerate={vi.fn()}
        onDelete={vi.fn()}
        onCopy={vi.fn()}
        onDownload={vi.fn()}
      />
    )
    expect(screen.getByRole('button', { name: /Copy text/ })).toBeDisabled()
    expect(screen.getByRole('button', { name: /Download/ })).toBeDisabled()
    unmount()

    const handlers = renderResults(letter({ counts: { accepted: 1, rejected: 0, pending: 0 } }), {
      notice: 'Copied. Add your contact details.',
    })
    fireEvent.click(screen.getByRole('button', { name: /Copy text/ }))
    fireEvent.click(screen.getByRole('button', { name: /Download/ }))

    expect(handlers.onCopy).toHaveBeenCalledOnce()
    expect(handlers.onDownload).toHaveBeenCalledOnce()
    expect(screen.getByText('Copied. Add your contact details.')).toBeInTheDocument()
  })

  it('makes regenerating two-step, warning that it discards choices and edits', () => {
    const handlers = renderResults(
      letter({ paragraphs: [paragraph({ is_edited: true, edited_text: 'Mine.' })] })
    )

    fireEvent.click(screen.getByRole('button', { name: /Regenerate/ }))
    expect(handlers.onRegenerate).not.toHaveBeenCalled()
    expect(screen.getByText(/discards the draft, your accept\/reject choices, and any edits/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Cancel' }))
    fireEvent.click(screen.getByRole('button', { name: /Regenerate/ }))
    fireEvent.click(screen.getAllByRole('button', { name: 'Regenerate' })[0])
    expect(handlers.onRegenerate).toHaveBeenCalledOnce()
  })

  it('makes deleting two-step and says the profile is unaffected', () => {
    const handlers = renderResults(letter())

    fireEvent.click(screen.getByRole('button', { name: /^Delete$/ }))
    expect(handlers.onDelete).not.toHaveBeenCalled()
    expect(screen.getByText(/Your profile isn.t affected/)).toBeInTheDocument()

    fireEvent.click(screen.getByRole('button', { name: 'Delete draft' }))
    expect(handlers.onDelete).toHaveBeenCalledOnce()
  })

  it('routes a paragraph decision and edit up to the caller', () => {
    const handlers = renderResults(letter())

    fireEvent.click(screen.getByRole('button', { name: /^Accept/ }))
    expect(handlers.onDecide).toHaveBeenCalledWith('p1', 'accepted')

    fireEvent.click(screen.getByRole('button', { name: /Edit/ }))
    fireEvent.change(screen.getByLabelText('Edit paragraph'), { target: { value: 'Mine.' } })
    fireEvent.click(screen.getByRole('button', { name: 'Save' }))
    expect(handlers.onEdit).toHaveBeenCalledWith('p1', 'Mine.')
  })
})
