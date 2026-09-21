import { CheckCircle2, XCircle } from 'lucide-react'
import type { ResearchSource } from '@/lib/api'
import { TierBadge } from '@/features/research/badges'

interface SourcesListProps {
  sources: ResearchSource[]
  highlightedAnchor?: string | null
}

export function SourcesList({ sources, highlightedAnchor = null }: SourcesListProps) {
  if (sources.length === 0) return null

  return (
    <ul className="space-y-2">
      {sources.map((source) => (
        <li
          key={source.id}
          id={`source-${source.id}`}
          className={
            'flex scroll-mt-24 flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2 text-xs transition-colors ' +
            (highlightedAnchor === `source-${source.id}` ? 'border-ring bg-accent' : 'border-border')
          }
        >
          <div className="flex min-w-0 items-center gap-2">
            <TierBadge tier={source.tier} />
            <a
              href={source.original_url}
              target="_blank"
              rel="noreferrer"
              className="truncate underline-offset-2 hover:underline"
              title={source.original_url}
            >
              {source.title || source.domain}
            </a>
          </div>
          <div className="flex items-center gap-1 whitespace-nowrap text-muted-foreground">
            {source.fetch_error ? (
              <span className="flex items-center gap-1 text-destructive">
                <XCircle className="h-3 w-3" /> {source.fetch_error}
              </span>
            ) : (
              <span className="flex items-center gap-1">
                <CheckCircle2 className="h-3 w-3" />
                fetched {source.fetched_at ? new Date(source.fetched_at).toLocaleString() : 'unknown'}
              </span>
            )}
          </div>
        </li>
      ))}
    </ul>
  )
}
