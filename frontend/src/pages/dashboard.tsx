import { useQuery } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import { Briefcase, FolderSearch, Search } from 'lucide-react'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
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

      <div className="grid gap-4 sm:grid-cols-2">
        <Link
          to="/research"
          className="flex items-start gap-3 rounded-lg border border-border p-4 transition-colors hover:bg-accent"
        >
          <FolderSearch className="h-5 w-5 shrink-0 text-muted-foreground" />
          <div>
            <p className="text-sm font-medium">Research</p>
            <p className="text-sm text-muted-foreground">
              Ask a question, get a cited, confidence-scored answer.
            </p>
          </div>
        </Link>
        <Link
          to="/search"
          className="flex items-start gap-3 rounded-lg border border-border p-4 transition-colors hover:bg-accent"
        >
          <Search className="h-5 w-5 shrink-0 text-muted-foreground" />
          <div>
            <p className="text-sm font-medium">Search</p>
            <p className="text-sm text-muted-foreground">
              Semantic search across your profile and past research.
            </p>
          </div>
        </Link>
        <Link
          to="/career"
          className="flex items-start gap-3 rounded-lg border border-border p-4 transition-colors hover:bg-accent"
        >
          <Briefcase className="h-5 w-5 shrink-0 text-muted-foreground" />
          <div>
            <p className="text-sm font-medium">Career</p>
            <p className="text-sm text-muted-foreground">
              Add job postings and see how well each fits you, with the evidence.
            </p>
          </div>
        </Link>
      </div>
    </div>
  )
}
