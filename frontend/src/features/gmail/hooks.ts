import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, type GmailSyncRun, gmailApi } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

function useToken(): string {
  const token = useAuthStore((s) => s.accessToken)
  if (!token) throw new Error('Not authenticated')
  return token
}

const ACTIVE_SYNC_STATUSES = new Set(['pending', 'running'])

export function useGmailConnection() {
  const token = useToken()
  return useQuery({
    queryKey: ['gmail', 'connection'],
    queryFn: async () => {
      try {
        return await gmailApi.getConnection(token)
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null
        throw error
      }
    },
  })
}

export function useStartOAuth() {
  const token = useToken()
  return useMutation({
    mutationFn: () => gmailApi.oauthStart(token),
    onSuccess: (data) => {
      window.location.href = data.authorization_url
    },
  })
}

export function useStartSync() {
  const token = useToken()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => gmailApi.startSync(token),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['gmail', 'syncRuns'] }),
  })
}

export function useSyncRuns() {
  const token = useToken()
  return useQuery({
    queryKey: ['gmail', 'syncRuns'],
    queryFn: () => gmailApi.listSyncRuns(token),
    refetchInterval: (query: { state: { data?: GmailSyncRun[] } }) => {
      const items = query.state.data
      return items?.some((run) => ACTIVE_SYNC_STATUSES.has(run.status)) ? 2000 : false
    },
  })
}

export function useMessages(enabled: boolean) {
  const token = useToken()
  return useQuery({
    queryKey: ['gmail', 'messages'],
    queryFn: () => gmailApi.listMessages(token),
    enabled,
  })
}

export function useDisconnectGmail() {
  const token = useToken()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (purgeData: boolean) => gmailApi.disconnect(token, purgeData),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['gmail'] }),
  })
}
