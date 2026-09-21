import { useState } from 'react'
import { Link, useSearchParams } from 'react-router-dom'
import { ClipboardList } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/layout/empty-state'
import { ErrorState } from '@/components/layout/error-state'
import { ApplicationPanel } from '@/features/applications/ApplicationPanel'
import { Board } from '@/features/applications/Board'
import { useApplications } from '@/features/applications/hooks'

export function ApplicationsPage() {
  const [searchParams] = useSearchParams()
  const [selectedId, setSelectedId] = useState<string | null>(searchParams.get('selected'))
  const { data: applications, isLoading, isError, error, refetch } = useApplications()

  return (
    <div className="mx-auto flex max-w-6xl flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Applications</CardTitle>
          <CardDescription>
            Where each application stands. This is your own record — every status is entered by you,
            and nothing here is ever sent or submitted for you.
          </CardDescription>
        </CardHeader>
        <CardContent>
          {isLoading && (
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-24 w-full" />
              <Skeleton className="h-24 w-full" />
            </div>
          )}
          {isError && (
            <ErrorState
              message={error instanceof Error ? error.message : 'Failed to load applications'}
              onRetry={() => refetch()}
            />
          )}
          {applications?.length === 0 && (
            <EmptyState
              icon={<ClipboardList className="h-8 w-8" />}
              title="No applications yet"
              description="Open a job on the Career page and choose “Track this application” to start."
              action={
                <Button asChild variant="outline" size="sm">
                  <Link to="/career">Go to Career</Link>
                </Button>
              }
            />
          )}
          {applications && applications.length > 0 && (
            <Board applications={applications} selectedId={selectedId} onSelect={setSelectedId} />
          )}
        </CardContent>
      </Card>

      {applications && applications.length > 0 && (
        <ApplicationPanel applicationId={selectedId} onDeleted={() => setSelectedId(null)} />
      )}
    </div>
  )
}
