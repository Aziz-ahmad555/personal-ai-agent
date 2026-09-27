import { Mail } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { ErrorState } from '@/components/layout/error-state'
import { useStartOAuth } from '@/features/gmail/hooks'
import { isDemoMode } from '@/lib/demo'

export function ConnectPrompt() {
  const startOAuth = useStartOAuth()

  return (
    <Card>
      <CardHeader>
        <CardTitle>Connect Gmail</CardTitle>
        <CardDescription>Read-only, and only what's described below — nothing else.</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex items-start gap-3 rounded-md border border-border p-4 text-sm">
          <Mail className="mt-0.5 h-5 w-5 shrink-0 text-muted-foreground" />
          <div className="space-y-2 text-muted-foreground">
            <p>
              This requests the <code className="text-foreground">gmail.readonly</code> scope only —
              it can read your mail, nothing more.
            </p>
            <ul className="list-disc space-y-1 pl-4">
              <li>Cannot send, draft, label, archive, or delete anything in your inbox.</li>
              <li>Cannot access Drive, Calendar, Contacts, or any other Google service.</li>
              <li>Only syncs when you click &ldquo;Sync now&rdquo; — nothing runs on a schedule.</li>
              <li>
                Pulls messages from roughly the last 6 months on first sync, not your whole
                history — nothing has judged what's relevant yet.
              </li>
              <li>Stores message metadata and plain-text body only — no attachments.</li>
            </ul>
          </div>
        </div>

        {startOAuth.isError && (
          <ErrorState
            message={
              startOAuth.error instanceof Error ? startOAuth.error.message : 'Failed to start connection'
            }
          />
        )}

        <Button onClick={() => startOAuth.mutate()} disabled={startOAuth.isPending || isDemoMode}>
          <Mail className="h-4 w-4" />
          {startOAuth.isPending ? 'Redirecting…' : 'Connect Gmail (read-only)'}
        </Button>
        {isDemoMode && (
          <p className="text-sm text-muted-foreground">
            Not available in this demo — real account connections are disabled.
          </p>
        )}
      </CardContent>
    </Card>
  )
}
