import { AlertTriangle, CheckCircle2, Download, HelpCircle, XCircle } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { AtsCheck, AtsCheckItem, AtsKeyword } from '@/lib/api'

const STATUS_ICON = {
  pass: <CheckCircle2 className="h-4 w-4 text-primary" aria-label="Passed" />,
  warn: <AlertTriangle className="h-4 w-4 text-warning-foreground" aria-label="Needs attention" />,
  fail: <XCircle className="h-4 w-4 text-destructive" aria-label="Failed" />,
} as const

function CoverageMeter({ percent }: { percent: number }) {
  return (
    <div
      role="progressbar"
      aria-valuenow={percent}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label="Keyword coverage"
      className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
    >
      <div className="h-full rounded-full bg-primary" style={{ width: `${percent}%` }} />
    </div>
  )
}

function KeywordRow({ keyword }: { keyword: AtsKeyword }) {
  return (
    <li className="space-y-1 rounded-md border border-border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{keyword.name}</span>
        <Badge variant="outline">{keyword.kind}</Badge>
      </div>
      <p className="text-muted-foreground">{keyword.detail}</p>
    </li>
  )
}

function CheckRow({ check }: { check: AtsCheckItem }) {
  return (
    <li className="flex gap-3 rounded-md border border-border p-3 text-sm">
      <span className="mt-0.5 shrink-0">{STATUS_ICON[check.status]}</span>
      <div className="space-y-0.5">
        <p className="font-medium">{check.label}</p>
        <p className="text-muted-foreground">{check.detail}</p>
      </div>
    </li>
  )
}

interface AtsResultsProps {
  result: AtsCheck
  onDownloadSafe: () => void
  isBusy: boolean
  notice: string | null
}

export function AtsResults({ result, onDownloadSafe, isBusy, notice }: AtsResultsProps) {
  const { keyword_stats: stats } = result
  const inContext = result.keywords.filter((k) => k.state === 'in_context')
  const listedOnly = result.keywords.filter((k) => k.state === 'listed_only')
  const gaps = result.keywords.filter((k) => k.state === 'gap')
  const checkedLabel =
    result.resume_source === 'tailored'
      ? `your tailored resume (${result.accepted_changes} accepted change${result.accepted_changes === 1 ? '' : 's'})`
      : 'the resume built from your profile'

  return (
    <div className="space-y-5">
      <p className="text-sm text-muted-foreground">Checked: {checkedLabel}.</p>

      <section className="space-y-3" aria-label="Keyword coverage">
        <h4 className="text-sm font-medium">Keyword coverage</h4>
        {stats.coverage_percent === null ? (
          <p className="text-sm text-muted-foreground">
            This posting didn&apos;t list any skills to check against, so there&apos;s no coverage number.
          </p>
        ) : (
          <div className="space-y-2">
            <div className="flex items-baseline gap-2">
              <span className="text-3xl font-semibold tabular-nums">{stats.coverage_percent}%</span>
              <span className="text-sm text-muted-foreground">of the skills it asks for appear on your resume</span>
            </div>
            <CoverageMeter percent={stats.coverage_percent} />
            <p className="text-xs text-muted-foreground">
              Required {stats.required_found} of {stats.required_total} · Preferred {stats.preferred_found}{' '}
              of {stats.preferred_total} · {stats.in_context} used in context
            </p>
          </div>
        )}

        {inContext.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Used in context
            </p>
            <ul className="flex flex-wrap gap-1.5" aria-label="Skills used in context">
              {inContext.map((k) => (
                <li key={k.name}>
                  <Badge>{k.name}</Badge>
                </li>
              ))}
            </ul>
          </div>
        )}

        {listedOnly.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">
              Only in your Skills list
            </p>
            <ul className="space-y-2">
              {listedOnly.map((k) => (
                <KeywordRow key={k.name} keyword={k} />
              ))}
            </ul>
          </div>
        )}

        {gaps.length > 0 && (
          <Alert>
            <HelpCircle className="h-4 w-4" />
            <AlertTitle>Not on your resume</AlertTitle>
            <AlertDescription>
              <p>
                These are never added for you. If you genuinely have one, record it with evidence on your
                Profile page first.
              </p>
              <ul className="mt-2 space-y-2">
                {gaps.map((k) => (
                  <li key={k.name}>
                    <span className="font-medium">{k.name}</span>{' '}
                    <Badge variant="outline">{k.kind}</Badge>
                    <span className="block text-muted-foreground">{k.detail}</span>
                  </li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}
      </section>

      <section className="space-y-3" aria-label="Structure checks">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h4 className="text-sm font-medium">Structure &amp; parsing</h4>
          <p className="text-xs text-muted-foreground">
            {result.summary.passed} passed · {result.summary.warn} to review · {result.summary.fail} failed
          </p>
        </div>
        <ul className="space-y-2">
          {result.checks.map((check) => (
            <CheckRow key={check.key} check={check} />
          ))}
        </ul>
      </section>

      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" size="sm" onClick={onDownloadSafe} disabled={isBusy}>
          <Download className="h-3.5 w-3.5" /> Download ATS-safe version
        </Button>
        <span className={cn('text-xs text-muted-foreground')}>
          {notice ??
            'Plain text with standard headings and no special symbols. It still needs your contact details.'}
        </span>
      </div>

      <details className="rounded-lg border border-border p-4">
        <summary className="cursor-pointer text-sm font-medium">What this can&apos;t tell you</summary>
        <ul className="mt-3 list-disc space-y-1.5 pl-4 text-sm text-muted-foreground">
          {result.limitations.map((item, index) => (
            <li key={index}>{item}</li>
          ))}
        </ul>
      </details>
    </div>
  )
}
