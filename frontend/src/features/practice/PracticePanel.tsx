import { useState } from 'react'
import { GraduationCap, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/layout/error-state'
import type { Application, CareerJob } from '@/lib/api'
import { PracticeSessionView } from '@/features/practice/PracticeSessionView'
import {
  useDeletePracticeSession,
  usePracticeSessions,
  useStartPractice,
} from '@/features/practice/hooks'

const ACTIVE_STATUSES = new Set(['questions_running', 'ready_for_answers', 'feedback_running'])

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong'
}

export function PracticePanel({
  job,
  application,
}: {
  job: CareerJob
  application?: Application | null
}) {
  const { data: sessions, isLoading, isError, error, refetch } = usePracticeSessions(job.id)
  const start = useStartPractice(job.id)
  const remove = useDeletePracticeSession(job.id)
  const [selectedId, setSelectedId] = useState<string | null>(null)

  const matchReady = job.match?.status === 'completed'
  const active = sessions?.find((s) => ACTIVE_STATUSES.has(s.status))
  const effectiveId = selectedId ?? sessions?.[0]?.id ?? null

  return (
    <Card id="practice">
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <GraduationCap className="h-4 w-4" /> Interview practice
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <p className="text-sm text-muted-foreground">
          Generates practice questions grounded in this job&apos;s verified requirements or your
          recorded profile evidence, then checks your answers the same way — citing what was
          addressed or missed, never inventing a verdict. Nothing is sent anywhere.
        </p>

        {!matchReady && (
          <p className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
            Score this job&apos;s match above first — practice reuses its verified requirements.
          </p>
        )}

        {matchReady && (
          <>
            {start.isError && <ErrorState message={messageOf(start.error)} />}
            <Button
              size="sm"
              disabled={start.isPending || Boolean(active)}
              onClick={() =>
                start.mutate(application?.id ?? null, {
                  onSuccess: () => setSelectedId(null), // fall back to the newest once it lands
                })
              }
            >
              {start.isPending
                ? 'Starting…'
                : active
                  ? 'A session is already in progress'
                  : 'Start new practice session'}
            </Button>

            {isLoading && <Skeleton className="h-24 w-full" />}
            {isError && (
              <ErrorState message={messageOf(error) ?? 'Failed to load sessions'} onRetry={() => refetch()} />
            )}

            {sessions && sessions.length === 0 && (
              <p className="text-sm text-muted-foreground">No practice sessions yet.</p>
            )}

            {sessions && sessions.length > 0 && (
              <div className="space-y-3">
                <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Practice sessions">
                  {sessions.map((session, index) => (
                    <div key={session.id} className="flex items-center gap-1">
                      <Button
                        type="button"
                        variant={session.id === effectiveId ? 'default' : 'outline'}
                        size="sm"
                        onClick={() => setSelectedId(session.id)}
                      >
                        {index === 0 ? 'Latest' : new Date(session.created_at).toLocaleDateString()}
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        size="sm"
                        aria-label="Delete this practice session"
                        disabled={remove.isPending}
                        onClick={() => {
                          remove.mutate(session.id)
                          if (session.id === effectiveId) setSelectedId(null)
                        }}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  ))}
                </div>

                {remove.isError && <ErrorState message={messageOf(remove.error)} />}

                {effectiveId && <PracticeSessionView sessionId={effectiveId} jobId={job.id} />}
              </div>
            )}
          </>
        )}
      </CardContent>
    </Card>
  )
}
