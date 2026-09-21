import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { CheckRow, ReadinessSection } from '@/features/github/ReadinessSection'
import {
  check,
  CONNECTION,
  json,
  readiness,
  renderAt,
  repoReview,
  RUN,
  stubApi,
} from '@/features/github/test-utils'
import { GithubPage } from '@/pages/github'
import { useAuthStore } from '@/stores/auth'

beforeEach(() => {
  useAuthStore.setState({ accessToken: 'token' })
})

afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
  useAuthStore.setState({ accessToken: null })
})

describe('CheckRow', () => {
  it.each([
    ['pass', 'Passed'],
    ['warn', 'Needs attention'],
    ['fail', 'Failed'],
    ['unknown', 'Unknown'],
  ] as const)('shows %s with an accessible label', (status, label) => {
    renderAt(
      <ul>
        <CheckRow check={check({ status })} />
      </ul>
    )

    expect(screen.getByLabelText(label)).toBeInTheDocument()
  })

  it('shows the evidence link and the fix only when there are some', () => {
    const { unmount } = renderAt(
      <ul>
        <CheckRow check={check({ evidence_url: 'https://github.com/x/y/blob/main/README.md' })} />
      </ul>
    )
    expect(screen.getByRole('link', { name: 'View' })).toHaveAttribute(
      'href',
      'https://github.com/x/y/blob/main/README.md'
    )
    expect(screen.getByText('Add a LICENSE file.')).toBeInTheDocument()
    unmount()

    renderAt(
      <ul>
        <CheckRow check={check({ status: 'pass', fix: null })} />
      </ul>
    )
    expect(screen.queryByRole('link', { name: 'View' })).not.toBeInTheDocument()
    expect(screen.queryByText('Add a LICENSE file.')).not.toBeInTheDocument()
  })
})

