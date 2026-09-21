import { MessageSquare, Mic, Milestone } from 'lucide-react'
import type { ApplicationEvent, ApplySnapshot } from '@/lib/api'
import { CLOSED_STATUSES, STATUS_LABEL, formatDate } from '@/features/applications/labels'

function eventTitle(event: ApplicationEvent): string {
  if (event.event_type === 'note') return 'Note'
  if (event.event_type === 'interview') return 'Interview'
  const to = event.to_status ? STATUS_LABEL[event.to_status] : ''
  if (!event.from_status) return `Started tracking (${to.toLowerCase()})`
  const reopened =
    CLOSED_STATUSES.includes(event.from_status) &&
    event.to_status &&
    !CLOSED_STATUSES.includes(event.to_status)
  return reopened
    ? `Reopened as ${to.toLowerCase()}`
    : `${STATUS_LABEL[event.from_status]} → ${to}`
}

function EventIcon({ event }: { event: ApplicationEvent }) {
  const cls = 'h-3.5 w-3.5'
  if (event.event_type === 'note') return <MessageSquare className={cls} aria-hidden />
  if (event.event_type === 'interview') return <Mic className={cls} aria-hidden />
  return <Milestone className={cls} aria-hidden />
}

/** What the user knew about the posting the moment they applied — frozen at that time, so it
 * stays true even after the live match, fraud, or employer check is recomputed. */
export function SnapshotSummary({ snapshot }: { snapshot: ApplySnapshot }) {
  const { match } = snapshot
  const parts: string[] = []

  if (!match || match.score_percent === null) {
    parts.push('not matched to your profile')
  } else if (match.low_confidence) {
    parts.push(
      `${match.score_percent}% match — low confidence (${match.assessed_weight}/100 points assessed)`
    )
  } else {
    parts.push(`${match.score_percent}% match`)
  }
  parts.push(
    snapshot.fraud_risk_level ? `fraud risk ${snapshot.fraud_risk_level}` : 'fraud check not run'
  )
  parts.push(
    snapshot.employer_verification
      ? `employer ${snapshot.employer_verification}`
      : 'employer not verified'
  )

  return (
    <p className="mt-1 rounded-md bg-muted/60 px-2 py-1.5 text-xs text-muted-foreground">
      <span className="font-medium text-foreground">When you applied:</span> {parts.join(' · ')}
    </p>
  )
}

export function Timeline({ events }: { events: ApplicationEvent[] }) {
  return (
    <ol className="space-y-3 border-l border-border pl-4">
      {events.map((event) => (
        <li key={event.id} className="relative text-sm">
          <span className="absolute -left-[25px] top-0.5 flex h-5 w-5 items-center justify-center rounded-full border border-border bg-background text-muted-foreground">
            <EventIcon event={event} />
          </span>
          <div className="flex flex-wrap items-baseline justify-between gap-x-3">
            <p className="font-medium">{eventTitle(event)}</p>
            <time dateTime={event.occurred_on} className="text-xs text-muted-foreground">
              {formatDate(event.occurred_on)}
            </time>
          </div>
          {event.body && <p className="whitespace-pre-wrap text-muted-foreground">{event.body}</p>}
          {event.snapshot && <SnapshotSummary snapshot={event.snapshot} />}
        </li>
      ))}
    </ol>
  )
}
