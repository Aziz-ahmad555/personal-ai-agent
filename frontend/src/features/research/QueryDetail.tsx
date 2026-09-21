import { useEffect, useRef, useState } from 'react'
import { AlertTriangle, HelpCircle, Loader2, SearchCheck } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/layout/empty-state'
import { ErrorState } from '@/components/layout/error-state'
import { useResearchQueryDetail } from '@/features/research/hooks'
import { ClaimCard } from '@/features/research/ClaimCard'
import { ReportSummary } from '@/features/research/ReportSummary'
import { SourcesList } from '@/features/research/SourcesList'

interface QueryDetailProps {
  queryId: string | null
  /** A DOM anchor id (e.g. "claim-<uuid>" or "source-<uuid>") to scroll to and briefly
   * highlight once the query's data has loaded — used when arriving here from a Search
   * result deep link, not from an in-page citation-marker click. */
  initialAnchor?: string | null
}

export function QueryDetail({ queryId, initialAnchor = null }: QueryDetailProps) {
  const [highlightedAnchor, setHighlightedAnchor] = useState<string | null>(null)
  const { data: query, isLoading, isError, error, refetch } = useResearchQueryDetail(queryId)
  const appliedInitialAnchorFor = useRef<string | null>(null)

  function jumpToAnchor(anchorId: string) {
    setHighlightedAnchor(anchorId)
    document.getElementById(anchorId)?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    window.setTimeout(
      () => setHighlightedAnchor((current) => (current === anchorId ? null : current)),
      2000
    )
  }

  // Applies the deep-linked anchor once per queryId, as soon as its data (and therefore
  // the target element) is actually on the page — not on every poll refetch.
  useEffect(() => {
    if (!query || !initialAnchor || appliedInitialAnchorFor.current === queryId) return
    appliedInitialAnchorFor.current = queryId
    jumpToAnchor(initialAnchor)
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [query, initialAnchor, queryId])

  if (queryId === null) {
    return (
      <Card>
        <CardContent className="pt-6">
          <EmptyState
            icon={<SearchCheck className="h-8 w-8" />}
            title="No query selected"
            description="Run a new query above, or pick one from your history."
          />
        </CardContent>
      </Card>
    )
  }

  if (isLoading) {
    return (
      <Card>
        <CardContent className="space-y-3 pt-6">
          <Skeleton className="h-6 w-2/3" />
          <Skeleton className="h-24 w-full" />
          <Skeleton className="h-24 w-full" />
        </CardContent>
      </Card>
    )
  }

  if (isError || !query) {
    return (
      <Card>
        <CardContent className="pt-6">
          <ErrorState
            message={error instanceof Error ? error.message : 'Failed to load this query'}
            onRetry={() => refetch()}
          />
        </CardContent>
      </Card>
    )
  }

  const sourcesById = new Map(query.sources.map((s) => [s.id, s]))
  const isActive = query.status === 'pending' || query.status === 'running'

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader>
          <CardTitle className="text-base">{query.query_text}</CardTitle>
          {query.purpose && <p className="text-sm text-muted-foreground">{query.purpose}</p>}
        </CardHeader>
        {isActive && (
          <CardContent>
            <div className="flex items-center gap-2 rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
              <Loader2 className="h-4 w-4 animate-spin" />
              Researching — searching sources, verifying them, and cross-checking claims. This can take up
              to a minute.
            </div>
          </CardContent>
        )}
        {query.status === 'failed' && (
          <CardContent>
            <ErrorState title="Research failed" message={query.error ?? 'Unknown error'} />
          </CardContent>
        )}
      </Card>

      {query.sources.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Sources ({query.sources.length})</CardTitle>
          </CardHeader>
          <CardContent>
            <SourcesList sources={query.sources} highlightedAnchor={highlightedAnchor} />
          </CardContent>
        </Card>
      )}

      {query.report && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Report</CardTitle>
            <p className="text-xs text-muted-foreground">
              {query.report.model_used && `${query.report.model_used} · `}
              generated {new Date(query.report.generated_at).toLocaleString()}
            </p>
          </CardHeader>
          <CardContent className="space-y-4">
            <ReportSummary
              summary={query.report.summary}
              claimIds={query.report.claim_ids}
              onJumpToClaim={(claimId) => jumpToAnchor(`claim-${claimId}`)}
            />

            {query.report.uncertainties.length > 0 && (
              <Alert>
                <HelpCircle className="h-4 w-4" />
                <AlertTitle>Open questions</AlertTitle>
                <AlertDescription>
                  <ul className="list-disc space-y-1 pl-4">
                    {query.report.uncertainties.map((item, index) => (
                      <li key={index}>{item}</li>
                    ))}
                  </ul>
                </AlertDescription>
              </Alert>
            )}
          </CardContent>
        </Card>
      )}

      {query.status === 'completed' && query.claims.length === 0 && (
        <EmptyState
          icon={<AlertTriangle className="h-6 w-6" />}
          title="No claims could be verified"
          description="No source held up well enough to support a claim — see the report above for what's missing."
        />
      )}

      {query.claims.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle className="text-base">Claims ({query.claims.length})</CardTitle>
          </CardHeader>
          <CardContent className="space-y-3">
            {query.claims.map((claim) => (
              <ClaimCard
                key={claim.id}
                claim={claim}
                sourcesById={sourcesById}
                highlighted={highlightedAnchor === `claim-${claim.id}`}
              />
            ))}
          </CardContent>
        </Card>
      )}
    </div>
  )
}
