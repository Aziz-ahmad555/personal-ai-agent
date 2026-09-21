import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type ResumeDecision, type TailoredResume, resumesApi } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

function useToken(): string {
  const token = useAuthStore((s) => s.accessToken)
  if (!token) throw new Error('Not authenticated')
  return token
}

const resumeKey = (jobId: string | null) => ['resume', jobId]

/** null = no draft yet. Polls while the draft is being generated. */
export function useTailoredResume(jobId: string | null) {
  const token = useToken()
  return useQuery({
    queryKey: resumeKey(jobId),
    queryFn: () => resumesApi.get(token, jobId as string),
    enabled: jobId !== null,
    refetchInterval: (query: { state: { data?: TailoredResume | null } }) =>
      query.state.data?.status === 'running' ? 3000 : false,
  })
}

export function useTailorJob() {
  const token = useToken()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => resumesApi.tailor(token, jobId),
    // The backend creates the "running" row before responding, so refetching straight away
    // shows progress instead of a gap.
    onSuccess: (_data, jobId) => client.invalidateQueries({ queryKey: resumeKey(jobId) }),
  })
}

export function useDecideChange() {
  const token = useToken()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { resumeId: string; changeId: string; decision: ResumeDecision }) =>
      resumesApi.decide(token, input.resumeId, input.changeId, input.decision),
    onSuccess: (updated) => client.setQueryData(resumeKey(updated.job_posting_id), updated),
  })
}

export function useExportResume() {
  const token = useToken()
  return useMutation({ mutationFn: (resumeId: string) => resumesApi.export(token, resumeId) })
}

export function useDeleteResume() {
  const token = useToken()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { resumeId: string; jobId: string }) => resumesApi.delete(token, input.resumeId),
    onSuccess: (_data, input) => client.setQueryData(resumeKey(input.jobId), null),
  })
}
