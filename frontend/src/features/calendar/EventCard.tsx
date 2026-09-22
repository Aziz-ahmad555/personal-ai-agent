import { useState } from 'react'
import { Pencil } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/select'
import { ErrorState } from '@/components/layout/error-state'
import type { CalendarEvent, CalendarEventKind } from '@/lib/api'
import { useApplications } from '@/features/applications/hooks'
import { useClassifyEvent } from '@/features/calendar/hooks'

const KIND_LABEL: Record<CalendarEventKind, string> = {
  interview: 'Interview',
  deadline: 'Deadline',
  other: 'Other',
}

const KIND_VARIANT: Record<CalendarEventKind, 'default' | 'outline'> = {
  interview: 'default',
  deadline: 'default',
  other: 'outline',
}

function formatWhen(event: CalendarEvent): string {
  if (!event.start_at) return 'No time set'
  const start = new Date(event.start_at)
  if (event.is_all_day) {
    return start.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
  }
  const date = start.toLocaleDateString(undefined, { weekday: 'short', month: 'short', day: 'numeric' })
  const time = start.toLocaleTimeString(undefined, { hour: 'numeric', minute: '2-digit' })
  return `${date} · ${time}`
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong'
}

export function EventCard({ event }: { event: CalendarEvent }) {
  const classify = useClassifyEvent()
  const { data: applications } = useApplications()
  const [editing, setEditing] = useState(false)
  const [kind, setKind] = useState<CalendarEventKind>(event.kind)
  const [applicationId, setApplicationId] = useState(event.application?.id ?? '')

  function startEditing() {
    setKind(event.kind)
    setApplicationId(event.application?.id ?? '')
    setEditing(true)
  }

  function save() {
    classify.mutate(
      { id: event.id, kind, applicationId: applicationId || null },
      { onSuccess: () => setEditing(false) }
    )
  }

  return (
    <li className="space-y-2 rounded-md border border-border p-4 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium">
            {event.html_link ? (
              <a
                href={event.html_link}
                target="_blank"
                rel="noreferrer"
                className="underline-offset-4 hover:underline"
              >
                {event.summary || 'Untitled event'}
              </a>
            ) : (
              event.summary || 'Untitled event'
            )}
          </p>
          <p className="text-muted-foreground">
            {formatWhen(event)}
            {event.location ? ` · ${event.location}` : ''}
          </p>
        </div>
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
          <Badge variant={KIND_VARIANT[event.kind]}>{KIND_LABEL[event.kind]}</Badge>
          {event.user_confirmed && <Badge variant="outline">Set by you</Badge>}
        </div>
      </div>

      {event.match_reason && !event.user_confirmed && (
        <p className="text-xs text-muted-foreground">
          Matched on the phrase &ldquo;{event.match_reason}&rdquo;.
        </p>
      )}

      {event.application && (
        <p className="text-xs text-muted-foreground">
          Linked to <span className="text-foreground">{event.application.title || 'an application'}</span>
          {event.application.company_name ? ` at ${event.application.company_name}` : ''}
          {event.application_match_reason ? ` — ${event.application_match_reason}` : ''}
        </p>
      )}

      {!editing ? (
        <Button size="sm" variant="outline" onClick={startEditing}>
          <Pencil className="h-3.5 w-3.5" />
          {event.user_confirmed || event.application ? 'Change' : 'Not right? Change it'}
        </Button>
      ) : (
        <div className="space-y-2 border-t border-border pt-3">
          <div className="flex flex-wrap items-center gap-2">
            <label className="text-muted-foreground" htmlFor={`kind-${event.id}`}>
              Type
            </label>
            <div className="w-40">
              <Select
                id={`kind-${event.id}`}
                value={kind}
                onChange={(e) => setKind(e.target.value as CalendarEventKind)}
              >
                <option value="interview">Interview</option>
                <option value="deadline">Deadline</option>
                <option value="other">Other</option>
              </Select>
            </div>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <label className="text-muted-foreground" htmlFor={`app-${event.id}`}>
              Linked application
            </label>
            <div className="w-72">
              <Select
                id={`app-${event.id}`}
                value={applicationId}
                onChange={(e) => setApplicationId(e.target.value)}
              >
                <option value="">Not linked</option>
                {applications?.map((application) => (
                  <option key={application.id} value={application.id}>
                    {application.job?.title || 'Untitled'} — {application.job?.company_name || 'Unknown'}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          {classify.isError && <ErrorState message={messageOf(classify.error)} />}

          <div className="flex flex-wrap gap-2">
            <Button size="sm" disabled={classify.isPending} onClick={save}>
              {classify.isPending ? 'Saving…' : 'Save'}
            </Button>
            <Button size="sm" variant="outline" disabled={classify.isPending} onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      )}
    </li>
  )
}
