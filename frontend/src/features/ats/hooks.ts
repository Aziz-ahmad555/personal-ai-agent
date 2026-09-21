import { useMutation } from '@tanstack/react-query'
import { atsApi } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

function useToken(): string {
  const token = useAuthStore((s) => s.accessToken)
  if (!token) throw new Error('Not authenticated')
  return token
}

/** The check is computed live from the current resume and match, so there's nothing to cache:
 * each run is a fresh result, held by the mutation. */
export function useAtsCheck() {
  const token = useToken()
  return useMutation({ mutationFn: (jobId: string) => atsApi.check(token, jobId) })
}

export function useAtsSafeExport() {
  const token = useAuthStore((s) => s.accessToken)
  return useMutation({
    mutationFn: (jobId: string) => {
      if (!token) throw new Error('Not authenticated')
      return atsApi.safeExport(token, jobId)
    },
  })
}
