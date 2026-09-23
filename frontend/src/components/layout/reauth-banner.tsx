import { Link } from 'react-router-dom'
import { AlertTriangle } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { useGmailConnection } from '@/features/gmail/hooks'
import { useCalendarConnection } from '@/features/calendar/hooks'
import { useGithubConnection } from '@/features/github/hooks'

/** Phase 11, Group B: once Gmail/Calendar sync run on a schedule instead of a manual click,
 * a needs_reauth failure loses its old feedback loop — the user isn't staring at a "Sync"
 * button when it happens. This shows on every authenticated page (not just the dedicated
 * integration page) so a silent reauth failure surfaces the next time the app is open at all,
 * not just in the next weekly digest. Covers GitHub too, for the same reason a manual sync
 * failure there has the identical blind spot. */
export function ReauthBanner() {
  const gmail = useGmailConnection()
  const calendar = useCalendarConnection()
  const github = useGithubConnection()

  const broken = [
    gmail.data?.status === 'needs_reauth' && { label: 'Gmail', to: '/gmail' },
    calendar.data?.status === 'needs_reauth' && { label: 'Calendar', to: '/calendar' },
    github.data?.status === 'needs_reauth' && { label: 'GitHub', to: '/github' },
  ].filter((x): x is { label: string; to: string } => Boolean(x))

  if (broken.length === 0) return null

  return (
    <Alert variant="destructive" className="mx-4 mt-3 sm:mx-6">
      <AlertTriangle className="h-4 w-4" />
      <AlertDescription>
        {broken.length === 1 ? (
          <>
            <Link to={broken[0].to} className="font-medium underline underline-offset-2">
              {broken[0].label}
            </Link>{' '}
            needs to be reconnected — it stopped syncing and won't pick back up on its own.
          </>
        ) : (
          <>
            These need to be reconnected — they stopped syncing and won't pick back up on their
            own:{' '}
            {broken.map((item, i) => (
              <span key={item.to}>
                <Link to={item.to} className="font-medium underline underline-offset-2">
                  {item.label}
                </Link>
                {i < broken.length - 1 ? ', ' : ''}
              </span>
            ))}
          </>
        )}
      </AlertDescription>
    </Alert>
  )
}
