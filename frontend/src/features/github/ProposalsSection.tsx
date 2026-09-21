import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/layout/error-state'
import { ProposalCard } from '@/features/github/ProposalCard'
import { useGithubProposals, useGithubSyncRuns } from '@/features/github/hooks'

export function ProposalsSection() {
  const { data, isLoading, isError, error, refetch } = useGithubProposals()
  const { data: runs } = useGithubSyncRuns()

  const pending = data?.filter((p) => p.status === 'pending') ?? []
  const decided = data?.filter((p) => p.status !== 'pending') ?? []
  const skipped = runs?.find((run) => run.status === 'completed')?.skipped ?? []
  const synced = Boolean(runs?.some((run) => run.status === 'completed'))

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Skills your repositories evidence</CardTitle>
        <CardDescription>
          Each one lists exactly where it comes from. Nothing is added to your profile until you say
          so. GitHub shows what you&apos;ve built, not how proficient you are, so you set the level for
          any new skill.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        {isLoading && <Skeleton className="h-32 w-full" />}
        {isError && (
          <ErrorState
            message={error instanceof Error ? error.message : 'Failed to load proposals'}
            onRetry={() => refetch()}
          />
        )}

        {data && pending.length === 0 && (
          <p className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
            {synced
              ? 'Nothing waiting for a decision. New evidence from your repositories will show up here after a sync.'
              : 'Nothing yet. Sync your repositories to see which skills they evidence.'}
          </p>
        )}

        {pending.length > 0 && (
          <ul className="space-y-3" aria-label="Skills waiting for your decision">
            {pending.map((proposal) => (
              <ProposalCard key={proposal.id} proposal={proposal} />
            ))}
          </ul>
        )}

        {decided.length > 0 && (
          <details className="rounded-md border border-border p-3">
            <summary className="cursor-pointer text-sm font-medium">
              Already decided ({decided.length})
            </summary>
            <ul className="mt-3 space-y-3" aria-label="Skills you already decided on">
              {decided.map((proposal) => (
                <ProposalCard key={proposal.id} proposal={proposal} />
              ))}
            </ul>
          </details>
        )}

        {skipped.length > 0 && (
          <details className="rounded-md border border-border p-3">
            <summary className="cursor-pointer text-sm font-medium">
              Not proposed, and why ({skipped.length})
            </summary>
            <ul className="mt-3 space-y-1.5 text-sm text-muted-foreground">
              {skipped.map((item) => (
                <li key={item.subject}>
                  <span className="font-medium text-foreground">{item.subject}</span> — {item.reason}
                </li>
              ))}
            </ul>
          </details>
        )}
      </CardContent>
    </Card>
  )
}
