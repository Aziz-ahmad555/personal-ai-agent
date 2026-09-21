import { AlarmClock, AlertTriangle, CalendarClock } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { ApplicationMatchSummary, ApplicationStatus, FollowUpState } from '@/lib/api'
import { STATUS_LABEL, formatDate } from '@/features/applications/labels'

export function ApplicationStatusBadge({ status }: { status: ApplicationStatus }) {
  if (status === 'accepted') return <Badge>{STATUS_LABEL[status]}</Badge>
  if (status === 'rejected') {
    return (
      <Badge variant="outline" className="border-destructive/50 text-destructive">
        {STATUS_LABEL[status]}
      </Badge>
    )
  }
  if (status === 'withdrawn' || status === 'no_response') {
    return (
      <Badge variant="outline" className="text-muted-foreground">
        {STATUS_LABEL[status]}
      </Badge>
    )
  }
  return <Badge variant="secondary">{STATUS_LABEL[status]}</Badge>
}

interface FollowUpChipProps {
  state: FollowUpState | null
  text: string | null
  on: string | null
}

/** Overdue and due-today are loud; upcoming is quiet. Nothing is sent — this is a reminder
 * shown inside the app only. */
export function FollowUpChip({ state, text, on }: FollowUpChipProps) {
  if (!state) return null
  const label = text || 'Follow up'
  if (state === 'overdue') {
    return (
      <Badge variant="outline" className="gap-1 border-destructive/50 text-destructive">
        <AlarmClock className="h-3 w-3" /> Overdue · {label}
      </Badge>
    )
  }
  if (state === 'due_today') {
    return (
      <Badge variant="outline" className="gap-1 border-warning/70 text-warning-foreground">
        <AlarmClock className="h-3 w-3" /> Due today · {label}
      </Badge>
    )
  }
  return (
    <Badge variant="outline" className="gap-1 text-muted-foreground">
      <CalendarClock className="h-3 w-3" /> {label}
      {on ? ` · ${formatDate(on)}` : ''}
    </Badge>
  )
}

/** The posting's current match, kept honest: a low-confidence score carries its flag. */
export function MatchChip({ match }: { match: ApplicationMatchSummary | null }) {
  if (!match || match.score_percent === null) return null
  return (
    <Badge
      variant="outline"
      className={cn(
        'gap-1',
        match.low_confidence && 'border-dashed border-warning/70 text-warning-foreground'
      )}
    >
      {match.low_confidence && <AlertTriangle className="h-3 w-3" />}
      {match.score_percent}%{match.low_confidence ? ' · low confidence' : ' match'}
    </Badge>
  )
}
