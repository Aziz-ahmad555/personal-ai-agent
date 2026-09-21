import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { QueryClient } from '@tanstack/react-query'
import { type CareerJob, type JobBoardFeedInput, careerApi } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

function useToken(): string {
  const token = useAuthStore((s) => s.accessToken)
  if (!token) throw new Error('Not authenticated')
  return token
}

const JOBS_KEY = ['career', 'jobs']
const FEEDS_KEY = ['career', 'feeds']
const VERIFYING_KEY = ['career', 'verifying']

// Verification runs in the background and (unlike matching) has no status row of its own, so
// "still working" is inferred: we remember when the user asked (a marker in the query cache),
// and treat it as in progress until a fraud assessment newer than that request shows up. A
// timer drops the marker after VERIFY_TIMEOUT_MS so a silently failed run doesn't spin forever.
const VERIFY_TIMEOUT_MS = 120_000

type VerifyingMarkers = Record<string, number>

function isVerifying(job: CareerJob, markers: VerifyingMarkers): boolean {
  const startedAt = markers[job.id]
  if (startedAt === undefined) return false
  return !job.fraud_assessment || new Date(job.fraud_assessment.assessed_at).getTime() < startedAt
}

function needsPolling(jobs: CareerJob[] | undefined, client: QueryClient): boolean {
  if (!jobs) return false
  const markers = client.getQueryData<VerifyingMarkers>(VERIFYING_KEY) ?? {}
  return jobs.some((job) => job.match?.status === 'running' || isVerifying(job, markers))
}

export function useJobs() {
  const token = useToken()
  const client = useQueryClient()
  return useQuery({
    queryKey: JOBS_KEY,
    queryFn: () => careerApi.listJobs(token),
    refetchInterval: (query: { state: { data?: CareerJob[] } }) =>
      needsPolling(query.state.data, client) ? 3000 : false,
  })
}

/** Ids of jobs whose verification was requested and hasn't landed yet. */
export function useVerifyingJobIds(): Set<string> {
  const { data: markers = {} } = useQuery<VerifyingMarkers>({
    queryKey: VERIFYING_KEY,
    queryFn: () => ({}),
    staleTime: Infinity,
    initialData: {},
  })
  const { data: jobs } = useQuery<CareerJob[]>({ queryKey: JOBS_KEY, enabled: false })
  return new Set((jobs ?? []).filter((job) => isVerifying(job, markers)).map((j) => j.id))
}

export function useCaptureJob() {
  const token = useToken()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: { kind: 'url'; url: string } | { kind: 'paste'; text: string }) =>
      input.kind === 'url'
        ? careerApi.createFromUrl(token, input.url)
        : careerApi.createFromPaste(token, input.text),
    onSuccess: () => client.invalidateQueries({ queryKey: JOBS_KEY }),
  })
}

export function useMatchJob() {
  const token = useToken()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => careerApi.matchJob(token, jobId),
    // The backend creates the "running" row before responding, so refetching straight away
    // shows progress instead of a gap.
    onSuccess: () => client.invalidateQueries({ queryKey: JOBS_KEY }),
  })
}

export function useVerifyJob() {
  const token = useToken()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (jobId: string) => careerApi.verifyJob(token, jobId),
    onSuccess: (_data, jobId) => {
      const startedAt = Date.now()
      client.setQueryData<VerifyingMarkers>(VERIFYING_KEY, (prev) => ({
        ...prev,
        [jobId]: startedAt,
      }))
      window.setTimeout(() => {
        // Only clear our own marker — a later re-check may have replaced it.
        client.setQueryData<VerifyingMarkers>(VERIFYING_KEY, (prev = {}) => {
          if (prev[jobId] !== startedAt) return prev
          const { [jobId]: _expired, ...rest } = prev
          return rest
        })
      }, VERIFY_TIMEOUT_MS)
      return client.invalidateQueries({ queryKey: JOBS_KEY })
    },
  })
}

export function useFeeds() {
  const token = useToken()
  return useQuery({ queryKey: FEEDS_KEY, queryFn: () => careerApi.listFeeds(token) })
}

export function useCreateFeed() {
  const token = useToken()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (input: JobBoardFeedInput) => careerApi.createFeed(token, input),
    onSuccess: () => client.invalidateQueries({ queryKey: FEEDS_KEY }),
  })
}

export function useDeleteFeed() {
  const token = useToken()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => careerApi.deleteFeed(token, id),
    onSuccess: () => client.invalidateQueries({ queryKey: FEEDS_KEY }),
  })
}

export function usePollFeed() {
  const token = useToken()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => careerApi.pollFeed(token, id),
    // Polling is a background task; new postings appear in the job list as they land.
    onSuccess: () => {
      for (const delay of [3000, 8000, 20000]) {
        window.setTimeout(() => {
          void client.invalidateQueries({ queryKey: JOBS_KEY })
          void client.invalidateQueries({ queryKey: FEEDS_KEY })
        }, delay)
      }
    },
  })
}
