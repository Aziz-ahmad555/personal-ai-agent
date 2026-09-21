import type { GithubContribution, GithubRepo } from '@/lib/api'

export function kb(bytes: number): string {
  return `${(bytes / 1000).toFixed(1)} KB`
}

export function shortDate(iso: string | null): string {
  return iso ? iso.slice(0, 10) : 'unknown'
}

/** One line of evidence, using only recorded facts. */
export function describeContribution(c: GithubContribution): string {
  const what =
    c.via === 'language'
      ? `${kb(c.bytes ?? 0)} of code`
      : c.via === 'dependency'
        ? `declared in ${c.source_file}`
        : `has a ${c.source_file}`
  if (c.attribution === 'attributed') {
    const commits = `${c.commits} ${c.commits === 1 ? 'commit' : 'commits'} by you`
    return `${what} · ${commits}${c.last_commit_at ? `, last ${shortDate(c.last_commit_at)}` : ''}`
  }
  if (c.attribution === 'ownership_only') {
    return `${what} · owned by you, no commits attributed to your account`
  }
  return `${what} · commit attribution unavailable`
}

/** What the sync knows about the commits in a repo, without ever turning "unknown" into zero. */
export function describeCommits(repo: GithubRepo): string {
  if (repo.authored_commits === null) return 'Commits not read'
  if (repo.authored_commits === 0) return 'No commits attributed to your account'
  return `${repo.authored_commits} ${repo.authored_commits === 1 ? 'commit' : 'commits'} by you`
}

/** Why a repo isn't used as evidence, or null if it is. */
export function exclusionReason(repo: GithubRepo): string | null {
  if (repo.is_fork) return "A fork, so it isn't counted as your work."
  if (repo.is_archived) return "Archived, so it isn't counted as current evidence."
  if (!repo.details_fetched) return "Its details couldn't be read yet."
  return null
}
