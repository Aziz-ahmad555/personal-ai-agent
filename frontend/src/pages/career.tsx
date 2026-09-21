import { useState } from 'react'
import { CaptureJobForm } from '@/features/career/CaptureJobForm'
import { FeedsPanel } from '@/features/career/FeedsPanel'
import { JobDetail } from '@/features/career/JobDetail'
import { JobList } from '@/features/career/JobList'
import { useJobs } from '@/features/career/hooks'

export function CareerPage() {
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const { data: jobs, isLoading, isError, error, refetch } = useJobs()

  const selectedJob = jobs?.find((job) => job.id === selectedId) ?? null

  return (
    <div className="mx-auto flex max-w-5xl flex-col gap-6">
      <CaptureJobForm onCreated={setSelectedId} />
      <div className="grid items-start gap-6 md:grid-cols-[300px_1fr]">
        <JobList
          jobs={jobs}
          isLoading={isLoading}
          isError={isError}
          error={error}
          onRetry={() => refetch()}
          selectedId={selectedId}
          onSelect={setSelectedId}
        />
        <JobDetail job={selectedJob} />
      </div>
      <FeedsPanel />
    </div>
  )
}
