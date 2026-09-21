import { AlertTriangle, Gauge, HelpCircle, Loader2, RefreshCw, ShieldAlert } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorState } from '@/components/layout/error-state'
import { cn } from '@/lib/utils'
import type {
  CareerJob,
  JobMatch,
  MatchComponent,
  MatchDetail,
} from '@/lib/api'
import { CoverageMeter } from '@/features/career/badges'

function text(value: unknown): string | null {
  return typeof value === 'string' && value.trim() ? value : null
}

const MATCH_TYPE_LABEL: Record<string, string> = {
  exact: 'Match',
  similar: 'Similar',
  missing: 'Missing',
}

function DetailRow({ detail }: { detail: MatchDetail }) {
  const requirement = text(detail.requirement) ?? text(detail.check) ?? text(detail.posting_industry)
  const matchType = text(detail.match_type)
  const quote = text(detail.quote)
  const profileSkill = text(detail.profile_skill)
  const evidence = text(detail.evidence)
  const note = text(detail.note)
  const level = text(detail.level)
  const similarity = typeof detail.similarity === 'number' ? detail.similarity : null

  return (
    <li className="space-y-1 rounded-md border border-border p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        {requirement && <span className="font-medium">{requirement}</span>}
        {matchType && (
          <Badge
            variant={matchType === 'exact' ? 'default' : 'outline'}
            className={cn(matchType === 'missing' && 'border-destructive/50 text-destructive')}
          >
            {MATCH_TYPE_LABEL[matchType] ?? matchType}
          </Badge>
        )}
        {profileSkill && matchType !== 'exact' && (
          <span className="text-muted-foreground">
            via your &ldquo;{profileSkill}&rdquo;
            {similarity !== null && ` (similarity ${similarity.toFixed(2)})`}
          </span>
        )}
      </div>
      {text(detail.check) && (
        <p className="text-muted-foreground">
          posting: {text(detail.posting) ?? '—'} · you: {text(detail.preference) ?? '—'}
        </p>
      )}
      {quote && <p className="text-muted-foreground">Posting: &ldquo;{quote}&rdquo;</p>}
      {evidence && (
        <p className="text-muted-foreground">
          Your evidence{level ? ` (${level})` : ''}: {evidence}
        </p>
      )}
      {note && <p className="text-xs text-muted-foreground">{note}</p>}
    </li>
  )
}

function ComponentRow({ component }: { component: MatchComponent }) {
  if (component.status === 'not_assessed') {
    return (
      <li className="rounded-md border border-dashed border-border p-3 text-sm">
        <div className="flex items-center justify-between gap-2">
          <span className="font-medium text-muted-foreground">{component.label}</span>
          <Badge variant="outline" className="gap-1 text-muted-foreground">
            <HelpCircle className="h-3 w-3" /> Not assessed · {component.weight} pts unmeasured
          </Badge>
        </div>
        {component.reason && (
          <p className="mt-1 text-muted-foreground">Couldn&apos;t judge: {component.reason}</p>
        )}
      </li>
    )
  }

  const fraction = component.fraction ?? 0
  return (
    <li className="rounded-md border border-border p-3 text-sm">
      <div className="flex items-center justify-between gap-2">
        <span className="font-medium">{component.label}</span>
        <span className="tabular-nums text-muted-foreground">
          {component.points?.toFixed(1)} / {component.weight}
        </span>
      </div>
      <div
        role="progressbar"
        aria-valuenow={Math.round(fraction * 100)}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`${component.label} score`}
        className="mt-2 h-1.5 overflow-hidden rounded-full bg-muted"
      >
        <div
          className={cn('h-full rounded-full', fraction === 0 ? 'bg-muted-foreground/30' : 'bg-primary')}
          style={{ width: `${fraction * 100}%` }}
        />
      </div>
      <p className="mt-2 text-muted-foreground">{component.summary}</p>
      {component.details.length > 0 && (
        <details className="mt-2">
          <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
            Show evidence ({component.details.length})
          </summary>
          <ul className="mt-2 space-y-2">
            {component.details.map((detail, index) => (
              <DetailRow key={index} detail={detail} />
            ))}
          </ul>
        </details>
      )}
    </li>
  )
}

/** The centerpiece of the low-confidence requirement: when most of the 100 points couldn't be
 * measured, this says so in words, ahead of the number, and names what was left out. */
function LowConfidenceWarning({ match }: { match: JobMatch }) {
  const unmeasured = match.components.filter((c) => c.status === 'not_assessed')
  return (
    <Alert variant="warning">
      <AlertTriangle className="h-4 w-4" />
      <AlertTitle>Low confidence — most components unknown</AlertTitle>
      <AlertDescription className="space-y-2">
        <p>
          Only {match.assessed_weight} of 100 points could be measured for this job.
          {match.score_percent !== null &&
            ` The ${match.score_percent}% below reflects just that slice — treat it as a partial read, not a verdict.`}
        </p>
        {unmeasured.length > 0 && (
          <p>
            Not assessed: {unmeasured.map((c) => c.label.toLowerCase()).join(', ')}. Filling in your
            profile and preferences, or pasting the full posting, usually raises this.
          </p>
        )}
      </AlertDescription>
    </Alert>
  )
}

