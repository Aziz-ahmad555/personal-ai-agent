import { CalendarDays } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorState } from '@/components/layout/error-state'
import { useStartCalendarOAuth } from '@/features/calendar/hooks'

export function ConnectPrompt({ reconnect = false }: { reconnect?: boolean }) {
  const start = useStartCalendarOAuth()
  const label = reconnect ? 'Reconnect Calendar' : 'Connect Calendar (read-only)'

  return (
    <Card>
      <CardHeader>
        <CardTitle>{reconnect ? 'Reconnect Calendar' : 'Connect Calendar'}</CardTitle>
        <CardDescription>Read-only, and only what&apos;s described below. Nothing else.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-start gap-3 rounded-md border border-border p-4 text-sm">
          <CalendarDays className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
          <div className="space-y-3 text-muted-foreground">
            <p>
              You sign in with Google and grant read-only access to your{' '}
              <span className="text-foreground">primary calendar</span> only. This is a separate
              grant from Gmail, if you&apos;ve connected that — disconnecting one never affects the
              other.
            </p>
            <div>
              <p className="font-medium text-foreground">It can</p>
              <ul className="list-disc space-y-1 pl-4">
                <li>
                  Read event titles, times, descriptions and attendees on your primary calendar,
                  once you click Sync now.
                </li>
              </ul>
            </div>
            <div>
              <p className="font-medium text-foreground">It cannot</p>
              <ul className="list-disc space-y-1 pl-4">
                <li>Create, edit, or delete anything on your calendar.</li>
                <li>Read any calendar other than your primary one.</li>
                <li>Act on its own: connecting alone reads nothing.</li>
              </ul>
            </div>
            <p>You can disconnect at any time. That revokes the token on Google and clears it here.</p>
            <p className="rounded-md bg-muted p-3">
              <span className="font-medium text-foreground">Not built yet:</span> reading events and
              spotting interviews or deadlines. For now, connecting only links your account.
            </p>
          </div>
        </div>

        {start.isError && (
          <ErrorState
            title="Couldn't start the connection"
            message={start.error instanceof Error ? start.error.message : 'Failed to start connection'}
          />
        )}

        <Button onClick={() => start.mutate()} disabled={start.isPending}>
          <CalendarDays className="h-4 w-4" />
          {start.isPending ? 'Redirecting…' : label}
        </Button>
      </CardContent>
    </Card>
  )
}
