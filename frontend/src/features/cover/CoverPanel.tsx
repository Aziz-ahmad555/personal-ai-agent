import { useState } from 'react'
import { Loader2, Mail } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/layout/error-state'
import type { CareerJob, CoverExport } from '@/lib/api'
import {
  useCoverLetter,
  useDecideParagraph,
  useDeleteCover,
  useDraftCover,
  useEditParagraph,
  useExportCover,
} from '@/features/cover/hooks'
import { CoverResults } from '@/features/cover/CoverResults'

function messageOf(error: unknown): string | null {
  if (!error) return null
  return error instanceof Error ? error.message : 'Something went wrong'
}

function downloadText(filename: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

/** What to tell the user after an export: the profile holds no contact details, and any
 * paragraph they rewrote is their own wording, not fact-checked. */
function exportNotice(done: string, exported: CoverExport): string {
  const parts = [done, 'Add your contact details before sending it anywhere.']
  if (exported.edited > 0) {
    parts.push(
      `${exported.edited} paragraph${exported.edited === 1 ? ' is' : 's are'} your own wording and ` +
        `${exported.edited === 1 ? "wasn't" : "weren't"} fact-checked.`
    )
  }
  return parts.join(' ')
}

export function CoverPanel({ job }: { job: CareerJob }) {
  const { data: letter, isLoading, isError, error, refetch } = useCoverLetter(job.id)
  const draft = useDraftCover()
  const decide = useDecideParagraph()
  const edit = useEditParagraph()
  const exporter = useExportCover()
  const remove = useDeleteCover()
  const [notice, setNotice] = useState<string | null>(null)

  const header = (
    <CardHeader>
      <CardTitle className="flex items-center gap-2 text-base">
        <Mail className="h-4 w-4" /> Cover letter
      </CardTitle>
    </CardHeader>
  )

  async function exportAnd(action: (exported: CoverExport) => Promise<void> | void, done: string) {
    if (!letter) return
    setNotice(null)
    try {
      const exported = await exporter.mutateAsync(letter.id)
      await action(exported)
      setNotice(exportNotice(done, exported))
    } catch {
      setNotice(null) // the mutation's own error is shown below
    }
  }

  if (isLoading) {
    return (
      <Card>
        {header}
        <CardContent>
          <Skeleton className="h-16 w-full" />
        </CardContent>
      </Card>
    )
  }

  if (isError) {
    return (
      <Card>
        {header}
        <CardContent>
          <ErrorState message={messageOf(error) ?? 'Failed to load'} onRetry={() => refetch()} />
        </CardContent>
      </Card>
    )
  }

  if (!letter) {
    return (
      <Card>
        {header}
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          <p>
            Drafts a cover letter for this job in which every factual sentence is checked against your
            evidence-backed profile or the posting itself — and anything that can&apos;t be backed is
            dropped, not written. You review it paragraph by paragraph and can edit any of it. Nothing is
            sent anywhere.
          </p>
          {draft.isError && <ErrorState message={messageOf(draft.error) ?? 'Failed to start'} />}
          <Button onClick={() => draft.mutate(job.id)} disabled={draft.isPending}>
            {draft.isPending ? 'Starting…' : 'Draft a cover letter'}
          </Button>
        </CardContent>
      </Card>
    )
  }

  if (letter.status === 'running') {
    return (
      <Card>
        {header}
        <CardContent>
          <div className="flex items-center gap-2 rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Writing the letter, then checking every sentence against your profile and the posting…
          </div>
        </CardContent>
      </Card>
    )
  }

  if (letter.status === 'failed') {
    return (
      <Card>
        {header}
        <CardContent>
          <ErrorState
            title="Couldn't draft the letter"
            message={letter.error ?? 'Unknown error'}
            onRetry={() => draft.mutate(job.id)}
          />
        </CardContent>
      </Card>
    )
  }

  const busy = decide.isPending || edit.isPending || exporter.isPending || draft.isPending || remove.isPending

  return (
    <Card>
      {header}
      <CardContent className="space-y-4">
        <CoverResults
          letter={letter}
          isBusy={busy}
          notice={notice}
          onDecide={(paragraphId, decision) =>
            decide.mutate({ letterId: letter.id, paragraphId, decision })
          }
          onEdit={(paragraphId, text) => edit.mutate({ letterId: letter.id, paragraphId, text })}
          onRegenerate={() => draft.mutate(job.id)}
          onDelete={() => remove.mutate({ letterId: letter.id, jobId: job.id })}
          onCopy={() =>
            void exportAnd(async (exported) => {
              await navigator.clipboard.writeText(exported.text)
            }, 'Copied.')
          }
          onDownload={() =>
            void exportAnd((exported) => downloadText(exported.filename, exported.text), 'Downloaded.')
          }
        />
        {decide.isError && <ErrorState message={messageOf(decide.error) ?? 'Failed to save'} />}
        {edit.isError && <ErrorState message={messageOf(edit.error) ?? 'Failed to save your edit'} />}
        {exporter.isError && <ErrorState message={messageOf(exporter.error) ?? 'Export failed'} />}
        {remove.isError && <ErrorState message={messageOf(remove.error) ?? 'Failed to delete'} />}
      </CardContent>
    </Card>
  )
}