describe('ReadinessSection', () => {
  it('asks for a sync before there is anything to review and disables the copy button', async () => {
    stubApi({})
    renderAt(<ReadinessSection />)

    expect(await screen.findByText(/Nothing to review yet/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Copy as checklist' })).toBeDisabled()
  })

  it('leads with what to fix first, in order, with the reason and the fix', async () => {
    stubApi({ '/github/readiness': () => json(readiness()) })
    renderAt(<ReadinessSection />)

    const fixes = await screen.findByRole('region', { name: 'Fix first' })
    const items = within(fixes).getAllByRole('listitem')
    expect(items).toHaveLength(2)
    expect(within(items[0]).getByRole('link', { name: 'AegisAI' })).toBeInTheDocument()
    expect(within(items[0]).getByLabelText('Failed')).toBeInTheDocument()
    expect(within(items[0]).getByText('Add a README.md.')).toBeInTheDocument()
    expect(within(items[1]).getByText('Your profile')).toBeInTheDocument()
    expect(within(items[1]).getByLabelText('Needs attention')).toBeInTheDocument()
  })

  it('shows each repository with how many checks pass and how many are unknown', async () => {
    stubApi({ '/github/readiness': () => json(readiness()) })
    renderAt(<ReadinessSection />)

    expect(await screen.findByText(/1 of 4 pass · 1 unknown/)).toBeInTheDocument()
    const list = screen.getByRole('list', { name: 'Checks for AegisAI', hidden: true })
    expect(within(list).getByText('No junk files committed')).toBeInTheDocument()
    expect(within(list).getByRole('link', { name: 'View', hidden: true })).toHaveAttribute(
      'href',
      'https://github.com/aziz-ahmad555/AegisAI/blob/main/.yolov8n.part'
    )
  })

  it('never presents an unknown check as a pass or a fix', async () => {
    stubApi({ '/github/readiness': () => json(readiness()) })
    renderAt(<ReadinessSection />)

    await screen.findByRole('region', { name: 'Fix first' })
    const list = screen.getByRole('list', { name: 'Checks for AegisAI', hidden: true })
    const tests = within(list).getByText('Has automated tests').closest('li') as HTMLElement
    expect(within(tests).getByLabelText('Unknown')).toBeInTheDocument()
    expect(within(tests).getByText('Sync again to include this.')).toBeInTheDocument()
    const fixes = screen.getByRole('region', { name: 'Fix first' })
    expect(within(fixes).queryByText('Has automated tests')).not.toBeInTheDocument()
  })

  it('lists repos that were not reviewed with the reason', async () => {
    stubApi({
      '/github/readiness': () =>
        json(
          readiness({
            repos: [
              repoReview({ name: 'upstream', reviewed: false, reason: 'A fork, so it isn’t reviewed as your work.', checks: [], passed: 0, total: 0, unknown: 0 }),
            ],
          })
        ),
    })
    renderAt(<ReadinessSection />)

    expect(await screen.findByText(/upstream/)).toBeInTheDocument()
    expect(screen.getByText(/not reviewed/)).toBeInTheDocument()
    expect(screen.getByText(/Not reviewed: A fork/, { exact: false })).toBeInTheDocument()
  })

  it('shows the profile checks and the limits of the review', async () => {
    stubApi({ '/github/readiness': () => json(readiness()) })
    renderAt(<ReadinessSection />)

    const profile = await screen.findByRole('region', { name: 'Your profile' })
    expect(within(profile).getByText('Bio is set')).toBeInTheDocument()
    expect(within(profile).getByText('Has a profile README')).toBeInTheDocument()
    expect(screen.getByText("What this can't tell you")).toBeInTheDocument()
    expect(screen.getByText(/Pinned repositories/)).toBeInTheDocument()
  })

  it('says so when checks are unknown only because the last sync is older', async () => {
    stubApi({ '/github/readiness': () => json(readiness({ needs_resync: true })) })
    renderAt(<ReadinessSection />)

    expect(await screen.findByText('Some checks are unknown')).toBeInTheDocument()
    expect(screen.getByText(/Sync again to include them/)).toBeInTheDocument()
  })

  it('does not claim everything is fine when nothing could be checked', async () => {
    stubApi({
      '/github/readiness': () => json(readiness({ fixes: [], repos: [repoReview({ unknown: 3 })] })),
    })
    renderAt(<ReadinessSection />)

    expect(await screen.findByText(/Nothing to fix from what could be checked/)).toBeInTheDocument()
    expect(screen.getByText(/Some checks are unknown, so this may not be everything/)).toBeInTheDocument()
  })

  it('shows an error with a retry when the review cannot be loaded', async () => {
    stubApi({ '/github/readiness': () => json({ detail: 'boom' }, 500) })
    renderAt(<ReadinessSection />)

    expect(await screen.findByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})

async function clickCopy() {
  const button = await screen.findByRole('button', { name: 'Copy as checklist' })
  await waitFor(() => expect(button).toBeEnabled()) // it stays disabled until the review has loaded
  fireEvent.click(button)
}

describe('copying the checklist', () => {
  const EXPORT = { filename: 'github-readiness-me.md', text: '# GitHub recruiter-readiness: @me\n- [ ] Has a README' }

  it('fetches the checklist and copies it to the clipboard', async () => {
    const writeText = vi.fn(async () => {})
    vi.stubGlobal('navigator', { clipboard: { writeText } })
    stubApi({
      '/github/readiness': () => json(readiness()),
      '/github/readiness/export': () => json(EXPORT),
    })
    renderAt(<ReadinessSection />)

    await clickCopy()

    await waitFor(() => expect(writeText).toHaveBeenCalledWith(EXPORT.text))
    expect(await screen.findByRole('button', { name: 'Copied' })).toBeInTheDocument()
  })

  it('shows the text to copy by hand when the browser blocks the clipboard', async () => {
    vi.stubGlobal('navigator', {
      clipboard: {
        writeText: vi.fn(async () => {
          throw new Error('denied')
        }),
      },
    })
    stubApi({
      '/github/readiness': () => json(readiness()),
      '/github/readiness/export': () => json(EXPORT),
    })
    renderAt(<ReadinessSection />)

    await clickCopy()

    const box = await screen.findByLabelText('Checklist text')
    expect(box).toHaveValue(EXPORT.text)
    expect(screen.getByText(/blocked copying/)).toBeInTheDocument()
  })

  it('shows why the checklist could not be prepared', async () => {
    stubApi({
      '/github/readiness': () => json(readiness()),
      '/github/readiness/export': () => json({ detail: 'Not found' }, 404),
    })
    renderAt(<ReadinessSection />)

    await clickCopy()

    expect(await screen.findByText("Couldn't prepare the checklist")).toBeInTheDocument()
  })
})

describe('on the GitHub page', () => {
  it('appears with the other sections when connected', async () => {
    stubApi({
      '/github/connection': () => json(CONNECTION),
      '/github/sync': () => json([RUN]),
      '/github/readiness': () => json(readiness()),
    })
    renderAt(<GithubPage />)

    expect(await screen.findByText('Recruiter-readiness')).toBeInTheDocument()
    expect(await screen.findByRole('region', { name: 'Fix first' })).toBeInTheDocument()
  })
})
