import { fireEvent, render, screen, within } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'
import type { AtsCheck } from '@/lib/api'
import { AtsResults } from '@/features/ats/AtsResults'

function result(overrides: Partial<AtsCheck> = {}): AtsCheck {
  return {
    resume_source: 'profile',
    accepted_changes: 0,
    keyword_stats: {
      required_found: 1,
      required_total: 2,
      preferred_found: 0,
      preferred_total: 1,
      in_context: 0,
      coverage_percent: 33,
    },
    keywords: [
      {
        name: 'Python',
        kind: 'required',
        state: 'listed_only',
        detail: 'Only in your Skills list. Your evidence links it to: Vaultic — University.',
        roles: ['Vaultic — University'],
      },
      {
        name: 'Kubernetes',
        kind: 'required',
        state: 'gap',
        detail: "It isn't in your profile, so it isn't on your resume.",
        roles: [],
      },
      {
        name: 'Docker',
        kind: 'preferred',
        state: 'gap',
        detail: "It's in your profile with no evidence recorded, so it isn't listed.",
        roles: [],
      },
    ],
    checks: [
      { key: 'sections', label: 'Section headings', status: 'pass', detail: 'Standard headings found.' },
      { key: 'contact', label: 'Contact details', status: 'fail', detail: 'No email or phone number found.' },
      { key: 'hazards', label: 'Characters that can trip parsers', status: 'warn', detail: 'Contains — ×2.' },
    ],
    summary: { passed: 1, warn: 1, fail: 1 },
    limitations: [
      'No vendor publishes how it scores resumes.',
      'Keywords are matched by name and aliases.',
    ],
    ...overrides,
  }
}

function renderResults(r: AtsCheck, props: { notice?: string | null; isBusy?: boolean } = {}) {
  const onDownloadSafe = vi.fn()
  render(
    <AtsResults result={r} onDownloadSafe={onDownloadSafe} isBusy={props.isBusy ?? false} notice={props.notice ?? null} />
  )
  return onDownloadSafe
}

describe('AtsResults', () => {
  it('says which resume was checked', () => {
    const { unmount } = render(
      <AtsResults result={result()} onDownloadSafe={vi.fn()} isBusy={false} notice={null} />
    )
    expect(screen.getByText('Checked: the resume built from your profile.')).toBeInTheDocument()
    unmount()

    renderResults(result({ resume_source: 'tailored', accepted_changes: 2 }))
    expect(
      screen.getByText('Checked: your tailored resume (2 accepted changes).')
    ).toBeInTheDocument()
  })

  it('uses the singular for one accepted change', () => {
    renderResults(result({ resume_source: 'tailored', accepted_changes: 1 }))

    expect(screen.getByText(/1 accepted change\)/)).toBeInTheDocument()
  })

  it('shows the coverage number with a meter and the breakdown behind it', () => {
    renderResults(result())

    expect(screen.getByText('33%')).toBeInTheDocument()
    expect(screen.getByRole('progressbar', { name: 'Keyword coverage' })).toHaveAttribute('aria-valuenow', '33')
    expect(screen.getByText(/Required 1 of 2 · Preferred 0 of 1 · 0 used in context/)).toBeInTheDocument()
  })

  it('shows no number at all when the posting listed no skills to check', () => {
    renderResults(
      result({
        keywords: [],
        keyword_stats: {
          required_found: 0,
          required_total: 0,
          preferred_found: 0,
          preferred_total: 0,
          in_context: 0,
          coverage_percent: null,
        },
      })
    )

    expect(screen.getByText(/didn.t list any skills to check against/)).toBeInTheDocument()
    expect(screen.queryByRole('progressbar')).not.toBeInTheDocument()
    expect(screen.queryByText('0%')).not.toBeInTheDocument()
  })

  it('separates skills used in context from those only listed, and explains the difference', () => {
    renderResults(
      result({
        keywords: [
          { name: 'Flask', kind: 'required', state: 'in_context', detail: '', roles: [] },
          ...result().keywords.slice(0, 1),
        ],
      })
    )

    const inContext = screen.getByRole('list', { name: 'Skills used in context' })
    expect(within(inContext).getByText('Flask')).toBeInTheDocument()
    expect(screen.getByText('Only in your Skills list')).toBeInTheDocument()
    expect(screen.getByText(/Your evidence links it to: Vaultic — University\./)).toBeInTheDocument()
  })

  it('lists gaps with their reasons and says they are never added', () => {
    renderResults(result())

    expect(screen.getByText('Not on your resume')).toBeInTheDocument()
    expect(screen.getByText(/never added for you/)).toBeInTheDocument()
    expect(screen.getByText('Kubernetes')).toBeInTheDocument()
    expect(screen.getByText(/with no evidence recorded/)).toBeInTheDocument()
  })

  it('shows each structure check with its status and explanation', () => {
    renderResults(result())

    expect(screen.getByText('Section headings')).toBeInTheDocument()
    expect(screen.getByLabelText('Passed')).toBeInTheDocument()
    expect(screen.getByLabelText('Failed')).toBeInTheDocument()
    expect(screen.getByLabelText('Needs attention')).toBeInTheDocument()
    expect(screen.getByText('No email or phone number found.')).toBeInTheDocument()
    expect(screen.getByText('1 passed · 1 to review · 1 failed')).toBeInTheDocument()
  })

  it('offers the ATS-safe download, and swaps the hint for the notice after one', () => {
    const onDownload = renderResults(result())
    fireEvent.click(screen.getByRole('button', { name: /Download ATS-safe version/ }))

    expect(onDownload).toHaveBeenCalledOnce()
    expect(screen.getByText(/It still needs your contact details/)).toBeInTheDocument()
  })

  it('shows a custom notice and disables the download while busy', () => {
    renderResults(result(), { notice: 'Downloaded. Add your contact details.', isBusy: true })

    expect(screen.getByText('Downloaded. Add your contact details.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /Download ATS-safe version/ })).toBeDisabled()
  })

  it('states the limits of what the check can tell you', () => {
    renderResults(result())

    expect(screen.getByText("What this can't tell you")).toBeInTheDocument()
    expect(screen.getByText('No vendor publishes how it scores resumes.')).toBeInTheDocument()
    expect(screen.getByText('Keywords are matched by name and aliases.')).toBeInTheDocument()
  })
})
