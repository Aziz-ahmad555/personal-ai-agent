import { useMemo } from 'react'
import type { ReactNode } from 'react'

interface ReportSummaryProps {
  summary: string
  claimIds: string[]
  onJumpToClaim: (claimId: string) => void
}

/**
 * The stored summary has literal `[c1]`, `[c2]`… markers with no persisted mapping back to
 * real claim ids — only `claimIds`, the list of real claim UUIDs in the exact order those
 * markers first resolved server-side (see app/research/pipeline.py's report_node). Marker
 * occurrence order and claimIds order are produced by the same left-to-right pass over the
 * same text there, so zipping them here recovers which claim each rendered marker points
 * to without the backend needing to persist the mapping itself. If the two ever don't line
 * up (should not happen, but never trust that blindly), the marker just renders as plain
 * text instead of guessing a link.
 */
export function ReportSummary({ summary, claimIds, onJumpToClaim }: ReportSummaryProps) {
  const nodes = useMemo(() => {
    const result: ReactNode[] = []
    let lastIndex = 0
    let occurrence = 0
    let match: RegExpExecArray | null
    const markerRe = /\[([a-zA-Z0-9_-]+)\]/g

    while ((match = markerRe.exec(summary)) !== null) {
      result.push(summary.slice(lastIndex, match.index))
      const claimId = claimIds[occurrence]
      occurrence += 1
      if (claimId) {
        result.push(
          <button
            key={match.index}
            type="button"
            onClick={() => onJumpToClaim(claimId)}
            className="mx-0.5 inline-flex h-4 min-w-4 items-center justify-center rounded bg-secondary px-1 align-super text-[10px] font-semibold text-secondary-foreground hover:bg-accent"
            title="Jump to the claim behind this"
          >
            {occurrence}
          </button>
        )
      } else {
        result.push(match[0])
      }
      lastIndex = match.index + match[0].length
    }
    result.push(summary.slice(lastIndex))
    return result
  }, [summary, claimIds, onJumpToClaim])

  return <p className="text-sm leading-relaxed">{nodes}</p>
}
