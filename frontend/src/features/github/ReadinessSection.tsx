import { useState } from 'react'
import { AlertTriangle, CheckCircle2, ClipboardCopy, HelpCircle, XCircle } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/layout/error-state'
import type { GithubCheck, GithubCheckStatus, GithubFix, GithubRepoReview } from '@/lib/api'
import { useExportReadiness, useGithubReadiness } from '@/features/github/hooks'

const STATUS_ICON: Record<GithubCheckStatus, React.ReactElement> = {
  pass: <CheckCircle2 className="h-4 w-4 text-primary" aria-label="Passed" />,
  warn: <AlertTriangle className="h-4 w-4 text-warning-foreground" aria-label="Needs attention" />,
  fail: <XCircle className="h-4 w-4 text-destructive" aria-label="Failed" />,
  unknown: <HelpCircle className="h-4 w-4 text-muted-foreground" aria-label="Unknown" />,
}

export function CheckRow({ check }: { check: GithubCheck }) {
  return (
    <li className="flex gap-3 text-sm">
      <span className="mt-0.5 shrink-0">{STATUS_ICON[check.status]}</span>
      <div className="min-w-0 space-y-0.5">
        <p className="font-medium">{check.label}</p>
        <p className="text-muted-foreground">
          {check.detail}
          {check.evidence_url && (
            <>
              {' '}
              <a
                href={check.evidence_url}
                target="_blank"
                rel="noreferrer"
                className="underline-offset-4 hover:underline"
              >
                View
              </a>
            </>
          )}
        </p>
        {check.fix && <p className="text-xs">{check.fix}</p>}
      </div>
    </li>
  )
}

function summary(review: GithubRepoReview): string {
  const unknown = review.unknown ? ` · ${review.unknown} unknown` : ''
  return `${review.passed} of ${review.total} pass${unknown}`
}

function RepoReview({ review }: { review: GithubRepoReview }) {
  return (
    <details className="rounded-md border border-border p-3">
      <summary className="cursor-pointer text-sm">
        <span className="font-medium">{review.name}</span>
        <span className="text-muted-foreground">
          {' '}
          — {review.reviewed ? summary(review) : `not reviewed`}
        </span>
      </summary>
      <div className="mt-3 space-y-3">
        <a
          href={review.html_url}
          target="_blank"
          rel="noreferrer"
          className="text-xs text-muted-foreground underline-offset-4 hover:underline"
        >
          Open on GitHub
        </a>
        {review.reviewed ? (
          <ul className="space-y-3" aria-label={`Checks for ${review.name}`}>
            {review.checks.map((check) => (
              <CheckRow key={check.key} check={check} />
            ))}
          </ul>
        ) : (
          <p className="text-sm text-muted-foreground">Not reviewed: {review.reason}</p>
        )}
      </div>
    </details>
  )
}

function FixRow({ fix }: { fix: GithubFix }) {
  return (
    <li className="flex gap-3 text-sm">
      <span className="mt-0.5 shrink-0">{STATUS_ICON[fix.status]}</span>
      <div className="min-w-0 space-y-0.5">
        <p className="font-medium">
          {fix.repo ? (
            <a
              href={fix.repo_url ?? undefined}
              target="_blank"
              rel="noreferrer"
              className="underline-offset-4 hover:underline"
            >
              {fix.repo}
            </a>
          ) : (
            'Your profile'
          )}
          <span className="font-normal text-muted-foreground"> — {fix.label}</span>
        </p>
        <p className="text-muted-foreground">{fix.detail}</p>
        <p>{fix.fix}</p>
      </div>
    </li>
  )
}

