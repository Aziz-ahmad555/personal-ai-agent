import type { GithubConnection } from '@/lib/api'

/** What the connection can reach, in words. With no installation the app sees public data only. */
export function accessSummary(connection: GithubConnection): string {
  if (connection.installations.length === 0) return 'Public information only'
  const accounts = connection.installations
    .map((installation) => installation.account)
    .filter(Boolean)
    .join(', ')
  return `Public information; the app is also installed on ${accounts || 'an account'} (read-only)`
}
