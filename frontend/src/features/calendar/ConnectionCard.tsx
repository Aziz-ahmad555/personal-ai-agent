import { useState } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorState } from '@/components/layout/error-state'
import type { CalendarConnection } from '@/lib/api'
import { ConnectionStatusBadge } from '@/features/gmail/badges'
import { DisconnectDialog } from '@/features/calendar/DisconnectDialog'
import { useStartCalendarOAuth } from '@/features/calendar/hooks'

export function ConnectionCard({ connection }: { connection: CalendarConnection }) {
  const start = useStartCalendarOAuth()
  const [disconnectOpen, setDisconnectOpen] = useState(false)
  const needsReauth = connection.status === 'needs_reauth'

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Calendar</CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 text-sm">
          <dt className="text-muted-foreground">Account</dt>
          <dd>{connection.google_email}</dd>
          <dt className="text-muted-foreground">Status</dt>
          <dd>
            <ConnectionStatusBadge status={connection.status} />
          </dd>
          <dt className="text-muted-foreground">Connected since</dt>
          <dd>{new Date(connection.created_at).toLocaleString()}</dd>
        </dl>

        {needsReauth && (
          <ErrorState
            title="Reconnect needed"
            message={
              connection.last_error
                ? `${connection.last_error} Reconnect to keep using Calendar.`
                : 'Calendar access expired. Reconnect to keep using it.'
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
