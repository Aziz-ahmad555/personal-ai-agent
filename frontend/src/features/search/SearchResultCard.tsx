import { useNavigate } from 'react-router-dom'
import type { SearchResult } from '@/lib/api'
import { ResultTypeBadge } from '@/features/search/badges'

export function SearchResultCard({ result }: { result: SearchResult }) {
  const navigate = useNavigate()

  const href =
    result.link.kind === 'profile'
      ? '/profile'
      : result.link.query_id
        ? `/research?query=${result.link.query_id}${result.link.anchor ? `&anchor=${result.link.anchor}` : ''}`
        : null

  const content = (
    <>
      <div className="flex items-center gap-2">
        <ResultTypeBadge type={result.type} />
        <p className="truncate text-sm font-medium">{result.title}</p>
      </div>
      <p className="mt-1.5 text-sm text-muted-foreground">{result.snippet}</p>
    </>
  )

  if (href === null) {
    // A research source whose owning query couldn't be resolved (shouldn't happen today —
    // queries aren't deletable — but degrade to unclickable rather than a broken link).
    return <div className="rounded-md border border-border p-4 opacity-70">{content}</div>
  }

  return (
    <button
      type="button"
      onClick={() => navigate(href)}
      className="w-full rounded-md border border-border p-4 text-left transition-colors hover:bg-accent"
    >
      {content}
    </button>
  )
}
