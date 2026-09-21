import { Loader2, ScrollText } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/layout/empty-state'
import { ErrorState } from '@/components/layout/error-state'
import { cn } from '@/lib/utils'
import type { ResearchQueryStatus } from '@/lib/api'
import { useResearchQueries } from '@/features/research/hooks'

function StatusPip({ status }: { status: ResearchQueryStatus }) {
  if (status === 'pending' || status === 'running') {
    return (
      <Badge variant="secondary" className="gap-1">
        <Loader2 className="h-3 w-3 animate-spin" /> {status === 'pending' ? 'Queued' : 'Running'}
      </Badge>
    )
  }
  if (status === 'failed') {
    return (
      <Badge variant="outline" className="border-destructive/50 text-destructive">
        Failed
      </Badge>
    )
  }
  return <Badge variant="outline">Done</Badge>
}

interface QueryHistoryListProps {
  selectedId: string | null
  onSelect: (id: string) => void
}

export function QueryHistoryList({ selectedId, onSelect }: QueryHistoryListProps) {
  const { data: queries, isLoading, isError, error, refetch } = useResearchQueries()

  return (
    <Card className="h-fit">
      <CardHeader>
        <CardTitle className="text-base">History</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-14 w-full" />
            <Skeleton className="h-14 w-full" />
          </div>
        )}
        {isError && (
          <ErrorState
            message={error instanceof Error ? error.message : 'Failed to load history'}
            onRetry={() => refetch()}
          />
        )}
        {queries?.length === 0 && (
          <EmptyState
            icon={<ScrollText className="h-6 w-6" />}
            title="No research yet"
            description="Run your first query above."
          />
        )}
        <ul className="space-y-2">
          {queries?.map((q) => (
            <li key={q.id}>
              <button
                type="button"
                onClick={() => onSelect(q.id)}
                className={cn(
                  'w-full rounded-md border border-border p-3 text-left text-sm transition-colors hover:bg-accent',
                  selectedId === q.id && 'border-ring bg-accent'
                )}
              >
                <p className="line-clamp-2 font-medium">{q.query_text}</p>
                <div className="mt-2 flex items-center justify-between gap-2">
                  <StatusPip status={q.status} />
                  <span className="text-xs text-muted-foreground">
                    {new Date(q.created_at).toLocaleDateString()}
                  </span>
                </div>
              </button>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
