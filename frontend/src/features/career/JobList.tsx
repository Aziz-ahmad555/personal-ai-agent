import { Briefcase } from 'lucide-react'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/layout/empty-state'
import { ErrorState } from '@/components/layout/error-state'
import { cn } from '@/lib/utils'
import type { CareerJob } from '@/lib/api'
import { FraudBadge, MatchBadge, VerificationBadge } from '@/features/career/badges'

interface JobListProps {
  jobs: CareerJob[] | undefined
  isLoading: boolean
  isError: boolean
  error: unknown
  onRetry: () => void
  selectedId: string | null
  onSelect: (id: string) => void
}

export function JobList({ jobs, isLoading, isError, error, onRetry, selectedId, onSelect }: JobListProps) {
  return (
    <Card className="h-fit">
      <CardHeader>
        <CardTitle className="text-base">Jobs</CardTitle>
      </CardHeader>
      <CardContent className="space-y-2">
        {isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
          </div>
        )}
        {isError && (
          <ErrorState
            message={error instanceof Error ? error.message : 'Failed to load jobs'}
            onRetry={onRetry}
          />
        )}
        {jobs?.length === 0 && (
          <EmptyState
            icon={<Briefcase className="h-6 w-6" />}
            title="No jobs yet"
            description="Paste a posting or add a URL above, or subscribe to a company's job board below."
            className="p-6"
          />
        )}
        <ul className="space-y-2">
          {jobs?.map((job) => (
            <li key={job.id}>
              <button
                type="button"
                onClick={() => onSelect(job.id)}
                className={cn(
                  'w-full rounded-md border border-border p-3 text-left text-sm transition-colors hover:bg-accent',
                  selectedId === job.id && 'border-ring bg-accent'
                )}
              >
                <p className="line-clamp-2 font-medium">{job.title ?? 'Untitled posting'}</p>
                {job.company_name && (
                  <p className="line-clamp-1 text-xs text-muted-foreground">{job.company_name}</p>
                )}
                <div className="mt-2 flex flex-wrap items-center gap-1.5">
                  <MatchBadge match={job.match} />
                  <FraudBadge level={job.fraud_assessment?.risk_level} />
                  <VerificationBadge status={job.employer_verification?.verification_status} />
                </div>
              </button>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
