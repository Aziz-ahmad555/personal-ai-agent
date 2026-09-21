import type { Application } from '@/lib/api'

/** Only what needs attention today: overdue first, then due today (oldest date first). */
export function dueFollowUps(applications: Application[]): Application[] {
  const due = applications.filter(
    (a) => a.follow_up_state === 'overdue' || a.follow_up_state === 'due_today'
  )
  return due.sort((a, b) => {
    if (a.follow_up_state !== b.follow_up_state) return a.follow_up_state === 'overdue' ? -1 : 1
    return (a.next_action_on ?? '').localeCompare(b.next_action_on ?? '')
  })
}
