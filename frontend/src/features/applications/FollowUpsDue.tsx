import { Link } from 'react-router-dom'
import { AlarmClock } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { FollowUpChip } from '@/features/applications/badges'
import { dueFollowUps } from '@/features/applications/followUps'
import { useApplications } from '@/features/applications/hooks'

/** Renders nothing when there is nothing to do (or while loading / on error — a dashboard
 * nag shouldn't add noise). */
export function FollowUpsDue() {
  const { data } = useApplications()
  const due = data ? dueFollowUps(data) : []
  if (due.length === 0) return null

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <AlarmClock className="h-4 w-4" /> Follow-ups due
        </CardTitle>
      </CardHeader>
      <CardContent>
        <ul className="space-y-2">
          {due.map((application) => (
            <li key={application.id}>
              <Link
                to={`/applications?selected=${application.id}`}
                className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border p-3 text-sm transition-colors hover:bg-accent"
              >
                <span className="min-w-0">
                  <span className="font-medium">{application.job?.title ?? 'Untitled posting'}</span>
                  {application.job?.company_name && (
                    <span className="text-muted-foreground"> · {application.job.company_name}</span>
                  )}
                </span>
                <FollowUpChip
                  state={application.follow_up_state}
                  text={application.next_action_text}
                  on={application.next_action_on}
                />
              </Link>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