function ScoreHeader({ match }: { match: JobMatch }) {
  if (match.score_percent === null) {
    return (
      <Alert>
        <HelpCircle className="h-4 w-4" />
        <AlertTitle>Can&apos;t score this job</AlertTitle>
        <AlertDescription>
          Nothing about this posting could be compared to your profile, so there is no score — not a
          zero. See what was missing below.
        </AlertDescription>
      </Alert>
    )
  }
  return (
    <div className="flex items-end gap-4">
      <div className="flex items-baseline gap-1">
        <span
          className={cn(
            'text-4xl font-semibold tabular-nums',
            match.low_confidence && 'text-muted-foreground'
          )}
        >
          {match.score_percent}%
        </span>
        <span className="text-sm text-muted-foreground">
          {match.low_confidence ? 'of what could be measured' : 'match'}
        </span>
      </div>
      <div className="min-w-0 flex-1 pb-1">
        <CoverageMeter assessed={match.assessed_weight} low={match.low_confidence} />
      </div>
    </div>
  )
}

interface MatchPanelProps {
  job: CareerJob
  onRematch: () => void
  isStarting: boolean
}

export function MatchPanel({ job, onRematch, isStarting }: MatchPanelProps) {
  const match = job.match

  if (!match) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-base">
            <Gauge className="h-4 w-4" /> Match to your profile
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          <p>
            Compares this posting&apos;s stated requirements with your evidence-backed skills, work
            history, and preferences. Anything it can&apos;t judge is reported as unknown, not guessed.
          </p>
          <Button onClick={onRematch} disabled={isStarting}>
            {isStarting ? 'Starting…' : 'Match to my profile'}
          </Button>
        </CardContent>
      </Card>
    )
  }

  if (match.status === 'running') {
    return (
      <Card>
        <CardContent className="pt-6">
          <div className="flex items-center gap-2 rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Reading the posting&apos;s requirements and comparing them with your profile…
          </div>
        </CardContent>
      </Card>
    )
  }

  if (match.status === 'failed') {
    return (
      <Card>
        <CardContent className="pt-6">
          <ErrorState
            title="Couldn't compute a match"
            message={match.error ?? 'Unknown error'}
            onRetry={onRematch}
          />
        </CardContent>
      </Card>
    )
  }

  const fraudLevel = job.fraud_assessment?.risk_level
  const employerStatus = job.employer_verification?.verification_status
  const hasDealBreakers = match.deal_breaker_hits.length > 0

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-2 space-y-0">
        <CardTitle className="flex items-center gap-2 text-base">
          <Gauge className="h-4 w-4" /> Match to your profile
        </CardTitle>
        <Button variant="outline" size="sm" onClick={onRematch} disabled={isStarting}>
          <RefreshCw className="h-3.5 w-3.5" /> Re-match
        </Button>
      </CardHeader>
      <CardContent className="space-y-4">
        {match.is_stale && (
          <Alert>
            <RefreshCw className="h-4 w-4" />
            <AlertTitle>Your profile changed since this was computed</AlertTitle>
            <AlertDescription>Re-match to score against your current profile.</AlertDescription>
          </Alert>
        )}

        {match.low_confidence && match.score_percent !== null && <LowConfidenceWarning match={match} />}

        <ScoreHeader match={match} />

        {(fraudLevel === 'high' || fraudLevel === 'medium' || employerStatus === 'suspicious') && (
          <Alert variant="destructive">
            <ShieldAlert className="h-4 w-4" />
            <AlertTitle>Don&apos;t let this score reassure you</AlertTitle>
            <AlertDescription>
              {employerStatus === 'suspicious' && 'The employer verification came back suspicious. '}
              {fraudLevel && fraudLevel !== 'low' && `This posting has ${fraudLevel} fraud risk. `}
              A strong fit on paper says nothing about whether the posting is legitimate.
            </AlertDescription>
          </Alert>
        )}

        {hasDealBreakers && (
          <Alert variant="destructive">
            <AlertTriangle className="h-4 w-4" />
            <AlertTitle>Triggers your deal-breakers</AlertTitle>
            <AlertDescription>
              <ul className="list-disc space-y-1 pl-4">
                {match.deal_breaker_hits.map((hit, index) => (
                  <li key={index}>
                    <span className="font-medium">{hit.deal_breaker}</span> — posting says: &ldquo;
                    {hit.quote}&rdquo;
                  </li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}

        {match.deal_breaker_check === 'unavailable' && (
          <Alert variant="warning">
            <HelpCircle className="h-4 w-4" />
            <AlertTitle>Deal-breakers weren&apos;t checked</AlertTitle>
            <AlertDescription>
              The check failed, so the absence of a warning here does not mean this posting is clear.
              Re-match to try again.
            </AlertDescription>
          </Alert>
        )}

        <ul className="space-y-2">
          {match.components.map((component) => (
            <ComponentRow key={component.key} component={component} />
          ))}
        </ul>

        {match.uncertainties.length > 0 && (
          <Alert>
            <HelpCircle className="h-4 w-4" />
            <AlertTitle>What this doesn&apos;t know</AlertTitle>
            <AlertDescription>
              <ul className="list-disc space-y-1 pl-4">
                {match.uncertainties.map((item, index) => (
                  <li key={index}>{item}</li>
                ))}
              </ul>
            </AlertDescription>
          </Alert>
        )}

        <p className="text-xs text-muted-foreground">
          Computed {new Date(match.computed_at).toLocaleString()}. Requirements are read from the
          posting by an AI model and each is checked against the posting&apos;s text; the scoring itself
          is plain, deterministic code.
        </p>
      </CardContent>
    </Card>
  )
}
