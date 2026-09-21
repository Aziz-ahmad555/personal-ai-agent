import { useQuery } from '@tanstack/react-query'
import { searchApi } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

function useToken(): string {
  const token = useAuthStore((s) => s.accessToken)
  if (!token) throw new Error('Not authenticated')
  return token
}

export function useSearchResults(query: string | null) {
  const token = useToken()
  const trimmed = query?.trim() ?? ''
  return useQuery({
    queryKey: ['search', trimmed],
    queryFn: () => searchApi.search(token, trimmed),
    enabled: trimmed.length > 0,
  })
}
