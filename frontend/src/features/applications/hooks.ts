import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  type ApplicationDetail,
  type ApplicationEventInput,
  type ApplicationPatch,
  type ApplicationStatusChangeInput,
  applicationsApi,
} from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

function useToken(): string {
  const token = useAuthStore((s) => s.accessToken)
  if (!token) throw new Error('Not authenticated')
  return token
}

const LIST_KEY = ['applications', 'list']
const detailKey = (id: string | null) => ['applications', 'detail', id]

export function useApplications() {
  const token = useToken()
  return useQuery({ queryKey: LIST_KEY, queryFn: () => applicationsApi.list(token) })
}

export function useApplication(id: string | null) {
  const token = useToken()
  return useQuery({
    queryKey: detailKey(id),
    queryFn: () => applicationsApi.get(token, id as string),
    enabled: id !== null,
  })
}

/** Every mutation returns the full updated application, so the detail cache is set directly
 * (no refetch flicker) and the board's list is invalidated to pick up the new column. */
function useApplicationMutation<TInput>(
  run: (token: string, id: string, input: TInput) => Promise<ApplicationDetail>
) {
  const token = useToken()
  const client = useQueryClient()
  return useMutation({
    mutationFn: ({ id, input }: { id: string; input: TInput }) => run(token, id, input),
    onSuccess: (updated) => {
      client.setQueryData(detailKey(updated.id), updated)
      return client.invalidateQueries({ queryKey: LIST_KEY })
    },
  })
}

export function useTrackJob() {
  const token = useToken()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (jobPostingId: string) => applicationsApi.create(token, jobPostingId),
    onSuccess: (created) => {
      client.setQueryData(detailKey(created.id), created)
      return client.invalidateQueries({ queryKey: LIST_KEY })
    },
  })
}

export function useChangeStatus() {
  return useApplicationMutation<ApplicationStatusChangeInput>(applicationsApi.changeStatus)
}

export function useAddEvent() {
  return useApplicationMutation<ApplicationEventInput>(applicationsApi.addEvent)
}

export function useUpdateApplication() {
  return useApplicationMutation<ApplicationPatch>(applicationsApi.update)
}

export function useDeleteApplication() {
  const token = useToken()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => applicationsApi.delete(token, id),
    onSuccess: (_data, id) => {
      client.removeQueries({ queryKey: detailKey(id) })
      return client.invalidateQueries({ queryKey: LIST_KEY })
    },
  })
}
