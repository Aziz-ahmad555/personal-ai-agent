import { AlertTriangle, CheckCircle2, HelpCircle, Loader2, ShieldAlert, XCircle } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type {
  EmployerVerificationStatus,
  FraudRiskLevel,
  JobMatch,
} from '@/lib/api'

/** Compact match indicator for the job list. A score that rests on little evidence carries a
 * visible "low confidence" flag right beside the number, so the number is never seen bare. */
export function MatchBadge({ match }: { match: JobMatch | null }) {
  if (!match) {
    return (
      <Badge variant="outline" className="text-muted-foreground">
        Not matched
      </Badge>
    )
  }
  if (match.status === 'running') {
    return (
      <Badge variant="secondary" className="gap-1">
        <Loader2 className="h-3 w-3 animate-spin" /> Matching
      </Badge>
    )
  }
  if (match.status === 'failed') {
    return (
      <Badge variant="outline" className="border-destructive/50 text-destructive">
        Match failed
      </Badge>
    )
  }
  if (match.score_percent === null) {
    return (
      <Badge variant="outline" className="gap-1 text-muted-foreground">
        <HelpCircle className="h-3 w-3" /> Can&apos;t score
      </Badge>
    )
  }
  if (match.low_confidence) {
    return (
      <Badge
        variant="outline"
        className="gap-1 border-dashed border-warning/70 text-warning-foreground"
        title={`Only ${match.assessed_weight} of 100 points could be assessed`}
      >
        <AlertTriangle className="h-3 w-3" />
        {match.score_percent}% · low confidence
      </Badge>
    )
  }
  return <Badge>{match.score_percent}% match</Badge>
}

const VERIFICATION_LABEL: Record<EmployerVerificationStatus, string> = {
  verified: 'Employer verified',
  unconfirmed: 'Employer unconfirmed',
  suspicious: 'Employer suspicious',
}

export function VerificationBadge({ status }: { status: EmployerVerificationStatus | undefined }) {
  if (!status) return null
  if (status === 'verified') {
    return (
      <Badge variant="secondary" className="gap-1">
        <CheckCircle2 className="h-3 w-3" /> {VERIFICATION_LABEL[status]}
      </Badge>
    )
  }
  if (status === 'suspicious') {
    return (
      <Badge variant="outline" className="gap-1 border-destructive/50 text-destructive">
        <XCircle className="h-3 w-3" /> {VERIFICATION_LABEL[status]}
      </Badge>
    )
  }
  return (
    <Badge variant="outline" className="gap-1 text-muted-foreground">
      <HelpCircle className="h-3 w-3" /> {VERIFICATION_LABEL[status]}
    </Badge>
  )
}

export function FraudBadge({ level }: { level: FraudRiskLevel | undefined }) {
  // Low risk is the unremarkable case — only surface what needs attention.
  if (!level || level === 'low') return null
  return (
    <Badge
      variant="outline"
      className={cn(
        'gap-1',
        level === 'high'
          ? 'border-destructive/50 text-destructive'
          : 'border-warning/70 text-warning-foreground'
      )}
    >
      <ShieldAlert className="h-3 w-3" /> {level === 'high' ? 'High' : 'Medium'} fraud risk
    </Badge>
  )
}

/** How much of the 100 points could actually be measured. */
export function CoverageMeter({ assessed, low }: { assessed: number; low: boolean }) {
  return (
    <div className="space-y-1">
      <div
        role="progressbar"
        aria-valuenow={assessed}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label="Share of the match that could be assessed"
        className="h-1.5 w-full overflow-hidden rounded-full bg-muted"
      >
        <div
          className={cn('h-full rounded-full', low ? 'bg-warning' : 'bg-primary')}
          style={{ width: `${assessed}%` }}
        />
      </div>
      <p className="text-xs text-muted-foreground">
        {assessed} of 100 points could be assessed
      </p>
    </div>
  )
}
