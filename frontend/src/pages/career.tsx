import { useEffect, useState } from 'react'
import { useSearchParams } from 'react-router-dom'
import { CaptureJobForm } from '@/features/career/CaptureJobForm'
import { FeedsPanel } from '@/features/career/FeedsPanel'
import { JobDetail } from '@/features/career/JobDetail'
import { JobList } from '@/features/career/JobList'
import { useJobs } from '@/features/career/hooks'

export function CareerPage() {
  const [searchParams, setSearchParams] = useSearchParams()
  const [selectedId, setSelectedId] = useState<string | null>(() => searchParams.get('job'))
  const { data: jobs, isLoading, isError, error, refetch } = useJobs()

  // The deep-link param is one-shot: read it once, then clear it so a later reload (or picking
  // a different job) doesn't keep forcing the selection back.
  useEffect(() => {
    if (searchParams.get('job')) setSearchParams({}, { replace: true })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

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
