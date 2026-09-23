import type { ReactNode } from 'react'
import { Download, Trash2 } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorState } from '@/components/layout/error-state'
import type { DigestData, DigestJobRef, WeeklyDigest } from '@/lib/api'
import { useDeleteDigest, useDownloadDigest } from '@/features/reporting/hooks'

function jobLine(job: DigestJobRef): string {
  return job.company_name ? `${job.title ?? 'Untitled posting'} — ${job.company_name}` : job.title ?? 'Untitled posting'
}

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong'
}

function Section({
  title,
  children,
  empty,
  emptyText = 'Nothing here for this period.',
}: {
  title: string
  children?: ReactNode
  empty: boolean
  emptyText?: string
}) {
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium">{title}</h3>
      {empty ? (
        <p className="text-sm text-muted-foreground">{emptyText}</p>
      ) : (
        <ul className="space-y-1 text-sm text-muted-foreground">{children}</ul>
      )}
    </div>
  )
}

function AttentionSection({ attention }: { attention: DigestData['attention'] }) {
  const lines: string[] = []
  for (const item of attention.follow_ups_overdue) {
    lines.push(`Follow-up overdue: ${jobLine(item)}${item.next_action_text ? ` — ${item.next_action_text}` : ''}`)
  }
  for (const item of attention.follow_ups_due_today) {
    lines.push(`Follow-up due today: ${jobLine(item)}`)
  }
  for (const item of attention.stale_matches) lines.push(`Match is stale: ${jobLine(item)}`)
  for (const item of attention.stale_resumes) lines.push(`Tailored resume is stale: ${jobLine(item)}`)
  for (const item of attention.stale_cover_letters) lines.push(`Cover letter is stale: ${jobLine(item)}`)
  for (const run of attention.stalled_runs) {
    const label = run.integration ?? jobLine(run as DigestJobRef)
    lines.push(`A ${run.kind.replace('_', ' ')} didn't finish and needs a retry: ${label}`)
  }
  for (const name of attention.connections_needing_reauth) {
    lines.push(`${name.charAt(0).toUpperCase()}${name.slice(1)} needs to be reconnected`)
  }
  if (attention.pending_audit_approvals.count) {
    lines.push(`${attention.pending_audit_approvals.count} action(s) awaiting your approval`)
  }
  if (attention.pending_skill_proposals.count) {
    lines.push(`${attention.pending_skill_proposals.count} GitHub skill proposal(s) awaiting review`)
  }

  if (lines.length === 0) {
    return (
      <Alert>
        <AlertTitle>Needs your attention</AlertTitle>
        <AlertDescription>Nothing needs your attention right now.</AlertDescription>
      </Alert>
    )
  }

  return (
    <Alert>
      <AlertTitle>Needs your attention</AlertTitle>
      <AlertDescription>
        <ul className="list-disc space-y-1 pl-4">
          {lines.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      </AlertDescription>
    </Alert>
  )
}

export function DigestView({ digest }: { digest: WeeklyDigest }) {
  const { data } = digest
  const download = useDownloadDigest()
  const remove = useDeleteDigest()
  const { career, research, gmail, github, calendar } = data

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
        <div>
          <CardTitle className="text-base">
            {data.period.start} to {data.period.end}
          </CardTitle>
          <p className="text-xs text-muted-foreground">
            Generated {new Date(data.generated_at).toLocaleString()}
          </p>
        </div>
        <div className="flex shrink-0 gap-2">
          <Button
            size="sm"
            variant="outline"
            disabled={download.isPending}
            onClick={() => download.mutate(digest.id)}
          >
            <Download className="h-3.5 w-3.5" />
            {download.isPending ? 'Preparing…' : 'Export PDF'}
          </Button>
          <Button
            size="sm"
            variant="ghost"
            aria-label="Delete this digest"
            disabled={remove.isPending}
            onClick={() => remove.mutate(digest.id)}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-5">
        {download.isError && <ErrorState message={messageOf(download.error)} />}
        {remove.isError && <ErrorState message={messageOf(remove.error)} />}

        <AttentionSection attention={data.attention} />

        <Section title="Career activity this week" empty={isCareerEmpty(career)}>
          {career.jobs_discovered.count > 0 && (
            <li>{career.jobs_discovered.count} new job(s) discovered</li>
          )}
          {career.matches_computed.items.map((m) => (
            <li key={m.id}>
              Match computed for {jobLine(m)}:{' '}
              {m.score_percent !== null ? `${m.score_percent}%` : 'not assessed'}
              {m.low_confidence ? ' (low confidence)' : ''}
            </li>
          ))}
          {career.high_risk_postings.items.map((job) => (
            <li key={job.id}>High fraud risk flagged: {jobLine(job)}</li>
          ))}
          {Object.entries(career.application_status_changes.by_status).map(([status, count]) => (
            <li key={status}>
              {count} application(s) moved to <Badge variant="outline">{status}</Badge>
            </li>
          ))}
          {career.cover_letters_drafted.count > 0 && (
            <li>{career.cover_letters_drafted.count} cover letter(s) drafted</li>
          )}
          {career.resumes_drafted.count > 0 && (
            <li>{career.resumes_drafted.count} resume(s) tailored</li>
          )}
          {career.practice_sessions.count > 0 && (
            <li>
              {career.practice_sessions.count} interview practice session(s) —{' '}
              {career.practice_sessions.verdict_tally.addressed} addressed,{' '}
              {career.practice_sessions.verdict_tally.partially_addressed} partial,{' '}
              {career.practice_sessions.verdict_tally.missed} missed,{' '}
              {career.practice_sessions.verdict_tally.unclear} unclear,{' '}
              {career.practice_sessions.verdict_tally.unanswered} unanswered
            </li>
          )}
        </Section>

        <Section title="Research activity this week" empty={research.queries_run.count === 0}>
          {research.queries_run.count > 0 && (
            <li>
              {research.queries_run.count} research quer{research.queries_run.count === 1 ? 'y' : 'ies'} run,{' '}
              {research.queries_completed.count} completed
            </li>
          )}
          {Object.entries(research.claims_added.by_status).map(([status, count]) => (
            <li key={status}>
              {count} claim(s) added: <Badge variant="outline">{status}</Badge>
            </li>
          ))}
        </Section>

        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1 text-sm">
            <h3 className="font-medium">Gmail</h3>
            {gmail.connected ? (
              <p className="text-muted-foreground">
                {gmail.messages_synced.count} synced this week · {gmail.unread_count} unread
              </p>
            ) : (
              <p className="text-muted-foreground">Not connected.</p>
            )}
          </div>
          <div className="space-y-1 text-sm">
            <h3 className="font-medium">GitHub</h3>
            {github.connected ? (
              <p className="text-muted-foreground">
                {github.repos_synced.count} repo(s) synced this week ·{' '}
                {github.pending_proposals.count} proposal(s) pending · readiness{' '}
                {github.readiness.passed}/{github.readiness.total}
              </p>
            ) : (
              <p className="text-muted-foreground">Not connected.</p>
            )}
          </div>
        </div>

        <Section
          title="Upcoming"
          empty={
            !calendar.connected ||
            (calendar.upcoming_interviews.length === 0 && calendar.upcoming_deadlines.length === 0)
          }
          emptyText={
            calendar.connected
              ? 'No upcoming interviews or deadlines in the lookahead window.'
              : 'Calendar is not connected.'
          }
        >
          {calendar.connected && (
            <>
              {calendar.upcoming_interviews.map((event, i) => (
                <li key={`interview-${i}`}>
                  Interview: {event.summary ?? (event.job && jobLine(event.job)) ?? 'Untitled'} (
                  {event.start_at ? new Date(event.start_at).toLocaleString() : 'no time set'})
                </li>
              ))}
              {calendar.upcoming_deadlines.map((event, i) => (
                <li key={`deadline-${i}`}>
                  Deadline: {event.summary ?? (event.job && jobLine(event.job)) ?? 'Untitled'} (
                  {event.start_at ? new Date(event.start_at).toLocaleString() : 'no time set'})
                </li>
              ))}
            </>
          )}
        </Section>
      </CardContent>
    </Card>
  )
}

function isCareerEmpty(career: DigestData['career']): boolean {
  return (
    career.jobs_discovered.count === 0 &&
    career.matches_computed.count === 0 &&
    career.high_risk_postings.count === 0 &&
    career.application_status_changes.count === 0 &&
    career.cover_letters_drafted.count === 0 &&
    career.resumes_drafted.count === 0 &&
    career.practice_sessions.count === 0
  )
}
