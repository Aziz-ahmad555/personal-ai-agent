import { useQuery } from '@tanstack/react-query'
import { FolderSearch } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/layout/empty-state'
import { ErrorState } from '@/components/layout/error-state'
import { authApi } from '@/lib/api'
import { useAuthStore } from '@/stores/auth'

export function DashboardPage() {
  const accessToken = useAuthStore((s) => s.accessToken)

  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ['me'],
    queryFn: () => authApi.me(accessToken as string),
    enabled: Boolean(accessToken),
  })

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Your profile</CardTitle>
          <CardDescription>Verified against the backend on every load — no cached guesses.</CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading && <Skeleton className="h-5 w-48" />}
          {isError && (
            <ErrorState
              message={error instanceof Error ? error.message : 'Failed to load profile'}
              onRetry={() => refetch()}
            />
          )}
          {data && (
            <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-sm">
              <dt className="text-muted-foreground">Email</dt>
              <dd>{data.email}</dd>
              <dt className="text-muted-foreground">Account created</dt>
              <dd>{new Date(data.created_at).toLocaleString()}</dd>
            </dl>
          )}
        </CardContent>
      </Card>

      <EmptyState
        icon={<FolderSearch className="h-8 w-8" />}
        title="Research Engine not built yet"
        description="Job research, source verification, and confidence scoring arrive in Phase 3."
      />
    </div>
  )
}
