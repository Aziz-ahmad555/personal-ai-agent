import { useState } from 'react'
import type { FormEvent } from 'react'
import { Plus } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { ErrorState } from '@/components/layout/error-state'
import { cn } from '@/lib/utils'
import { useCaptureJob } from '@/features/career/hooks'
import { isDemoMode } from '@/lib/demo'

type Mode = 'paste' | 'url'

interface CaptureJobFormProps {
  onCreated: (id: string) => void
}

export function CaptureJobForm({ onCreated }: CaptureJobFormProps) {
  const [mode, setMode] = useState<Mode>('paste')
  const [pasteText, setPasteText] = useState('')
  const [url, setUrl] = useState('')
  const capture = useCaptureJob()

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    const input =
      mode === 'paste'
        ? { kind: 'paste' as const, text: pasteText.trim() }
        : { kind: 'url' as const, url: url.trim() }
    if (input.kind === 'paste' ? !input.text : !input.url) return
    capture.mutate(input, {
      onSuccess: (job) => {
        setPasteText('')
        setUrl('')
        onCreated(job.id)
      },
    })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Career</CardTitle>
        <CardDescription>
          Add a job posting, then see how well it fits you — with every point of the score traced to
          your profile, and anything it can&apos;t judge reported as unknown.
        </CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-3">
          <div role="tablist" aria-label="How to add a posting" className="inline-flex rounded-md border border-border p-0.5">
            {(['paste', 'url'] as const).map((value) => (
              <button
                key={value}
                type="button"
                role="tab"
                aria-selected={mode === value}
                disabled={value === 'url' && isDemoMode}
                onClick={() => setMode(value)}
                className={cn(
                  'rounded px-3 py-1 text-sm transition-colors disabled:cursor-not-allowed disabled:opacity-50',
                  mode === value ? 'bg-accent text-accent-foreground' : 'text-muted-foreground'
                )}
              >
                {value === 'paste' ? 'Paste text' : 'From URL'}
              </button>
            ))}
          </div>
          {isDemoMode && (
            <p className="text-sm text-muted-foreground">
              Capturing a posting by URL is disabled in this demo — paste the text instead.
            </p>
          )}

          {mode === 'paste' ? (
            <div className="space-y-2">
              <Label htmlFor="job_text">Posting text</Label>
              <Textarea
                id="job_text"
                required
                rows={6}
                maxLength={20000}
                placeholder="Paste the full job description — the more of it, the more the match can measure."
                value={pasteText}
                onChange={(e) => setPasteText(e.target.value)}
              />
            </div>
          ) : (
            <div className="space-y-2">
              <Label htmlFor="job_url">Posting URL</Label>
              <Input
                id="job_url"
                type="url"
                required
                placeholder="https://company.example.com/careers/role"
                value={url}
                onChange={(e) => setUrl(e.target.value)}
              />
            </div>
          )}

          {capture.isError && (
            <ErrorState
              message={capture.error instanceof Error ? capture.error.message : 'Failed to add the posting'}
            />
          )}
          <Button type="submit" disabled={capture.isPending}>
            <Plus className="h-4 w-4" />
            {capture.isPending ? 'Reading posting…' : 'Add posting'}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}
