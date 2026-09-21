import { cleanup, fireEvent, screen, waitFor, within } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import type { GithubContribution } from '@/lib/api'
import { describeCommits, describeContribution, exclusionReason, kb } from '@/features/github/format'
import { RepoList } from '@/features/github/RepoList'
import { ProposalsSection } from '@/features/github/ProposalsSection'
import { SyncCard } from '@/features/github/SyncCard'
import {
  CONNECTION,
  json,
  proposal,
  renderAt,
  repo,
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

function contribution(overrides: Partial<GithubContribution> = {}): GithubContribution {
  return {
    repo: 'AegisAI',
    repo_url: 'https://github.com/x/AegisAI',
    via: 'language',
    source_url: 'https://github.com/x/AegisAI',
    source_file: null,
    bytes: 114846,
    commits: 43,
    last_commit_at: '2026-09-12T10:00:00Z',
    attribution: 'attributed',
    ...overrides,
  }
}

describe('format helpers', () => {
  it('formats sizes like the backend does', () => {
    expect(kb(114846)).toBe('114.8 KB')
    expect(kb(1384)).toBe('1.4 KB')
  })

  it('describes each kind of evidence with only recorded facts', () => {
    expect(describeContribution(contribution())).toBe('114.8 KB of code · 43 commits by you, last 2026-09-12')
    expect(describeContribution(contribution({ commits: 1 }))).toContain('1 commit by you')
    expect(
      describeContribution(contribution({ via: 'dependency', source_file: 'backend/requirements.txt' }))
    ).toContain('declared in backend/requirements.txt')
    expect(describeContribution(contribution({ via: 'file', source_file: 'Dockerfile' }))).toContain(
      'has a Dockerfile'
    )
  })

  it('never turns missing or unattributed commits into a claim', () => {
    expect(describeContribution(contribution({ attribution: 'ownership_only', commits: 0 }))).toContain(
      'owned by you, no commits attributed to your account'
    )
    expect(describeContribution(contribution({ attribution: 'unknown', commits: null }))).toContain(
      'commit attribution unavailable'
    )
  })

  it('tells "not read" apart from "none attributed"', () => {
    expect(describeCommits(repo({ authored_commits: null }))).toBe('Commits not read')
    expect(describeCommits(repo({ authored_commits: 0 }))).toBe('No commits attributed to your account')
    expect(describeCommits(repo({ authored_commits: 1 }))).toBe('1 commit by you')
    expect(describeCommits(repo({ authored_commits: 43 }))).toBe('43 commits by you')
  })

  it('says why a repo is left out of evidence', () => {
    expect(exclusionReason(repo({ is_fork: true }))).toMatch(/fork/)
    expect(exclusionReason(repo({ is_archived: true }))).toMatch(/Archived/)
    expect(exclusionReason(repo({ details_fetched: false }))).toMatch(/couldn't be read/)
    expect(exclusionReason(repo())).toBeNull()
  })
})

describe('SyncCard', () => {
  it('invites a first sync and starts one on click', async () => {
    const calls = stubApi({
      '/github/sync': (init) => (init?.method === 'POST' ? json({ ...RUN, status: 'pending' }, 201) : json([])),
    })
    renderAt(<SyncCard connection={CONNECTION} />)

    expect(await screen.findByText(/Nothing synced yet/)).toBeInTheDocument()
    fireEvent.click(screen.getByRole('button', { name: 'Sync now' }))

    await waitFor(() => expect(calls.some((c) => c.method === 'POST' && c.path === '/github/sync')).toBe(true))
    expect(screen.getByText(/Nothing is written to GitHub/)).toBeInTheDocument()
  })

  it('shows a running sync and stops the button being pressed again', async () => {
    stubApi({ '/github/sync': () => json([{ ...RUN, status: 'running', completed_at: null }]) })
    renderAt(<SyncCard connection={CONNECTION} />)

    const button = await screen.findByRole('button', { name: 'Syncing…' })
    expect(button).toBeDisabled()
  })

  it('reports the last completed sync, its size and the recent activity with its 90-day limit', async () => {
    stubApi({ '/github/sync': () => json([RUN]) })
    renderAt(<SyncCard connection={CONNECTION} />)

    expect(await screen.findByText(/5 public repositories/)).toBeInTheDocument()
    expect(screen.getByText(/3 in detail, 16 requests/)).toBeInTheDocument()
    expect(screen.getByText(/65 pushes on 11 different days/)).toBeInTheDocument()
    expect(screen.getByText(/about the last 90 days/)).toBeInTheDocument()
  })

  it('shows a failed sync with its reason and keeps offering another try', async () => {
    stubApi({
      '/github/sync': () => json([{ ...RUN, status: 'failed', error: 'GitHub rejected the access token.' }]),
    })
    renderAt(<SyncCard connection={CONNECTION} />)

    expect(await screen.findByText('The last sync failed')).toBeInTheDocument()
    expect(screen.getByText('GitHub rejected the access token.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sync now' })).toBeEnabled()
  })

  it('lists everything that could not be read instead of hiding it', async () => {
    stubApi({
      '/github/sync': () => json([{ ...RUN, warnings: ["smart-campus-ai: couldn't be read this time (HTTP 500)."] }]),
    })
    renderAt(<SyncCard connection={CONNECTION} />)

    expect(await screen.findByText("Some things couldn't be read")).toBeInTheDocument()
    expect(screen.getByText(/smart-campus-ai: couldn't be read this time/)).toBeInTheDocument()
  })

  it('cannot sync until a broken connection is reconnected', async () => {
    stubApi({})
    renderAt(<SyncCard connection={{ ...CONNECTION, status: 'needs_reauth' }} />)

    expect(await screen.findByRole('button', { name: 'Sync now' })).toBeDisabled()
    expect(screen.getByText(/Reconnect GitHub above/)).toBeInTheDocument()
  })

  it('shows why a sync could not start', async () => {
    stubApi({
      '/github/sync': (init) =>
        init?.method === 'POST' ? json({ detail: 'A sync is already running.' }, 409) : json([]),
    })
    renderAt(<SyncCard connection={CONNECTION} />)

    fireEvent.click(await screen.findByRole('button', { name: 'Sync now' }))

    expect(await screen.findByText("Couldn't start the sync")).toBeInTheDocument()
    expect(screen.getByText('A sync is already running.')).toBeInTheDocument()
  })
})

describe('RepoList', () => {
  it('lists repos with their language, attributed commits and the reason any is left out', async () => {
    stubApi({
      '/github/repos': () =>
        json([
          repo(),
          repo({ id: 'g2', name: 'upstream', is_fork: true, authored_commits: null, primary_language: 'Go' }),
          repo({ id: 'g3', name: 'notebooks', authored_commits: 0 }),
        ]),
    })
    renderAt(<RepoList />)

    const list = await screen.findByRole('list', { name: 'Your public repositories' })
    const items = within(list).getAllByRole('listitem')
    expect(items).toHaveLength(3)
    expect(within(items[0]).getByRole('link', { name: 'AegisAI' })).toHaveAttribute(
      'href',
      'https://github.com/aziz-ahmad555/AegisAI'
    )
    expect(within(items[0]).getByText(/43 commits by you · last push 2026-09-12/)).toBeInTheDocument()
    expect(within(items[1]).getByText('Fork')).toBeInTheDocument()
    expect(within(items[1]).getByText(/Not used as evidence: A fork/)).toBeInTheDocument()
    expect(within(items[1]).getByText(/Commits not read/)).toBeInTheDocument()
    expect(within(items[2]).getByText(/No commits attributed to your account/)).toBeInTheDocument()
  })

  it('has an empty state and an error state with a retry', async () => {
    stubApi({ '/github/repos': () => json([]) })
    const { unmount } = renderAt(<RepoList />)
    expect(await screen.findByText(/They appear here after a sync/)).toBeInTheDocument()
    unmount()

    stubApi({ '/github/repos': () => json({ detail: 'boom' }, 500) })
    renderAt(<RepoList />)
    expect(await screen.findByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})

describe('ProposalsSection', () => {
  it('shows a proposal with linked evidence and the exact text that would be saved', async () => {
    stubApi({ '/github/proposals': () => json([proposal()]) })
    renderAt(<ProposalsSection />)

    const evidence = await screen.findByRole('list', { name: 'Evidence for Python' })
    expect(within(evidence).getByRole('link', { name: 'AegisAI' })).toHaveAttribute(
      'href',
      'https://github.com/aziz-ahmad555/AegisAI'
    )
    expect(within(evidence).getByText(/114.8 KB of code · 43 commits by you, last 2026-09-12/)).toBeInTheDocument()
    expect(screen.getByText('What will be saved on your profile')).toBeInTheDocument()
    expect(screen.getByText(/GitHub \(@aziz-ahmad555\): Python — AegisAI/)).toBeInTheDocument()
  })

  it('will not add a new skill until the user chooses a level, then sends it', async () => {
    const calls = stubApi({
      '/github/proposals': () => json([proposal()]),
      '/github/proposals/p1/accept': () =>
        json({ proposal: proposal({ status: 'accepted' }), skill_id: 's1', skill_version_id: 'v1' }),
    })
    renderAt(<ProposalsSection />)

    const add = await screen.findByRole('button', { name: 'Add to my profile' })
    expect(add).toBeDisabled()
    expect(screen.getByText(/not how proficient you are, so you set the level/)).toBeInTheDocument()
    fireEvent.change(screen.getByLabelText('Level'), { target: { value: 'advanced' } })
    expect(add).toBeEnabled()
    fireEvent.click(add)

    await waitFor(() =>
      expect(calls.find((c) => c.path === '/github/proposals/p1/accept')?.body).toEqual({ level: 'advanced' })
    )
  })

  it('keeps an existing skill at its current level unless the user picks another', async () => {
    const calls = stubApi({
      '/github/proposals': () =>
        json([proposal({ requires_level: false, existing_level: 'advanced', existing_skill_name: 'Python' })]),
      '/github/proposals/p1/accept': () =>
        json({ proposal: proposal({ status: 'accepted' }), skill_id: 's1', skill_version_id: 'v1' }),
    })
    renderAt(<ProposalsSection />)

    const add = await screen.findByRole('button', { name: 'Add to my profile' })
    expect(add).toBeEnabled()
    expect(screen.getByRole('option', { name: 'Keep my current level (advanced)' })).toBeInTheDocument()
    fireEvent.click(add)

    await waitFor(() =>
      expect(calls.find((c) => c.path === '/github/proposals/p1/accept')?.body).toEqual({ level: null })
    )
  })

  it('labels evidence that is only ownership, so it does not read as proven work', async () => {
    stubApi({
      '/github/proposals': () =>
        json([
          proposal({
            id: 'p2',
            skill_name: 'Jupyter Notebooks',
            attribution: 'ownership_only',
            contributions: [contribution({ attribution: 'ownership_only', commits: 0 })],
          }),
          proposal({ id: 'p3', skill_name: 'Go', attribution: 'unknown' }),
        ])
    })
    renderAt(<ProposalsSection />)

    expect(await screen.findByText('Owned, no attributed commits')).toBeInTheDocument()
    expect(screen.getByText('Commit attribution unavailable')).toBeInTheDocument()
    expect(screen.getByText(/owned by you, no commits attributed to your account/)).toBeInTheDocument()
  })

  it('dismisses a proposal', async () => {
    const calls = stubApi({
      '/github/proposals': () => json([proposal()]),
      '/github/proposals/p1/dismiss': () => json(proposal({ status: 'dismissed' })),
    })
    renderAt(<ProposalsSection />)

    fireEvent.click(await screen.findByRole('button', { name: 'Dismiss' }))

    await waitFor(() => expect(calls.some((c) => c.path === '/github/proposals/p1/dismiss')).toBe(true))
  })

  it('shows why adding failed and leaves the proposal in place', async () => {
    stubApi({
      '/github/proposals': () => json([proposal()]),
      '/github/proposals/p1/accept': () => json({ detail: 'This proposal was already accepted.' }, 409),
    })
    renderAt(<ProposalsSection />)

    fireEvent.change(await screen.findByLabelText('Level'), { target: { value: 'expert' } })
    fireEvent.click(screen.getByRole('button', { name: 'Add to my profile' }))

    expect(await screen.findByText("Couldn't add it")).toBeInTheDocument()
    expect(screen.getByText('This proposal was already accepted.')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add to my profile' })).toBeInTheDocument()
  })

  it('keeps decided proposals out of the way, without buttons', async () => {
    stubApi({
      '/github/proposals': () =>
        json([
          proposal({ id: 'p1' }),
          proposal({ id: 'p2', skill_name: 'HTML', status: 'accepted' }),
          proposal({ id: 'p3', skill_name: 'CSS', status: 'dismissed' }),
        ]),
    })
    renderAt(<ProposalsSection />)

    expect(await screen.findByText('Already decided (2)')).toBeInTheDocument()
    const decided = screen.getByRole('list', { name: 'Skills you already decided on' })
    expect(within(decided).getByText('Added to your profile')).toBeInTheDocument()
    expect(within(decided).getByText('Dismissed')).toBeInTheDocument()
    expect(within(decided).queryByRole('button')).not.toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Add to my profile' })).toHaveLength(1)
  })

  it('explains what to do before any sync, and what an empty result means after one', async () => {
    stubApi({})
    const first = renderAt(<ProposalsSection />)
    expect(await screen.findByText(/Sync your repositories to see which skills/)).toBeInTheDocument()
    first.unmount()

    stubApi({ '/github/sync': () => json([RUN]) })
    renderAt(<ProposalsSection />)
    expect(await screen.findByText(/Nothing waiting for a decision/)).toBeInTheDocument()
  })

  it('lists what was left out of proposals and why', async () => {
    stubApi({
      '/github/sync': () =>
        json([
          {
            ...RUN,
            skipped: [
              { subject: 'plant-disease-classifier: Python', reason: 'Only 1.4 KB, under the 5.0 KB needed.' },
              { subject: 'upstream', reason: "A fork of someone else's project." },
            ],
          },
        ]),
    })
    renderAt(<ProposalsSection />)

    expect(await screen.findByText('Not proposed, and why (2)')).toBeInTheDocument()
    expect(screen.getByText(/Only 1.4 KB, under the 5.0 KB needed/)).toBeInTheDocument()
  })

  it('shows an error with a retry when proposals cannot be loaded', async () => {
    stubApi({ '/github/proposals': () => json({ detail: 'boom' }, 500) })
    renderAt(<ProposalsSection />)

    expect(await screen.findByRole('button', { name: 'Try again' })).toBeInTheDocument()
  })
})

describe('GithubPage when connected', () => {
  it('shows the sync, the skills and the repositories together', async () => {
    stubApi({
      '/github/connection': () => json(CONNECTION),
      '/github/sync': () => json([RUN]),
      '/github/proposals': () => json([proposal()]),
      '/github/repos': () => json([repo()]),
    })
    renderAt(<GithubPage />)

    expect(await screen.findByText('Skills your repositories evidence')).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Repositories' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Sync now' })).toBeInTheDocument()
  })

  it('shows none of it after a disconnect', async () => {
    stubApi({ '/github/connection': () => json({ ...CONNECTION, status: 'disconnected' }) })
    renderAt(<GithubPage />)

    expect(await screen.findByRole('button', { name: 'Reconnect GitHub' })).toBeInTheDocument()
    expect(screen.queryByText('Skills your repositories evidence')).not.toBeInTheDocument()
  })
})

describe('disconnecting with the synced data', () => {
  it('offers to keep or delete it, and says accepted skills stay either way', async () => {
    const calls = stubApi({
      '/github/connection': (init) =>
        init?.method === 'DELETE'
          ? json({ connection: { ...CONNECTION, status: 'disconnected' }, revoked_at_github: true })
          : json(CONNECTION),
    })
    renderAt(<GithubPage />)

    fireEvent.click(await screen.findByRole('button', { name: 'Disconnect' }))
    const dialog = await screen.findByRole('dialog')
    expect(within(dialog).getByText(/Skills you already added to your profile are yours/)).toBeInTheDocument()
    fireEvent.click(within(dialog).getByRole('button', { name: /Delete the synced data/ }))
    fireEvent.click(within(dialog).getByRole('button', { name: 'Disconnect' }))

    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true))
    expect(calls.find((c) => c.method === 'DELETE')?.url).toContain('purge_data=true')
  })

  it('keeps the data by default', async () => {
    const calls = stubApi({
      '/github/connection': (init) =>
        init?.method === 'DELETE'
          ? json({ connection: { ...CONNECTION, status: 'disconnected' }, revoked_at_github: true })
          : json(CONNECTION),
    })
    renderAt(<GithubPage />)

    fireEvent.click(await screen.findByRole('button', { name: 'Disconnect' }))
    const dialog = await screen.findByRole('dialog')
    fireEvent.click(within(dialog).getByRole('button', { name: 'Disconnect' }))

    await waitFor(() => expect(calls.some((c) => c.method === 'DELETE')).toBe(true))
    expect(calls.find((c) => c.method === 'DELETE')?.url).toContain('purge_data=false')
  })
})
