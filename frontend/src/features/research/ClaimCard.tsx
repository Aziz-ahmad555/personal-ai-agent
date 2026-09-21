import type { ResearchClaim, ResearchSource } from '@/lib/api'
import { ClaimStatusBadge, ConfidenceMeter, ExcerptVerifiedIcon, TierBadge } from '@/features/research/badges'

interface ClaimCardProps {
  claim: ResearchClaim
  sourcesById: Map<string, ResearchSource>
  highlighted: boolean
}

export function ClaimCard({ claim, sourcesById, highlighted }: ClaimCardProps) {
  return (
    <div
      id={`claim-${claim.id}`}
      className={
        'scroll-mt-24 rounded-md border p-4 transition-colors ' +
        (highlighted ? 'border-ring bg-accent' : 'border-border')
      }
    >
      <div className="flex items-start justify-between gap-3">
        <p className="text-sm font-medium">{claim.claim_text}</p>
        <ClaimStatusBadge status={claim.status} />
      </div>

      <div className="mt-2 flex items-center gap-2">
        <ConfidenceMeter value={claim.confidence_score} />
        <span className="text-xs text-muted-foreground">{claim.confidence_score}% confidence</span>
      </div>
      <p className="mt-1.5 text-xs text-muted-foreground">{claim.confidence_rationale}</p>

      {claim.citations.length > 0 && (
        <ul className="mt-3 space-y-2.5 border-l border-border pl-3">
          {claim.citations.map((citation) => {
            const source = sourcesById.get(citation.source_id)
            return (
              <li key={citation.id} className="text-xs">
                <div className="flex flex-wrap items-center gap-1.5 text-muted-foreground">
                  <ExcerptVerifiedIcon verified={citation.excerpt_verified} />
                  <TierBadge tier={source?.tier} />
                  {source && (
                    <a
                      href={source.original_url}
                      target="_blank"
                      rel="noreferrer"
                      className="truncate underline-offset-2 hover:underline"
                    >
                      {source.domain}
                    </a>
                  )}
                  <span className="capitalize">· {citation.stance.replace('_', ' ')}</span>
                </div>
                <p className="mt-0.5 italic text-foreground/80">&ldquo;{citation.excerpt}&rdquo;</p>
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}
