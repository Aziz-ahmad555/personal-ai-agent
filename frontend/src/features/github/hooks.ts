import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, githubApi } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

function useToken(): string {
  const token = useAuthStore((s) => s.accessToken)
  if (!token) throw new Error('Not authenticated')
  return token
}

export function useGithubConnection() {
  const token = useToken()
  return useQuery({
    queryKey: ['github', 'connection'],
    queryFn: async () => {
      try {
        return await githubApi.getConnection(token)
      } catch (error) {
        if (error instanceof ApiError && error.status === 404) return null
        throw error
      }
    },
  })
}

export function useStartGithubOAuth() {
  const token = useToken()
  return useMutation({
    mutationFn: () => githubApi.oauthStart(token),
    onSuccess: (data) => {
      window.location.href = data.authorization_url
    },
  })
}

export function useDisconnectGithub() {
  const token = useToken()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => githubApi.disconnect(token),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['github', 'connection'] })
      queryClient.invalidateQueries({ queryKey: ['integrations'] })
    },
  })
}
