import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, calendarApi, type CalendarEventKind, type CalendarSyncRun } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

const ACTIVE_SYNC_STATUSES = new Set(['pending', 'running'])

function useToken(): string {
  const token = useAuthStore((s) => s.accessToken)
  if (!token) throw new Error('Not authenticated')
  return token
}

export function useCalendarConnection() {
  const token = useToken()
  return useQuery({
    queryKey: ['calendar', 'connection'],
    queryFn: async () => {
      try {
        return await calendarApi.getConnection(token)
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null
        throw error
      }
    },
  })
}

export function useStartCalendarOAuth() {
  const token = useToken()
  return useMutation({
    mutationFn: () => calendarApi.oauthStart(token),
    onSuccess: (data) => {
      window.location.href = data.authorization_url
    },
  })
}

export function useDisconnectCalendar() {
  const token = useToken()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (purgeData: boolean) => calendarApi.disconnect(token, purgeData),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['calendar'] })
      queryClient.invalidateQueries({ queryKey: ['integrations'] })
    },
  })
}

export function useCalendarSyncRuns() {
  const token = useToken()
  return useQuery({
    queryKey: ['calendar', 'syncRuns'],
    queryFn: () => calendarApi.listSyncRuns(token),
    refetchInterval: (query: { state: { data?: CalendarSyncRun[] } }) =>
      query.state.data?.some((run) => ACTIVE_SYNC_STATUSES.has(run.status)) ? 2000 : false,
  })
}

export function useStartCalendarSync() {
  const token = useToken()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => calendarApi.startSync(token),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['calendar', 'syncRuns'] }),
  })
}

export function useCalendarEvents() {
  const token = useToken()
  return useQuery({ queryKey: ['calendar', 'events'], queryFn: () => calendarApi.listEvents(token) })
}

export function useClassifyEvent() {
  const token = useToken()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({
      id,
      kind,
      applicationId,
    }: {
      id: string
      kind: CalendarEventKind
      applicationId: string | null
    }) => calendarApi.classifyEvent(token, id, kind, applicationId),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['calendar', 'events'] }),
  })
}
