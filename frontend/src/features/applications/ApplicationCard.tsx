import { cn } from '@/lib/utils'
import type { Application } from '@/lib/api'
import { ApplicationStatusBadge, FollowUpChip, MatchChip } from '@/features/applications/badges'
import { isClosed } from '@/features/applications/labels'

interface ApplicationCardProps {
  application: Application
  selected: boolean
  onSelect: (id: string) => void
}

export function ApplicationCard({ application, selected, onSelect }: ApplicationCardProps) {
  const { job } = application
  return (
    <button
      type="button"
      onClick={() => onSelect(application.id)}
      aria-pressed={selected}
      className={cn(
        'w-full space-y-2 rounded-md border border-border bg-card p-3 text-left text-sm transition-colors hover:bg-accent',
        selected && 'border-ring bg-accent'
      )}
    >
      <div>
        <p className="line-clamp-2 font-medium">{job?.title ?? 'Untitled posting'}</p>
        {job?.company_name && (
          <p className="line-clamp-1 text-xs text-muted-foreground">{job.company_name}</p>
        )}
      </div>
      <div className="flex flex-wrap items-center gap-1.5">
        {isClosed(application.status) && <ApplicationStatusBadge status={application.status} />}
        <MatchChip match={application.match} />
        <FollowUpChip
          state={application.follow_up_state}
          text={application.next_action_text}
          on={application.next_action_on}
        />
      </div>
    </button>
  )
}
