import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type PracticeAnswerInput, type PracticeSession, practiceApi } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

function useToken(): string {
  const token = useAuthStore((s) => s.accessToken)
  if (!token) throw new Error('Not authenticated')
  return token
}

const RUNNING_STATUSES = new Set(['questions_running', 'feedback_running'])

const sessionsKey = (jobId: string) => ['practice', 'sessions', jobId]
const sessionKey = (sessionId: string) => ['practice', 'session', sessionId]

export function usePracticeSessions(jobId: string) {
  const token = useToken()
  return useQuery({
    queryKey: sessionsKey(jobId),
    queryFn: () => practiceApi.listSessions(token, jobId),
  })
}

export function useStartPractice(jobId: string) {
  const token = useToken()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (applicationId?: string | null) => practiceApi.start(token, jobId, applicationId),
    onSuccess: () => client.invalidateQueries({ queryKey: sessionsKey(jobId) }),
  })
}

/** Polls while a background LLM call (questions, then feedback) is running. Not while the
 * session is simply waiting on the user to answer. */
export function usePracticeSession(sessionId: string | null) {
  const token = useToken()
  return useQuery({
    queryKey: sessionKey(sessionId ?? ''),
    queryFn: () => practiceApi.get(token, sessionId as string),
    enabled: sessionId !== null,
    refetchInterval: (query: { state: { data?: PracticeSession } }) =>
      query.state.data && RUNNING_STATUSES.has(query.state.data.status) ? 2000 : false,
  })
}

export function useSubmitPracticeAnswers(jobId: string) {
  const token = useToken()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { sessionId: string; answers: PracticeAnswerInput[] }) =>
      practiceApi.submitAnswers(token, input.sessionId, input.answers),
    onSuccess: (_data, input) => {
      client.invalidateQueries({ queryKey: sessionKey(input.sessionId) })
      client.invalidateQueries({ queryKey: sessionsKey(jobId) })
    },
  })
}

export function useDeletePracticeSession(jobId: string) {
  const token = useToken()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (sessionId: string) => practiceApi.delete(token, sessionId),
    onSuccess: () => client.invalidateQueries({ queryKey: sessionsKey(jobId) }),
  })
}
