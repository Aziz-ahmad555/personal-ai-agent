import { useState } from 'react'
import type { FormEvent } from 'react'
import { Loader2, RefreshCw, Rss, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/layout/empty-state'
import { ErrorState } from '@/components/layout/error-state'
import type { JobBoard } from '@/lib/api'
import { useCreateFeed, useDeleteFeed, useFeeds, usePollFeed } from '@/features/career/hooks'

const BOARD_LABEL: Record<JobBoard, string> = {
  greenhouse: 'Greenhouse',
  lever: 'Lever',
  ashby: 'Ashby',
  usajobs: 'USAJobs',
}

export function FeedsPanel() {
  const [board, setBoard] = useState<JobBoard>('greenhouse')
  const [identifier, setIdentifier] = useState('')
  const { data: feeds, isLoading, isError, error, refetch } = useFeeds()
  const createFeed = useCreateFeed()
  const deleteFeed = useDeleteFeed()
  const pollFeed = usePollFeed()

  const isKeyword = board === 'usajobs'

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const value = identifier.trim()
    if (!value) return
    createFeed.mutate(
      isKeyword ? { board, keyword: value } : { board, company_slug: value },
      { onSuccess: () => setIdentifier('') }
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="text-base">Job board feeds</CardTitle>
        <CardDescription>
          Follow a company&apos;s postings on Greenhouse, Lever, or Ashby, or a USAJobs keyword. These are
          the boards&apos; public APIs — nothing is scraped.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <form onSubmit={handleSubmit} className="grid gap-3 sm:grid-cols-[160px_1fr_auto] sm:items-end">
          <div className="space-y-2">
            <Label htmlFor="feed_board">Board</Label>
            <Select id="feed_board" value={board} onChange={(e) => setBoard(e.target.value as JobBoard)}>
              {(Object.keys(BOARD_LABEL) as JobBoard[]).map((value) => (
                <option key={value} value={value}>
                  {BOARD_LABEL[value]}
                </option>
              ))}
            </Select>
          </div>
          <div className="space-y-2">
            <Label htmlFor="feed_identifier">{isKeyword ? 'Keyword' : 'Company slug'}</Label>
            <Input
              id="feed_identifier"
              required
              placeholder={isKeyword ? 'e.g. machine learning' : 'e.g. anthropic'}
              value={identifier}
              onChange={(e) => setIdentifier(e.target.value)}
            />
          </div>
          <Button type="submit" disabled={createFeed.isPending}>
            {createFeed.isPending ? 'Adding…' : 'Add feed'}
          </Button>
        </form>
        {createFeed.isError && (
          <ErrorState
            message={createFeed.error instanceof Error ? createFeed.error.message : 'Failed to add feed'}
          />
        )}

        {isLoading && <Skeleton className="h-12 w-full" />}
        {isError && (
          <ErrorState
            message={error instanceof Error ? error.message : 'Failed to load feeds'}
            onRetry={() => refetch()}
          />
        )}
        {feeds?.length === 0 && (
          <EmptyState
            icon={<Rss className="h-6 w-6" />}
            title="No feeds yet"
            description="Add a company or keyword above to pull in its postings."
            className="p-6"
          />
        )}
        <ul className="space-y-2">
          {feeds?.map((feed) => (
            <li
              key={feed.id}
              className="flex flex-wrap items-center justify-between gap-2 rounded-md border border-border p-3 text-sm"
            >
              <div className="min-w-0">
                <p className="font-medium">
                  {BOARD_LABEL[feed.board]} · {feed.company_slug ?? feed.keyword}
                </p>
                <p className="text-xs text-muted-foreground">
                  {feed.last_polled_at
                    ? `Last polled ${new Date(feed.last_polled_at).toLocaleString()}`
                    : 'Not polled yet'}
                </p>
                {feed.last_poll_error && (
                  <p className="text-xs text-destructive">Last poll failed: {feed.last_poll_error}</p>
                )}
              </div>
              <div className="flex items-center gap-1">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => pollFeed.mutate(feed.id)}
                  disabled={pollFeed.isPending}
                >
                  {pollFeed.isPending && pollFeed.variables === feed.id ? (
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                  ) : (
                    <RefreshCw className="h-3.5 w-3.5" />
                  )}
                  Poll now
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Remove ${BOARD_LABEL[feed.board]} feed`}
                  onClick={() => deleteFeed.mutate(feed.id)}
                  disabled={deleteFeed.isPending}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
