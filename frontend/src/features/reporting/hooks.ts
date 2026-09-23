import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { reportingApi } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

function useToken(): string {
  const token = useAuthStore((s) => s.accessToken)
  if (!token) throw new Error('Not authenticated')
  return token
}

const DIGESTS_KEY = ['reporting', 'digests']
const digestKey = (id: string) => ['reporting', 'digest', id]

export function useDigests() {
  const token = useToken()
  return useQuery({ queryKey: DIGESTS_KEY, queryFn: () => reportingApi.listDigests(token) })
}

export function useDigest(id: string | null) {
  const token = useToken()
  return useQuery({
    queryKey: digestKey(id ?? ''),
    queryFn: () => reportingApi.getDigest(token, id as string),
    enabled: id !== null,
  })
}

export function useGenerateDigest() {
  const token = useToken()
  const client = useQueryClient()
  return useMutation({
    // No background/polling needed anywhere here: generation is synchronous, unlike every
    // LLM-backed feature elsewhere in this app.
    mutationFn: (input: { days: number; lookaheadDays: number }) =>
      reportingApi.generateDigest(token, input.days, input.lookaheadDays),
    onSuccess: (digest) => {
      client.setQueryData(digestKey(digest.id), digest)
      client.invalidateQueries({ queryKey: DIGESTS_KEY })
    },
  })
}

export function useDeleteDigest() {
  const token = useToken()
  const client = useQueryClient()
  return useMutation({
    mutationFn: (id: string) => reportingApi.deleteDigest(token, id),
    onSuccess: () => client.invalidateQueries({ queryKey: DIGESTS_KEY }),
  })
}

export function useDownloadDigest() {
  const token = useToken()
  return useMutation({
    mutationFn: (id: string) => reportingApi.downloadDigest(token, id),
    onSuccess: ({ blob, filename }) => {
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = filename
      link.click()
      URL.revokeObjectURL(url)
    },
  })
}