export function ReadinessSection() {
  const { data, isLoading, isError, error, refetch } = useGithubReadiness()
  const exporter = useExportReadiness()
  const [copyState, setCopyState] = useState<'idle' | 'copied' | 'failed'>('idle')
  const [manualText, setManualText] = useState<string | null>(null)

  async function copyChecklist() {
    setCopyState('idle')
    setManualText(null)
    try {
      const { text } = await exporter.mutateAsync()
      try {
        await navigator.clipboard.writeText(text)
        setCopyState('copied')
      } catch {
        // No clipboard access (an insecure page, or the browser said no): show the text instead.
        setManualText(text)
        setCopyState('failed')
      }
    } catch {
      setCopyState('idle') // the mutation's own error is shown below
    }
  }

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-3 space-y-0">
        <div className="space-y-1">
          <CardTitle className="text-base">Recruiter-readiness</CardTitle>
          <CardDescription>
            What a visitor needs from your repositories: what it is, whether it runs, whether it&apos;s
            maintained, whether it can be reused. Checked from what the last sync read.
          </CardDescription>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void copyChecklist()}
          disabled={!data?.synced || exporter.isPending}
          className="shrink-0"
        >
          <ClipboardCopy className="h-4 w-4" />
          {exporter.isPending ? 'Preparing…' : copyState === 'copied' ? 'Copied' : 'Copy as checklist'}
        </Button>
      </CardHeader>
      <CardContent className="space-y-5">
        {isLoading && <Skeleton className="h-32 w-full" />}
        {isError && (
          <ErrorState
            message={error instanceof Error ? error.message : 'Failed to load the review'}
            onRetry={() => refetch()}
          />
        )}
        {exporter.isError && (
          <ErrorState
            title="Couldn't prepare the checklist"
            message={exporter.error instanceof Error ? exporter.error.message : 'Export failed'}
          />
        )}
        {manualText && (
          <div className="space-y-1.5">
            <p className="text-sm text-muted-foreground">
              Your browser blocked copying, so here is the checklist to copy by hand.
            </p>
            <textarea
              readOnly
              aria-label="Checklist text"
              value={manualText}
              className="h-40 w-full rounded-md border border-input bg-transparent p-2 text-xs"
            />
          </div>
        )}

        {data && !data.synced && (
          <p className="rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
            Nothing to review yet. Sync your repositories first.
          </p>
        )}

        {data?.needs_resync && (
          <Alert>
            <AlertTitle>Some checks are unknown</AlertTitle>
            <AlertDescription>
              Your last sync was made before these checks existed, so they can&apos;t say yet. Sync again to
              include them.
            </AlertDescription>
          </Alert>
        )}

        {data?.synced && (
          <>
            <section className="space-y-3" aria-label="Fix first">
              <h4 className="text-sm font-medium">Fix first</h4>
              {data.fixes.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Nothing to fix from what could be checked.
                  {data.repos.some((repo) => repo.unknown > 0) &&
                    ' Some checks are unknown, so this may not be everything.'}
                </p>
              ) : (
                <ol className="space-y-3">
                  {data.fixes.map((fix) => (
                    <FixRow key={`${fix.repo ?? 'profile'}-${fix.check_key}`} fix={fix} />
                  ))}
                </ol>
              )}
            </section>

            <section className="space-y-2" aria-label="Repositories reviewed">
              <h4 className="text-sm font-medium">Repositories</h4>
              {data.repos.map((review) => (
                <RepoReview key={review.name} review={review} />
              ))}
            </section>

            <section className="space-y-3" aria-label="Your profile">
              <h4 className="text-sm font-medium">Your GitHub profile</h4>
              <ul className="space-y-3">
                {data.profile.map((check) => (
                  <CheckRow key={check.key} check={check} />
                ))}
              </ul>
            </section>

            <details className="rounded-md border border-border p-3">
              <summary className="cursor-pointer text-sm font-medium">What this can&apos;t tell you</summary>
              <ul className="mt-3 list-disc space-y-1.5 pl-4 text-sm text-muted-foreground">
                {data.limitations.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </details>
          </>
        )}
      </CardContent>
    </Card>
  )
}
