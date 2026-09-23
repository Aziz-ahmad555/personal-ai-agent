import { useState } from 'react'
import { FileText } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/layout/empty-state'
import { ErrorState } from '@/components/layout/error-state'
import { DigestView } from '@/features/reporting/DigestView'
import { useDigest, useDigests, useGenerateDigest } from '@/features/reporting/hooks'

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong'
}

export function DigestPanel() {
  const { data: digests, isLoading, isError, error, refetch } = useDigests()
  const generate = useGenerateDigest()
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const effectiveId = selectedId ?? digests?.[0]?.id ?? null
  const { data: selected } = useDigest(effectiveId)

  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="flex-row items-center justify-between gap-3 space-y-0">
          <CardTitle className="flex items-center gap-2 text-base">
            <FileText className="h-4 w-4" /> Weekly digest
          </CardTitle>
          <Button
            size="sm"
            disabled={generate.isPending}
            onClick={() =>
              generate.mutate(
                { days: 7, lookaheadDays: 14 },
                { onSuccess: (digest) => setSelectedId(digest.id) }
              )
            }
          >
            {generate.isPending ? 'Generating…' : 'Generate digest'}
          </Button>
        </CardHeader>
        <CardContent className="space-y-4">
          <p className="text-sm text-muted-foreground">
            Pulls together what actually happened across Career, Research, Gmail, Calendar, and
            GitHub over the last 7 days, plus anything that needs your attention right now.
            Plain aggregation of your own stored data — nothing here is written by a model.
          </p>

          {generate.isError && <ErrorState message={messageOf(generate.error)} />}

          {isLoading && <Skeleton className="h-16 w-full" />}
          {isError && (
            <ErrorState message={messageOf(error) ?? 'Failed to load digests'} onRetry={() => refetch()} />
          )}

          {digests && digests.length === 0 && (
            <EmptyState
              icon={<FileText className="h-8 w-8" />}
              title="No digests yet"
              description="Generate one to see this week's activity across the app."
            />
          )}

          {digests && digests.length > 0 && (
            <div className="flex flex-wrap gap-1.5" role="tablist" aria-label="Past digests">
              {digests.map((digest, index) => (
                <Button
                  key={digest.id}
                  type="button"
                  variant={digest.id === effectiveId ? 'default' : 'outline'}
                  size="sm"
                  onClick={() => setSelectedId(digest.id)}
                >
                  {index === 0 ? 'Latest' : new Date(digest.generated_at).toLocaleDateString()}
                </Button>
              ))}
            </div>
          )}
        </CardContent>
      </Card>

      {selected && <DigestView digest={selected} />}
    </div>
  )
}
