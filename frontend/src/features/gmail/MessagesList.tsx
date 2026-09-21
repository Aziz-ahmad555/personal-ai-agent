import { Inbox } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/layout/empty-state'
import { ErrorState } from '@/components/layout/error-state'
import { useMessages } from '@/features/gmail/hooks'

export function MessagesList() {
  const { data: messages, isLoading, isError, error, refetch } = useMessages(true)

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Recent mail{messages ? ` (${messages.length})` : ''}</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        )}
        {isError && (
          <ErrorState
            message={error instanceof Error ? error.message : 'Failed to load messages'}
            onRetry={() => refetch()}
          />
        )}
        {messages?.length === 0 && (
          <EmptyState
            icon={<Inbox className="h-6 w-6" />}
            title="No mail synced yet"
            description="Run a sync to pull in messages from the last few months."
          />
        )}
        <ul className="space-y-2">
          {messages?.map((message) => (
            <li key={message.id} className="rounded-md border border-border p-3 text-sm">
              <div className="flex items-start justify-between gap-2">
                <p className="truncate font-medium">{message.subject || '(no subject)'}</p>
                <span className="shrink-0 text-xs text-muted-foreground">
                  {message.date ? new Date(message.date).toLocaleDateString() : ''}
                </span>
              </div>
              <p className="truncate text-xs text-muted-foreground">
                {message.from_address || 'Unknown sender'}
              </p>
              <p className="mt-1 truncate text-muted-foreground">{message.snippet}</p>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
