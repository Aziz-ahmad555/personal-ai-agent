import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { ApiError, githubApi, type GithubSyncRun, type SkillLevel } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

function useToken(): string {
  const token = useAuthStore((s) => s.accessToken)
  if (!token) throw new Error('Not authenticated')
  return token
}

const ACTIVE_SYNC_STATUSES = new Set(['pending', 'running'])

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
    mutationFn: (purgeData: boolean) => githubApi.disconnect(token, purgeData),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['github'] })
      queryClient.invalidateQueries({ queryKey: ['integrations'] })
    },
  })
}

export function useGithubSyncRuns() {
  const token = useToken()
  return useQuery({
    queryKey: ['github', 'syncRuns'],
    queryFn: () => githubApi.listSyncRuns(token),
    refetchInterval: (query: { state: { data?: GithubSyncRun[] } }) =>
      query.state.data?.some((run) => ACTIVE_SYNC_STATUSES.has(run.status)) ? 2000 : false,
  })
}

export function useStartGithubSync() {
  const token = useToken()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: () => githubApi.startSync(token),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['github', 'syncRuns'] }),
  })
}

export function useGithubRepos() {
  const token = useToken()
  return useQuery({ queryKey: ['github', 'repos'], queryFn: () => githubApi.listRepos(token) })
}

export function useGithubProposals() {
  const token = useToken()
  return useQuery({ queryKey: ['github', 'proposals'], queryFn: () => githubApi.listProposals(token) })
}

export function useAcceptProposal() {
  const token = useToken()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: ({ id, level }: { id: string; level: SkillLevel | null }) =>
      githubApi.acceptProposal(token, id, level),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['github', 'proposals'] })
      // The profile now has a new skill version.
      queryClient.invalidateQueries({ queryKey: ['skills'] })
      queryClient.invalidateQueries({ queryKey: ['profile'] })
    },
  })
}

export function useDismissProposal() {
  const token = useToken()
  const queryClient = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => githubApi.dismissProposal(token, id),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['github', 'proposals'] }),
  })
}
