import { useQuery } from '@tanstack/react-query'
import { integrationsApi } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

export function useIntegrations() {
  const token = useAuthStore((s) => s.accessToken)
  return useQuery({
    queryKey: ['integrations'],
    queryFn: () => integrationsApi.list(token as string),
    enabled: Boolean(token),
  })
}
