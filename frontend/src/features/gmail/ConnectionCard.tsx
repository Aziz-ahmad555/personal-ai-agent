import { useState } from 'react'
import { RefreshCw } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorState } from '@/components/layout/error-state'
import type { GmailConnection } from '@/lib/api'
import { ConnectionStatusBadge } from '@/features/gmail/badges'
import { DisconnectDialog } from '@/features/gmail/DisconnectDialog'
import { useStartOAuth, useStartSync } from '@/features/gmail/hooks'
import { isDemoMode } from '@/lib/demo'

export function ConnectionCard({ connection }: { connection: GmailConnection }) {
  const startSync = useStartSync()
  const startOAuth = useStartOAuth()
  const [disconnectOpen, setDisconnectOpen] = useState(false)

  const needsReauth = connection.status === 'needs_reauth'

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Gmail</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
          <dt className="text-muted-foreground">Account</dt>
          <dd>{connection.google_email}</dd>
          <dt className="text-muted-foreground">Status</dt>
          <dd>
            <ConnectionStatusBadge status={connection.status} />
          </dd>
          <dt className="text-muted-foreground">Last synced</dt>
          <dd>
            {connection.last_synced_at ? new Date(connection.last_synced_at).toLocaleString() : 'Never'}
          </dd>
        </dl>

        {connection.last_sync_error && (
          <ErrorState title="Last sync failed" message={connection.last_sync_error} />
        )}

        {needsReauth && (
          <ErrorState
            title="Reconnect needed"
            message="Gmail access expired (this happens roughly weekly while this app is unverified with Google) — reconnect to keep syncing."
          />
        )}

        {startSync.isError && (
          <ErrorState
            message={startSync.error instanceof Error ? startSync.error.message : 'Sync failed to start'}
          />
        )}

        <div className="flex flex-wrap gap-2">
          {connection.status !== 'connected' ? (
            <Button onClick={() => startOAuth.mutate()} disabled={startOAuth.isPending || isDemoMode}>
              {startOAuth.isPending ? 'Redirecting…' : 'Reconnect'}
            </Button>
          ) : (
            <Button onClick={() => startSync.mutate()} disabled={startSync.isPending || isDemoMode}>
              <RefreshCw className="h-4 w-4" />
              {startSync.isPending ? 'Starting…' : 'Sync now'}
            </Button>
          )}
          <Button variant="outline" onClick={() => setDisconnectOpen(true)}>
            Disconnect
          </Button>
        </div>
        {isDemoMode && !needsReauth && (
          <p className="text-sm text-muted-foreground">
            Not available in this demo — this sample data doesn&apos;t sync against a real account.
          </p>
        )}
      </CardContent>

      <DisconnectDialog open={disconnectOpen} onOpenChange={setDisconnectOpen} />
    </Card>
  )
}
