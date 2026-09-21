import { AlertTriangle, CheckCircle2, Loader2, XCircle } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import type { GmailConnectionStatus, GmailSyncRunStatus } from '@/lib/api'

export function ConnectionStatusBadge({ status }: { status: GmailConnectionStatus }) {
  if (status === 'connected') {
    return (
      <Badge className="gap-1">
        <CheckCircle2 className="h-3 w-3" /> Connected
      </Badge>
    )
  }
  if (status === 'needs_reauth') {
    return (
      <Badge variant="outline" className="gap-1 border-destructive/50 text-destructive">
        <AlertTriangle className="h-3 w-3" /> Needs reconnect
      </Badge>
    )
  }
  return <Badge variant="outline">Disconnected</Badge>
}

export function SyncRunStatusBadge({ status }: { status: GmailSyncRunStatus }) {
  if (status === 'pending' || status === 'running') {
    return (
      <Badge variant="secondary" className="gap-1">
        <Loader2 className="h-3 w-3 animate-spin" /> {status === 'pending' ? 'Queued' : 'Syncing'}
      </Badge>
    )
  }
  if (status === 'failed') {
    return (
      <Badge variant="outline" className="gap-1 border-destructive/50 text-destructive">
        <XCircle className="h-3 w-3" /> Failed
      </Badge>
    )
  }
  return (
    <Badge variant="outline" className="gap-1">
      <CheckCircle2 className="h-3 w-3" /> Done
    </Badge>
  )
}
