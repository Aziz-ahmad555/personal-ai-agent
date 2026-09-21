import { AlertTriangle, CheckCheck, CheckCircle2, HelpCircle, XCircle } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { cn } from '@/lib/utils'
import type { ClaimStatus, SourceTier } from '@/lib/api'

const STATUS_LABEL: Record<ClaimStatus, string> = {
  corroborated: 'Corroborated',
  single_source: 'Single source',
  contradicted: 'Contradicted',
  unverified: 'Unverified',
}

export function ClaimStatusBadge({ status }: { status: ClaimStatus }) {
  if (status === 'corroborated') {
    return (
      <Badge className="gap-1">
        <CheckCheck className="h-3 w-3" /> {STATUS_LABEL[status]}
      </Badge>
    )
  }
  if (status === 'contradicted') {
    return (
      <Badge variant="outline" className="gap-1 border-destructive/50 text-destructive">
        <XCircle className="h-3 w-3" /> {STATUS_LABEL[status]}
      </Badge>
    )
  }
  if (status === 'unverified') {
    return (
      <Badge variant="outline" className="gap-1 text-muted-foreground">
        <HelpCircle className="h-3 w-3" /> {STATUS_LABEL[status]}
      </Badge>
    )
  }
  return <Badge variant="secondary">{STATUS_LABEL[status]}</Badge>
}

const TIER_LABEL: Record<SourceTier, string> = {
  official: 'Official',
  government: 'Government',
  docs: 'Docs',
  reputable_secondary: 'Reputable secondary',
  forum_anecdotal: 'Forum (anecdotal)',
  unknown: 'Unranked',
}

export function TierBadge({ tier }: { tier: SourceTier | undefined }) {
  if (!tier) return null
  return (
    <Badge variant="outline" className="whitespace-nowrap text-[11px]">
      {TIER_LABEL[tier]}
    </Badge>
  )
}

export function ConfidenceMeter({ value }: { value: number }) {
  return (
    <div
      role="progressbar"
      aria-valuenow={value}
      aria-valuemin={0}
      aria-valuemax={100}
      aria-label="Confidence score"
      className="h-1.5 w-20 overflow-hidden rounded-full bg-muted"
    >
      <div
        className={cn('h-full rounded-full', value === 0 ? 'bg-muted-foreground/30' : 'bg-primary')}
        style={{ width: `${value}%` }}
      />
    </div>
  )
}

export function ExcerptVerifiedIcon({ verified }: { verified: boolean }) {
  return verified ? (
    <CheckCircle2 className="h-3 w-3 shrink-0 text-muted-foreground" aria-label="Excerpt verified against source" />
  ) : (
    <AlertTriangle className="h-3 w-3 shrink-0 text-destructive" aria-label="Excerpt could not be verified against source" />
  )
}
