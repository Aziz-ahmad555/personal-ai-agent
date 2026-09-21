import type { ReactElement } from 'react'
import { MemoryRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render } from '@testing-library/react'
import { vi } from 'vitest'
import type {
  GithubCheck,
  GithubConnection,
  GithubProposal,
  GithubReadiness,
  GithubRepo,
  GithubRepoReview,
  GithubSyncRun,
} from '@/lib/api'

export const CONNECTION: GithubConnection = {
  id: 'c1',
  github_login: 'aziz-ahmad555',
  status: 'connected',
  installations: [],
  last_error: null,
  created_at: '2026-09-22T10:00:00Z',
}

export function json(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

export const RUN: GithubSyncRun = {
  id: 'r1',
  status: 'completed',
  started_at: '2026-09-22T10:00:00Z',
  completed_at: '2026-09-22T10:00:05Z',
  repos_seen: 5,
  repos_detailed: 3,
  requests_made: 16,
  activity: {
    events_seen: 67,
    push_events: 65,
    active_days: 11,
    first_day: '2026-08-27',
    last_day: '2026-09-12',
    note: 'GitHub only exposes about the last 90 days of public events.',
    as_of: '2026-09-22T10:00:05Z',
  },
  warnings: [],
  skipped: [],
  error: null,
}

export function repo(overrides: Partial<GithubRepo> = {}): GithubRepo {
  return {
    id: 'g1',
    name: 'AegisAI',
    full_name: 'aziz-ahmad555/AegisAI',
    html_url: 'https://github.com/aziz-ahmad555/AegisAI',
    description: 'Emergency detection platform',
    is_fork: false,
    is_archived: false,
    primary_language: 'Python',
    topics: [],
    stars: 0,
    forks: 0,
    license_spdx: null,
    pushed_at: '2026-09-12T10:00:00Z',
    details_fetched: true,
    languages: { Python: 114846 },
    authored_commits: 43,
    first_commit_at: '2026-03-01T00:00:00Z',
    last_commit_at: '2026-09-12T10:00:00Z',
    dependencies: [],
    synced_at: '2026-09-22T10:00:05Z',
    ...overrides,
  }
}

export function proposal(overrides: Partial<GithubProposal> = {}): GithubProposal {
  return {
    id: 'p1',
    skill_name: 'Python',
    kind: 'language',
    attribution: 'attributed',
    contributions: [
      {
        repo: 'AegisAI',
        repo_url: 'https://github.com/aziz-ahmad555/AegisAI',
        via: 'language',
        source_url: 'https://github.com/aziz-ahmad555/AegisAI',
        source_file: null,
        bytes: 114846,
        commits: 43,
        last_commit_at: '2026-09-12T10:00:00Z',
        attribution: 'attributed',
      },
    ],
    existing_skill_name: null,
    existing_level: null,
    requires_level: true,
    evidence_preview:
      'GitHub (@aziz-ahmad555): Python — AegisAI (114.8 KB of Python; 43 commits by this account, last 2026-09-12).',
    status: 'pending',
    decided_at: null,
    created_at: '2026-09-22T10:00:05Z',
    ...overrides,
  }
}

export function check(overrides: Partial<GithubCheck> = {}): GithubCheck {
  return {
    key: 'license',
    label: 'Has a license',
    status: 'fail',
    detail: 'No license, so nobody is allowed to reuse the code.',
    evidence_url: null,
    fix: 'Add a LICENSE file.',
    ...overrides,
  }
}

export function repoReview(overrides: Partial<GithubRepoReview> = {}): GithubRepoReview {
  return {
    name: 'AegisAI',
    html_url: 'https://github.com/aziz-ahmad555/AegisAI',
    reviewed: true,
    reason: null,
    checks: [
      check({ key: 'description', label: 'Has a description', status: 'pass', detail: '“A platform”', fix: null }),
      check({ key: 'readme', label: 'Has a README', status: 'fail', detail: 'No README in the repository root.', fix: 'Add a README.md.' }),
      check({ key: 'tests', label: 'Has automated tests', status: 'unknown', detail: 'Sync again to include this.', fix: null }),
      check({
        key: 'junk',
        label: 'No junk files committed',
        status: 'warn',
        detail: 'Committed: .yolov8n.part.',
        evidence_url: 'https://github.com/aziz-ahmad555/AegisAI/blob/main/.yolov8n.part',
        fix: 'Delete these files and add them to .gitignore.',
      }),
    ],
    passed: 1,
    total: 4,
    unknown: 1,
    ...overrides,
  }
}

export function readiness(overrides: Partial<GithubReadiness> = {}): GithubReadiness {
  return {
    synced: true,
    as_of: '2026-09-22T10:00:05Z',
    needs_resync: false,
    repos: [repoReview()],
    profile: [
      check({ key: 'bio', label: 'Bio is set', status: 'pass', detail: '“ML engineer”', fix: null }),
      check({ key: 'profile_readme', label: 'Has a profile README', status: 'warn', detail: 'No public repository named you.', fix: 'Create a profile README repo.' }),
    ],
    fixes: [
      {
        repo: 'AegisAI',
        repo_url: 'https://github.com/aziz-ahmad555/AegisAI',
        check_key: 'readme',
        label: 'Has a README',
        status: 'fail',
        detail: 'No README in the repository root.',
        fix: 'Add a README.md.',
        evidence_url: null,
      },
      {
        repo: null,
        repo_url: null,
        check_key: 'profile_readme',
        label: 'Has a profile README',
        status: 'warn',
        detail: 'No public repository named you.',
        fix: 'Create a profile README repo.',
        evidence_url: null,
      },
    ],
    limitations: ['Pinned repositories can’t be read with this access.'],
    ...overrides,
  }
}

type Handler = (init?: RequestInit) => Response

const EMPTY_DATA: Record<string, Handler> = {
  '/github/sync': () => json([]),
  '/github/proposals': () => json([]),
  '/github/repos': () => json([]),
  '/github/readiness': () => json({ synced: false, as_of: null, needs_resync: false, repos: [], profile: [], fixes: [], limitations: [] }),
}

/** Routes by path (query ignored). Anything unlisted throws, so a stray request fails loudly. */
export function stubApi(routes: Record<string, Handler>) {
  const merged = { ...EMPTY_DATA, ...routes }
  const calls: { path: string; method: string; body: unknown; url: string }[] = []
  vi.stubGlobal(
    'fetch',
    vi.fn(async (url: string, init?: RequestInit) => {
      const pathOnly = url.split('?')[0]
      const path = Object.keys(merged).find((key) => pathOnly.endsWith(key))
      calls.push({
        path: path ?? url,
        method: init?.method ?? 'GET',
        body: init?.body ? JSON.parse(String(init.body)) : undefined,
        url,
      })
      if (!path) throw new Error(`Unexpected request: ${url}`)
      return merged[path](init)
    })
  )
  return calls
}

export function renderAt(ui: ReactElement, url = '/github') {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } })
  return render(
    <QueryClientProvider client={client}>
      <MemoryRouter initialEntries={[url]}>{ui}</MemoryRouter>
    </QueryClientProvider>
  )
}
