import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { type ResearchQuery, type ResearchQueryDetail, type ResearchQueryInput, researchApi } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

function useToken(): string {
  const token = useAuthStore((s) => s.accessToken)
  if (!token) throw new Error('Not authenticated')
  return token
}

const ACTIVE_STATUSES = new Set(['pending', 'running'])

export function useResearchQueries() {
  const token = useToken()
  return useQuery({
    queryKey: ['research', 'queries'],
    queryFn: () => researchApi.list(token),
    refetchInterval: (query: { state: { data?: ResearchQuery[] } }) => {
      const items = query.state.data
      return items?.some((q) => ACTIVE_STATUSES.has(q.status)) ? 3000 : false
    },
  })
}

export function useCreateResearchQuery() {
  const token = useToken()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (input: ResearchQueryInput) => researchApi.create(token, input),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['research', 'queries'] }),
  })
}

export function useResearchQueryDetail(id: string | null) {
  const token = useToken()
  return useQuery({
    queryKey: ['research', 'query', id],
    queryFn: () => researchApi.get(token, id as string),
    enabled: id !== null,
    refetchInterval: (query: { state: { data?: ResearchQueryDetail } }) => {
      const status = query.state.data?.status
      return status && ACTIVE_STATUSES.has(status) ? 2000 : false
    },
  })
}
