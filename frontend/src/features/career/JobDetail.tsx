import { Briefcase, ExternalLink, Loader2, ShieldCheck } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { EmptyState } from '@/components/layout/empty-state'
import { ErrorState } from '@/components/layout/error-state'
import type { CareerJob } from '@/lib/api'
import { FraudBadge, VerificationBadge } from '@/features/career/badges'
import { Link } from 'react-router-dom'
import { ApplicationStatusBadge } from '@/features/applications/badges'
import { useApplications, useTrackJob } from '@/features/applications/hooks'
import { useMatchJob, useVerifyJob, useVerifyingJobIds } from '@/features/career/hooks'
import { MatchPanel } from '@/features/career/MatchPanel'
import { CoverPanel } from '@/features/cover/CoverPanel'
import { TailorPanel } from '@/features/resume/TailorPanel'

function formatSalary(job: CareerJob): string | null {
  const { salary_min: min, salary_max: max, salary_currency: currency } = job
  if (min === null && max === null) return null
  const range =
    min !== null && max !== null && min !== max
      ? `${min.toLocaleString()}–${max.toLocaleString()}`
      : (min ?? max)!.toLocaleString()
  return currency ? `${currency} ${range}` : range
}

function VerificationSection({ job, isVerifying }: { job: CareerJob; isVerifying: boolean }) {
  const verifyJob = useVerifyJob()
  const verification = job.employer_verification
  const fraud = job.fraud_assessment

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-2 space-y-0">
        <CardTitle className="flex items-center gap-2 text-base">
          <ShieldCheck className="h-4 w-4" /> Employer &amp; fraud check
        </CardTitle>
        <Button
          variant="outline"
          size="sm"
          onClick={() => verifyJob.mutate(job.id)}
          disabled={verifyJob.isPending || isVerifying}
        >
          {isVerifying ? (
            <>
              <Loader2 className="h-3.5 w-3.5 animate-spin" /> Checking…
            </>
          ) : verification || fraud ? (
            'Re-check'
          ) : (
            'Verify employer & check for fraud'
          )}
        </Button>
      </CardHeader>
      <CardContent className="space-y-3 text-sm">
        {verifyJob.isError && (
          <ErrorState
            message={verifyJob.error instanceof Error ? verifyJob.error.message : 'Failed to start'}
          />
        )}
        {isVerifying && (
          <p className="text-muted-foreground">
            Researching the employer against real sources. This can take up to a minute.
          </p>
        )}
        {!verification && !fraud && !isVerifying && (
          <p className="text-muted-foreground">
            Not checked yet. Verification researches whether the employer is real; the fraud check
            looks for scam patterns in the posting itself.
          </p>
        )}
        {verification && (
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <VerificationBadge status={verification.verification_status} />
              <span className="text-xs text-muted-foreground">
                checked {new Date(verification.checked_at).toLocaleDateString()}
              </span>
            </div>
            <p className="text-muted-foreground">{verification.rationale}</p>
          </div>
        )}
        {fraud && (
          <div className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <FraudBadge level={fraud.risk_level} />
              {fraud.risk_level === 'low' && (
                <span className="text-xs text-muted-foreground">Low fraud risk</span>
              )}
            </div>
            {fraud.signals.length === 0 ? (
              <p className="text-muted-foreground">No scam patterns were found in this posting.</p>
            ) : (
              <ul className="list-disc space-y-1 pl-4 text-muted-foreground">
                {fraud.signals.map((signal) => (
                  <li key={signal.code}>{signal.description}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  )
}

interface JobDetailProps {
  job: CareerJob | null
}

export function JobDetail({ job }: JobDetailProps) {
  const matchJob = useMatchJob()
  const verifyingIds = useVerifyingJobIds()
  const { data: applications } = useApplications()
  const trackJob = useTrackJob()

  if (!job) {
    return (
      <Card>
        <CardContent className="pt-6">
          <EmptyState
            icon={<Briefcase className="h-8 w-8" />}
            title="No job selected"
            description="Add a posting above, or pick one from your list."
          />
        </CardContent>
      </Card>
    )
  }

  const application = applications?.find((a) => a.job_posting_id === job.id)
  const salary = formatSalary(job)
  const meta = [
    job.company_name,
    job.location,
    job.remote_type !== 'unknown' ? job.remote_type : null,
    salary,
  ].filter(Boolean)

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{job.title ?? 'Untitled posting'}</CardTitle>
          {meta.length > 0 && <p className="text-sm text-muted-foreground">{meta.join(' · ')}</p>}
          {job.source_url && (
            <a
              href={job.source_url}
              target="_blank"
              rel="noreferrer noopener"
              className="inline-flex w-fit items-center gap-1 text-xs text-muted-foreground underline-offset-4 hover:underline"
            >
              View original <ExternalLink className="h-3 w-3" />
            </a>
          )}
        </CardHeader>
        {job.description_text && (
          <CardContent>
            <details>
              <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
                Show posting text
              </summary>
              <p className="mt-2 max-h-72 overflow-y-auto whitespace-pre-wrap text-sm text-muted-foreground">
                {job.description_text}
              </p>
            </details>
          </CardContent>
        )}
      </Card>

      <Card>
        <CardContent className="flex flex-wrap items-center justify-between gap-3 pt-6 text-sm">
          {application ? (
            <>
              <span className="flex items-center gap-2">
                You&apos;re tracking this application: <ApplicationStatusBadge status={application.status} />
              </span>
              <Button asChild variant="outline" size="sm">
                <Link to={`/applications?selected=${application.id}`}>View application</Link>
              </Button>
            </>
          ) : (
            <>
              <span className="text-muted-foreground">
                Applying? Track it to keep a dated record of where it stands.
              </span>
              <Button
                variant="outline"
                size="sm"
                onClick={() => trackJob.mutate(job.id)}
                disabled={trackJob.isPending}
              >
                {trackJob.isPending ? 'Starting…' : 'Track this application'}
              </Button>
            </>
          )}
        </CardContent>
        {trackJob.isError && (
          <CardContent>
            <ErrorState
              message={trackJob.error instanceof Error ? trackJob.error.message : 'Failed to start tracking'}
            />
          </CardContent>
        )}
      </Card>

      <MatchPanel
        job={job}
        onRematch={() => matchJob.mutate(job.id)}
        isStarting={matchJob.isPending}
      />
      {matchJob.isError && (
        <ErrorState
          message={matchJob.error instanceof Error ? matchJob.error.message : 'Failed to start match'}
        />
      )}

      <TailorPanel job={job} />

      <CoverPanel job={job} />

      <VerificationSection job={job} isVerifying={verifyingIds.has(job.id)} />
    </div>
  )
}
