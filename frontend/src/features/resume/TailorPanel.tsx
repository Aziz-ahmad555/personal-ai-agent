import { useState } from 'react'
import { FileText, Loader2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/layout/error-state'
import type { CareerJob } from '@/lib/api'
import {
  useDecideChange,
  useExportResume,
  useTailorJob,
  useTailoredResume,
} from '@/features/resume/hooks'
import { TailorResults } from '@/features/resume/TailorResults'

function messageOf(error: unknown): string | null {
  if (!error) return null
  return error instanceof Error ? error.message : 'Something went wrong'
}

function downloadText(filename: string, text: string) {
  const url = URL.createObjectURL(new Blob([text], { type: 'text/markdown;charset=utf-8' }))
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}

const CONTACT_REMINDER = 'Your profile holds no contact details — add your own before sending it anywhere.'

export function TailorPanel({ job }: { job: CareerJob }) {
  const { data: resume, isLoading, isError, error, refetch } = useTailoredResume(job.id)
  const tailor = useTailorJob()
  const decide = useDecideChange()
  const exporter = useExportResume()
  const [notice, setNotice] = useState<string | null>(null)

  const header = (
    <CardHeader>
      <CardTitle className="flex items-center gap-2 text-base">
        <FileText className="h-4 w-4" /> Tailor your resume
      </CardTitle>
    </CardHeader>
  )

  async function exportAnd(action: (markdown: string, filename: string) => Promise<void> | void, done: string) {
    if (!resume) return
    setNotice(null)
    try {
      const exported = await exporter.mutateAsync(resume.id)
      await action(exported.markdown, exported.filename)
      setNotice(`${done} ${CONTACT_REMINDER}`)
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

  if (!resume) {
    return (
      <Card>
        {header}
        <CardContent className="space-y-3 text-sm text-muted-foreground">
          <p>
            Suggests rewordings of your existing summary and role descriptions so they speak to this
            posting — as a diff you accept or reject one change at a time. It only rephrases what your
            profile already says; it never adds skills, numbers, or experience you haven&apos;t recorded.
          </p>
          {tailor.isError && <ErrorState message={messageOf(tailor.error) ?? 'Failed to start'} />}
          <Button onClick={() => tailor.mutate(job.id)} disabled={tailor.isPending}>
            {tailor.isPending ? 'Starting…' : 'Tailor my resume for this job'}
          </Button>
        </CardContent>
      </Card>
    )
  }

  if (resume.status === 'running') {
    return (
      <Card>
        {header}
        <CardContent>
          <div className="flex items-center gap-2 rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" />
            Reading your profile and the posting, then checking every suggestion against what you&apos;ve
            actually recorded…
          </div>
        </CardContent>
      </Card>
    )
  }

  if (resume.status === 'failed') {
    return (
      <Card>
        {header}
        <CardContent>
          <ErrorState
            title="Couldn't tailor your resume"
            message={resume.error ?? 'Unknown error'}
            onRetry={() => tailor.mutate(job.id)}
          />
        </CardContent>
      </Card>
    )
  }

  return (
    <Card>
      {header}
      <CardContent className="space-y-4">
        <TailorResults
          resume={resume}
          isBusy={decide.isPending || exporter.isPending || tailor.isPending}
          notice={notice}
          onDecide={(changeId, decision) =>
            decide.mutate({ resumeId: resume.id, changeId, decision })
          }
          onRegenerate={() => tailor.mutate(job.id)}
          onCopy={() =>
            void exportAnd(async (markdown) => {
              await navigator.clipboard.writeText(markdown)
            }, 'Copied.')
          }
          onDownload={() =>
            void exportAnd((markdown, filename) => downloadText(filename, markdown), 'Downloaded.')
          }
        />
        {decide.isError && <ErrorState message={messageOf(decide.error) ?? 'Failed to save'} />}
        {exporter.isError && <ErrorState message={messageOf(exporter.error) ?? 'Export failed'} />}
      </CardContent>
    </Card>
  )
}
