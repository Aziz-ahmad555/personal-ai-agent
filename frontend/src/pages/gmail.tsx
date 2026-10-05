import { useEffect, useRef, useState } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { useSearchParams } from 'react-router-dom'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/layout/error-state'
import { ConnectPrompt } from '@/features/gmail/ConnectPrompt'
import { ConnectionCard } from '@/features/gmail/ConnectionCard'
import { SyncHistoryList } from '@/features/gmail/SyncHistoryList'
import { MessagesList } from '@/features/gmail/MessagesList'
import { useGmailConnection, useSyncRuns } from '@/features/gmail/hooks'

export function GmailPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const queryClient = useQueryClient()
  const { data: connection, isLoading, isError, error, refetch } = useGmailConnection()
  const { data: syncRuns } = useSyncRuns()
  const lastKnownRunStatus = useRef<string | null>(null)

  // Read the one-shot OAuth redirect params once so the error stays on screen after they're
  // cleared from the URL, and make sure the card reflects a just-completed connect.
  const [landing] = useState(() => ({
    error: searchParams.get('error'),
    connected: searchParams.get('connected') === '1',
  }))
  const oauthError = landing.error

  useEffect(() => {
    if (landing.error || landing.connected) {
      if (landing.connected) refetch()
      setSearchParams({}, { replace: true })
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  // When the latest sync run finishes, the connection's last_synced_at and the message
  // list are both stale until refetched — poll-driven updates only cover the run itself.
  useEffect(() => {
    const latest = syncRuns?.[0]
    if (!latest) return
    if (lastKnownRunStatus.current === latest.status) return
    const wasActive = lastKnownRunStatus.current === 'pending' || lastKnownRunStatus.current === 'running'
    lastKnownRunStatus.current = latest.status
    if (wasActive && (latest.status === 'completed' || latest.status === 'failed')) {
      queryClient.invalidateQueries({ queryKey: ['gmail', 'connection'] })
      queryClient.invalidateQueries({ queryKey: ['gmail', 'messages'] })
    }
  }, [syncRuns, queryClient])

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      {oauthError && (
        <ErrorState title="Couldn't connect Gmail" message={decodeURIComponent(oauthError)} />
      )}

      {isLoading && (
        <Card>
          <CardContent className="space-y-3 pt-6">
            <Skeleton className="h-6 w-1/3" />
            <Skeleton className="h-20 w-full" />
          </CardContent>
        </Card>
      )}

      {isError && (
        <Card>
          <CardContent className="pt-6">
            <ErrorState
              message={error instanceof Error ? error.message : 'Failed to load Gmail connection'}
              onRetry={() => refetch()}
            />
          </CardContent>
        </Card>
      )}

      {!isLoading && !isError && connection === null && <ConnectPrompt />}

      {!isLoading && !isError && connection?.status === 'disconnected' && <ConnectPrompt reconnect />}

      {!isLoading && !isError && connection && connection.status !== 'disconnected' && (
        <>
          <ConnectionCard connection={connection} />
          <SyncHistoryList />
          <MessagesList />
        </>
      )}
    </div>
  )
}
