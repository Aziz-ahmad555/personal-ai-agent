import { useEffect, useRef } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { Loader2, RefreshCw } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorState } from '@/components/layout/error-state'
import type { CalendarConnection } from '@/lib/api'
import { useCalendarSyncRuns, useStartCalendarSync } from '@/features/calendar/hooks'

const ACTIVE = new Set(['pending', 'running'])

export function SyncCard({ connection }: { connection: CalendarConnection }) {
  const { data: runs } = useCalendarSyncRuns()
  const start = useStartCalendarSync()
  const queryClient = useQueryClient()
  const previous = useRef<string | null>(null)

  const latest = runs?.[0]
  const active = latest ? ACTIVE.has(latest.status) : false
  const lastDone = runs?.find((run) => run.status === 'completed')

  // When a run finishes, the events list is stale until refetched.
  useEffect(() => {
    if (!latest) return
    const wasActive = previous.current !== null && ACTIVE.has(previous.current)
    previous.current = latest.status
    if (wasActive && !ACTIVE.has(latest.status)) {
      queryClient.invalidateQueries({ queryKey: ['calendar', 'events'] })
    }
  }, [latest, queryClient])

  const canSync = connection.status === 'connected'

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
        <CardTitle className="text-base">Sync</CardTitle>
        <Button onClick={() => start.mutate()} disabled={!canSync || active || start.isPending}>
          {active ? <Loader2 className="h-4 w-4 animate-spin" /> : <RefreshCw className="h-4 w-4" />}
          {active ? 'Syncing…' : 'Sync now'}
        </Button>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        <p className="text-muted-foreground">
          Reads events on your primary calendar (about a month back, six months ahead) and
          classifies each one. Nothing is written to Google, and nothing here changes an
          application unless you link one yourself.
        </p>

        {!canSync && <p className="text-muted-foreground">Reconnect Calendar above before syncing.</p>}

        {start.isError && (
          <ErrorState
            title="Couldn't start the sync"
            message={start.error instanceof Error ? start.error.message : 'Failed to start the sync'}
          />
        )}

        {latest?.status === 'failed' && (
          <ErrorState title="The last sync failed" message={latest.error ?? 'Unknown error'} />
        )}

        {lastDone && (
          <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5">
            <dt className="text-muted-foreground">Last synced</dt>
            <dd>{new Date(lastDone.completed_at ?? lastDone.started_at).toLocaleString()}</dd>
            <dt className="text-muted-foreground">Read</dt>
            <dd>
              {lastDone.events_seen} {lastDone.events_seen === 1 ? 'event' : 'events'} (
              {lastDone.events_stored} new)
            </dd>
          </dl>
        )}

        {lastDone && lastDone.warnings.length > 0 && (
          <Alert>
            <AlertTitle>Worth knowing</AlertTitle>
            <AlertDescription>
              <ul className="list-disc space-y-1 pl-4">
                {lastDone.warnings.map((warning) => (
                  <li key={warning}>{warning}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}

        {!runs?.length && !start.isPending && (
          <p className="rounded-md border border-dashed border-border p-4 text-muted-foreground">
            Nothing synced yet. Click &ldquo;Sync now&rdquo; to read your calendar.
          </p>
        )}
      </CardContent>
    </Card>
  )
}
