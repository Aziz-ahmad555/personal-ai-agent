import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/layout/error-state'
import { EventCard } from '@/features/calendar/EventCard'
import { useCalendarEvents, useCalendarSyncRuns } from '@/features/calendar/hooks'

export function EventsList() {
  const { data, isLoading, isError, error, refetch } = useCalendarEvents()
  const { data: runs } = useCalendarSyncRuns()
  const synced = Boolean(runs?.some((run) => run.status === 'completed'))

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Events</CardTitle>
        <CardDescription>
          Interview and deadline are guesses from the title and description, and shown with the
          evidence. Nothing here is sent anywhere, and you can correct any of it.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading && <Skeleton className="h-24 w-full" />}
        {isError && (
          <ErrorState
            message={error instanceof Error ? error.message : 'Failed to load events'}
            onRetry={() => refetch()}
          />
        )}
        {data && data.length === 0 && (
          <p className="text-sm text-muted-foreground">
            {synced
              ? 'No events in the synced window (about a month back, six months ahead).'
              : 'Nothing yet. Sync your calendar to see events here.'}
          </p>
        )}
        {data && data.length > 0 && (
          <ul className="space-y-2" aria-label="Calendar events">
            {data.map((event) => (
              <EventCard key={event.id} event={event} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  )
}
