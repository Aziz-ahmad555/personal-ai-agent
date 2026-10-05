import { CalendarDays } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorState } from '@/components/layout/error-state'
import { useStartCalendarOAuth } from '@/features/calendar/hooks'
import { isDemoMode } from '@/lib/demo'

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
                <li>
                  Spot events that look like interviews or application deadlines, from keywords in
                  the title and description, and link one to a tracked application when an
                  attendee&apos;s email domain or the company name matches. You can always correct or
                  clear its guess.
                </li>
              </ul>
            </div>
            <div>
              <p className="font-medium text-foreground">It cannot</p>
              <ul className="list-disc space-y-1 pl-4">
                <li>Create, edit, or delete anything on your calendar.</li>
                <li>Read any calendar other than your primary one.</li>
                <li>Act on its own: it reads only when you click Sync now.</li>
              </ul>
            </div>
            <p>You can disconnect at any time. That revokes the token on Google and clears it here.</p>
            <p className="rounded-md bg-muted p-3">
              <span className="font-medium text-foreground">Interview practice</span> lives in Career,
              per job: generated questions, a verdict for each answer, and written feedback.
            </p>
          </div>
        </div>

        {start.isError && (
          <ErrorState
            title="Couldn't start the connection"
            message={start.error instanceof Error ? start.error.message : 'Failed to start connection'}
          />
        )}

        <Button onClick={() => start.mutate()} disabled={start.isPending || isDemoMode}>
          <CalendarDays className="h-4 w-4" />
          {start.isPending ? 'Redirecting…' : label}
        </Button>
        {isDemoMode && (
          <p className="text-sm text-muted-foreground">
            Not available in this demo — real account connections are disabled.
          </p>
        )}
      </CardContent>
    </Card>
  )
}
