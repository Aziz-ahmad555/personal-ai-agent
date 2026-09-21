import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/layout/empty-state'
import { ErrorState } from '@/components/layout/error-state'
import { History } from 'lucide-react'
import { SyncRunStatusBadge } from '@/features/gmail/badges'
import { useSyncRuns } from '@/features/gmail/hooks'

export function SyncHistoryList() {
  const { data: runs, isLoading, isError, error, refetch } = useSyncRuns()

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Sync history</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-12 w-full" />
            <Skeleton className="h-12 w-full" />
          </div>
        )}
        {isError && (
          <ErrorState
            message={error instanceof Error ? error.message : 'Failed to load sync history'}
            onRetry={() => refetch()}
          />
        )}
        {runs?.length === 0 && (
          <EmptyState
            icon={<History className="h-6 w-6" />}
            title="No syncs yet"
            description="Click “Sync now” above to pull in your mail."
          />
        )}
        <ul className="space-y-2">
          {runs?.map((run) => (
            <li
              key={run.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border px-3 py-2 text-sm"
            >
              <div className="flex items-center gap-2">
                <SyncRunStatusBadge status={run.status} />
                <span className="capitalize text-muted-foreground">{run.sync_type}</span>
              </div>
              <div className="flex items-center gap-3 text-xs text-muted-foreground">
                <span>
                  {run.messages_stored} / {run.messages_fetched} stored
                </span>
                <span>{new Date(run.started_at).toLocaleString()}</span>
              </div>
              {run.error && <p className="w-full text-xs text-destructive">{run.error}</p>}
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
