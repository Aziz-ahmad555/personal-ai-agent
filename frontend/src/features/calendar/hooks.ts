import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, calendarApi } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

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
    mutationFn: () => calendarApi.disconnect(token),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['calendar'] })
      queryClient.invalidateQueries({ queryKey: ['integrations'] })
    },
  })
}
