import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type CoverLetter, type ResumeDecision, coversApi } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

function useToken(): string {
  const token = useAuthStore((s) => s.accessToken)
  if (!token) throw new Error('Not authenticated')
  return token
}

const letterKey = (jobId: string | null) => ['cover-letter', jobId]

/** null = no draft yet. Polls while the draft is being written. */
export function useCoverLetter(jobId: string | null) {
  const token = useToken()
  return useQuery({
    queryKey: letterKey(jobId),
    queryFn: () => coversApi.get(token, jobId as string),
    enabled: jobId !== null,
    refetchInterval: (query: { state: { data?: CoverLetter | null } }) =>
      query.state.data?.status === 'running' ? 3000 : false,
  })
}

export function useDraftCover() {
  const token = useToken()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => coversApi.draft(token, jobId),
    // The backend creates the "running" row before responding, so refetching straight away
    // shows progress instead of a gap.
    onSuccess: (_data, jobId) => client.invalidateQueries({ queryKey: letterKey(jobId) }),
  })
}

export function useDecideParagraph() {
  const token = useToken()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { letterId: string; paragraphId: string; decision: ResumeDecision }) =>
      coversApi.decide(token, input.letterId, input.paragraphId, input.decision),
    onSuccess: (updated) => client.setQueryData(letterKey(updated.job_posting_id), updated),
  })
}

export function useEditParagraph() {
  const token = useToken()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { letterId: string; paragraphId: string; text: string | null }) =>
      coversApi.edit(token, input.letterId, input.paragraphId, input.text),
    onSuccess: (updated) => client.setQueryData(letterKey(updated.job_posting_id), updated),
  })
}

export function useExportCover() {
  const token = useToken()
  return useMutation({ mutationFn: (letterId: string) => coversApi.export(token, letterId) })
}

export function useDeleteCover() {
  const token = useToken()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { letterId: string; jobId: string }) => coversApi.delete(token, input.letterId),
    onSuccess: (_data, input) => client.setQueryData(letterKey(input.jobId), null),
  })
}
