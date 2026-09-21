import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorState } from '@/components/layout/error-state'
import type { GithubConnection } from '@/lib/api'
import { ConnectionStatusBadge } from '@/features/gmail/badges'
import { DisconnectDialog } from '@/features/github/DisconnectDialog'
import { useStartGithubOAuth } from '@/features/github/hooks'
import { accessSummary } from '@/features/github/access'

export function ConnectionCard({ connection }: { connection: GithubConnection }) {
  const start = useStartGithubOAuth()
  const [disconnectOpen, setDisconnectOpen] = useState(false)
  const needsReauth = connection.status === 'needs_reauth'

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">GitHub</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
          <dt className="text-muted-foreground">Account</dt>
          <dd>
            <a
              href={`https://github.com/${connection.github_login}`}
              target="_blank"
              rel="noreferrer"
              className="underline-offset-4 hover:underline"
            >
              {connection.github_login}
            </a>
          </dd>
          <dt className="text-muted-foreground">Status</dt>
          <dd>
            <ConnectionStatusBadge status={connection.status} />
          </dd>
          <dt className="text-muted-foreground">Access</dt>
          <dd>{accessSummary(connection)}</dd>
          <dt className="text-muted-foreground">Connected since</dt>
          <dd>{new Date(connection.created_at).toLocaleString()}</dd>
        </dl>

        {needsReauth && (
          <ErrorState
            title="Reconnect needed"
            message={
              connection.last_error
                ? `${connection.last_error} Reconnect to keep using GitHub.`
                : 'GitHub access expired. Reconnect to keep using it.'
            }
          />
        )}

        {start.isError && (
          <ErrorState
            message={start.error instanceof Error ? start.error.message : 'Failed to start connection'}
          />
        )}

        <div className="flex flex-wrap gap-2">
          {needsReauth && (
            <Button onClick={() => start.mutate()} disabled={start.isPending}>
              {start.isPending ? 'Redirecting…' : 'Reconnect'}
            </Button>
          )}
          <Button variant="outline" onClick={() => setDisconnectOpen(true)}>
            Disconnect
          </Button>
        </div>
      </CardContent>

      <DisconnectDialog open={disconnectOpen} onOpenChange={setDisconnectOpen} />
    </Card>
  )
}
