import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { Card, CardContent } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/layout/error-state'
import { ConnectPrompt } from '@/features/github/ConnectPrompt'
import { ConnectionCard } from '@/features/github/ConnectionCard'
import { ProposalsSection } from '@/features/github/ProposalsSection'
import { RepoList } from '@/features/github/RepoList'
import { SyncCard } from '@/features/github/SyncCard'
import { useGithubConnection } from '@/features/github/hooks'

export function GithubPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const { data: connection, isLoading, isError, error, refetch } = useGithubConnection()

  // The OAuth redirect params are one-shot. Read them once, keep the message on screen, and
  // clear them from the URL so a reload doesn't show a stale error.
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

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <h1 className="text-xl font-semibold">GitHub</h1>

      {oauthError && <ErrorState title="Couldn't connect GitHub" message={oauthError} />}

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
              message={error instanceof Error ? error.message : 'Failed to load the GitHub connection'}
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
          <SyncCard connection={connection} />
          <ProposalsSection />
          <RepoList />
        </>
      )}
    </div>
  )
}
