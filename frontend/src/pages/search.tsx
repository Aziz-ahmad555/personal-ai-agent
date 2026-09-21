import { useState } from 'react'
import type { FormEvent } from 'react'
import { Search as SearchIcon, SearchX } from 'lucide-react'
import { useSearchParams } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/layout/empty-state'
import { ErrorState } from '@/components/layout/error-state'
import { useSearchResults } from '@/features/search/hooks'
import { SearchResultCard } from '@/features/search/SearchResultCard'

export function SearchPage() {
  const [searchParams] = useSearchParams()
  const initialQuery = searchParams.get('q') ?? ''
  const [inputValue, setInputValue] = useState(initialQuery)
  const [submittedQuery, setSubmittedQuery] = useState<string | null>(
    initialQuery.trim() || null
  )

  const { data, isLoading, isFetching, isError, error, refetch } = useSearchResults(submittedQuery)

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    setSubmittedQuery(inputValue.trim() || null)
  }

  return (
    <div className="mx-auto flex max-w-3xl flex-col gap-6">
      <Card>
        <CardHeader>
          <CardTitle>Search</CardTitle>
          <CardDescription>
            Semantic search across your profile and past research — real results with real
            links, never a synthesized answer.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={handleSubmit} className="flex gap-2">
            <Input
              autoFocus
              placeholder="e.g. PyTorch experience, visa sponsorship, remote preference…"
              value={inputValue}
              onChange={(e) => setInputValue(e.target.value)}
            />
            <Button type="submit" disabled={!inputValue.trim() || isFetching}>
              <SearchIcon className="h-4 w-4" />
              {isFetching ? 'Searching…' : 'Search'}
            </Button>
          </form>
        </CardContent>
      </Card>

      {submittedQuery === null && (
        <EmptyState
          icon={<SearchIcon className="h-8 w-8" />}
          title="Search your whole profile and research history"
          description="Try a skill, a role, a company you researched, or a preference."
        />
      )}

      {submittedQuery !== null && isLoading && (
        <div className="space-y-2">
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-20 w-full" />
        </div>
      )}

      {submittedQuery !== null && isError && (
        <ErrorState
          title="Search failed"
          message={error instanceof Error ? error.message : 'Search is unavailable right now'}
          onRetry={() => refetch()}
        />
      )}

      {data && data.results.length === 0 && (
        <EmptyState
          icon={<SearchX className="h-8 w-8" />}
          title="No matches"
          description="Nothing in your profile or research history matched that — try different wording."
        />
      )}

      {data && data.results.length > 0 && (
        <div className="space-y-3">
          {data.results.map((result) => (
            <SearchResultCard key={result.id} result={result} />
          ))}
        </div>
      )}
    </div>
  )
}
