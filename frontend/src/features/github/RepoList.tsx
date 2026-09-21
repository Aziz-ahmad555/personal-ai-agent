import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/layout/error-state'
import type { GithubRepo } from '@/lib/api'
import { describeCommits, exclusionReason, shortDate } from '@/features/github/format'
import { useGithubRepos } from '@/features/github/hooks'

export function RepoRow({ repo }: { repo: GithubRepo }) {
  const excluded = exclusionReason(repo)
  return (
    <li className="space-y-1 rounded-md border border-border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <a
          href={repo.html_url}
          target="_blank"
          rel="noreferrer"
          className="font-medium underline-offset-4 hover:underline"
        >
          {repo.name}
        </a>
        {repo.is_fork && <Badge variant="outline">Fork</Badge>}
        {repo.is_archived && <Badge variant="outline">Archived</Badge>}
        {repo.primary_language && <Badge variant="secondary">{repo.primary_language}</Badge>}
      </div>
      {repo.description && <p className="text-muted-foreground">{repo.description}</p>}
      <p className="text-xs text-muted-foreground">
        {describeCommits(repo)} · last push {shortDate(repo.pushed_at)}
      </p>
      {excluded && <p className="text-xs text-muted-foreground">Not used as evidence: {excluded}</p>}
    </li>
  )
}

export function RepoList() {
  const { data, isLoading, isError, error, refetch } = useGithubRepos()

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Repositories</CardTitle>
      </CardHeader>
      <CardContent>
        {isLoading && <Skeleton className="h-24 w-full" />}
        {isError && (
          <ErrorState
            message={error instanceof Error ? error.message : 'Failed to load repositories'}
            onRetry={() => refetch()}
          />
        )}
        {data && data.length === 0 && (
          <p className="text-sm text-muted-foreground">
            No repositories yet. They appear here after a sync.
          </p>
        )}
        {data && data.length > 0 && (
          <ul className="space-y-2" aria-label="Your public repositories">
            {data.map((repo) => (
              <RepoRow key={repo.id} repo={repo} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
