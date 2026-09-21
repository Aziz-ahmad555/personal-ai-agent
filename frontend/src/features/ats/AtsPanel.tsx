import { useState } from 'react'
import { Loader2, ScanSearch } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorState } from '@/components/layout/error-state'
import type { CareerJob } from '@/lib/api'
import { AtsResults } from '@/features/ats/AtsResults'
import { useAtsCheck, useAtsSafeExport } from '@/features/ats/hooks'

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

export function AtsPanel({ job }: { job: CareerJob }) {
  const check = useAtsCheck()
  const safe = useAtsSafeExport()
  const [notice, setNotice] = useState<string | null>(null)

  async function downloadSafe() {
    setNotice(null)
    try {
      const exported = await safe.mutateAsync(job.id)
      downloadText(exported.filename, exported.text)
      setNotice('Downloaded. Add your contact details before sending it anywhere.')
    } catch {
      setNotice(null) // the mutation's own error is shown below
    }
  }

  return (
    <Card>
      <CardHeader className="flex-row items-start justify-between gap-2 space-y-0">
        <CardTitle className="flex items-center gap-2 text-base">
          <ScanSearch className="h-4 w-4" /> ATS compatibility
        </CardTitle>
        {check.data && (
          <Button
            variant="outline"
            size="sm"
            onClick={() => check.mutate(job.id)}
            disabled={check.isPending}
          >
            Re-run
          </Button>
        )}
      </CardHeader>
      <CardContent className="space-y-4">
        {!check.data && !check.isPending && (
          <div className="space-y-3 text-sm text-muted-foreground">
            <p>
              Checks how your resume is likely to fare when a company&apos;s applicant-tracking system reads
              it: whether the skills this job asks for appear (and where), and whether the structure and
              characters parse cleanly. It only reports — it never edits anything.
            </p>
            <Button onClick={() => check.mutate(job.id)}>Run ATS check</Button>
          </div>
        )}

        {check.isPending && (
          <div className="flex items-center gap-2 rounded-md border border-dashed border-border p-4 text-sm text-muted-foreground">
            <Loader2 className="h-4 w-4 animate-spin" /> Checking your resume against this posting…
          </div>
        )}

        {check.isError && (
          <ErrorState
            title="Couldn't run the ATS check"
            message={messageOf(check.error) ?? 'Unknown error'}
            onRetry={() => check.mutate(job.id)}
          />
        )}

        {check.data && (
          <AtsResults
            result={check.data}
            onDownloadSafe={() => void downloadSafe()}
            isBusy={safe.isPending}
            notice={notice}
          />
        )}
        {safe.isError && <ErrorState message={messageOf(safe.error) ?? 'Download failed'} />}
      </CardContent>
    </Card>
  )
}
