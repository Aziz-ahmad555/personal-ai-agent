import type { ApplicationStatus } from '@/lib/api'

export const STATUS_LABEL: Record<ApplicationStatus, string> = {
  saved: 'Saved',
  applied: 'Applied',
  screening: 'Screening',
  interviewing: 'Interviewing',
  offer: 'Offer',
  accepted: 'Accepted',
  rejected: 'Rejected',
  withdrawn: 'Withdrawn',
  no_response: 'No response',
}

/** The pipeline, in order — one board column each. */
export const ACTIVE_COLUMNS: ApplicationStatus[] = [
  'saved',
  'applied',
  'screening',
  'interviewing',
  'offer',
]

/** Everything that ends an application; shown together in a final "Closed" column. */
export const CLOSED_STATUSES: ApplicationStatus[] = ['accepted', 'rejected', 'withdrawn', 'no_response']

export function isClosed(status: ApplicationStatus): boolean {
  return CLOSED_STATUSES.includes(status)
}

/** Today as YYYY-MM-DD in the user's local timezone (what a date input expects). */
export function todayISO(): string {
  return new Date().toLocaleDateString('en-CA')
}

/** "2026-09-21" -> "21 Sep 2026", without the off-by-one a UTC parse causes for date-only strings. */
export function formatDate(iso: string): string {
  const [year, month, day] = iso.split('-').map(Number)
  return new Date(year, month - 1, day).toLocaleDateString(undefined, {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  })
}
