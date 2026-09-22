import { useState } from 'react'
import { Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/layout/error-state'
import type { PracticeCounts } from '@/lib/api'
import { QuestionCard } from '@/features/practice/QuestionCard'
import { usePracticeSession, useSubmitPracticeAnswers } from '@/features/practice/hooks'

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong'
}

function summarize(counts: PracticeCounts): string {
  const parts: string[] = []
  if (counts.addressed) parts.push(`${counts.addressed} addressed`)
  if (counts.partially_addressed) parts.push(`${counts.partially_addressed} partially addressed`)
  if (counts.missed) parts.push(`${counts.missed} missed`)
  if (counts.unclear) parts.push(`${counts.unclear} unclear`)
  if (counts.unanswered) parts.push(`${counts.unanswered} not answered`)
  return parts.join(' · ') || 'No questions'
}

export function PracticeSessionView({ sessionId, jobId }: { sessionId: string; jobId: string }) {
  const { data: session, isLoading, isError, error, refetch } = usePracticeSession(sessionId)
  const submit = useSubmitPracticeAnswers(jobId)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  // Re-seed the answer drafts from the server once per newly-loaded session (not on every
  // poll), so the user's in-progress typing survives a background refetch. This is the "adjust
  // state during render" pattern React recommends in place of an effect for resetting state
  // when a prop changes.
  const [seededFor, setSeededFor] = useState<string | null>(null)
  if (session && seededFor !== session.id) {
    setSeededFor(session.id)
    setAnswers(Object.fromEntries(session.questions.map((q) => [q.id, q.answer_text ?? ''])))
  }

  if (isLoading) return <Skeleton className="h-32 w-full" />

  if (isError || !session) {
    return (
      <ErrorState message={messageOf(error) ?? 'Failed to load this session'} onRetry={() => refetch()} />
    )
  }

  if (session.status === 'questions_running') {
    return (
      <div className="flex items-center gap-2 rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Writing practice questions, grounded in this job&apos;s verified requirements and your
        profile…
      </div>
    )
  }

  if (session.status === 'feedback_running') {
    return (
      <div className="flex items-center gap-2 rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
        <Loader2 className="h-4 w-4 animate-spin" />
        Checking your answers against each question&apos;s grounding and your own wording…
      </div>
    )
  }

  const editable = session.status === 'ready_for_answers' || session.status === 'failed'
  const canRetry = session.status === 'failed' && session.questions.length > 0

  function submitAnswers() {
    submit.mutate({
      sessionId,
      answers: session!.questions.map((q) => ({
        question_id: q.id,
        answer_text: answers[q.id] ?? '',
      })),
    })
  }

  return (
    <div className="space-y-3">
      {session.status === 'failed' && (
        <ErrorState
          title={session.questions.length === 0 ? "Couldn't write questions" : "Couldn't get feedback"}
          message={session.error ?? 'Unknown error'}
        />
      )}

      {session.status === 'completed' && (
        <p className="text-sm text-muted-foreground">{summarize(session.counts)}</p>
      )}

      {session.dropped.length > 0 && (
        <p className="text-xs text-muted-foreground">
          {session.dropped.length} proposed question{session.dropped.length === 1 ? '' : 's'}{' '}
          couldn&apos;t be grounded and {session.dropped.length === 1 ? "wasn't" : "weren't"} asked.
        </p>
      )}

      {session.questions.length > 0 && (
        <ul className="space-y-2" aria-label="Practice questions">
          {session.questions.map((question, index) => (
            <QuestionCard
              key={question.id}
              question={question}
              index={index}
              editable={editable}
              value={answers[question.id]}
              onChange={(value) => setAnswers((prev) => ({ ...prev, [question.id]: value }))}
            />
          ))}
        </ul>
      )}

      {editable && session.questions.length > 0 && (
        <div className="space-y-2">
          {submit.isError && <ErrorState message={messageOf(submit.error)} />}
          <Button onClick={submitAnswers} disabled={submit.isPending}>
            {submit.isPending ? 'Submitting…' : canRetry ? 'Retry feedback' : 'Submit for feedback'}
          </Button>
        </div>
      )}
    </div>
  )
}
