import { useState } from 'react'
import type { FormEvent } from 'react'
import { Search } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { ErrorState } from '@/components/layout/error-state'
import { useCreateResearchQuery } from '@/features/research/hooks'

interface NewQueryFormProps {
  onCreated: (id: string) => void
}

export function NewQueryForm({ onCreated }: NewQueryFormProps) {
  const [queryText, setQueryText] = useState('')
  const [purpose, setPurpose] = useState('')
  const createQuery = useCreateResearchQuery()

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!queryText.trim()) return
    createQuery.mutate(
      { query_text: queryText.trim(), purpose: purpose.trim() || null },
      {
        onSuccess: (created) => {
          setQueryText('')
          setPurpose('')
          onCreated(created.id)
        },
      }
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Research</CardTitle>
        <CardDescription>
          Ask a question. Every claim in the answer is cited against a real source and scored — if the
          sources don&apos;t support something, it&apos;s reported as an open question, not guessed.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div className="space-y-2">
            <Label htmlFor="query_text">Question</Label>
            <Textarea
              id="query_text"
              required
              minLength={3}
              placeholder="e.g. Does Acme Corp sponsor visas for the Senior ML Engineer role?"
              value={queryText}
              onChange={(e) => setQueryText(e.target.value)}
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="purpose">Purpose (optional)</Label>
            <Input
              id="purpose"
              placeholder="Why you're asking — helps focus the research"
              value={purpose}
              onChange={(e) => setPurpose(e.target.value)}
            />
          </div>
          {createQuery.isError && (
            <ErrorState
              message={
                createQuery.error instanceof Error ? createQuery.error.message : 'Failed to start research'
              }
            />
          )}
          <Button type="submit" disabled={createQuery.isPending}>
            <Search className="h-4 w-4" />
            {createQuery.isPending ? 'Starting…' : 'Run research'}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}
