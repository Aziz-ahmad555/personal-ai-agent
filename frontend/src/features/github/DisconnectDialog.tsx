import { Button } from '@/components/ui/button'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { ErrorState } from '@/components/layout/error-state'
import { useDisconnectGithub } from '@/features/github/hooks'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function DisconnectDialog({ open, onOpenChange }: Props) {
  const disconnect = useDisconnectGithub()
  const result = disconnect.data

  function handleOpenChange(next: boolean) {
    if (!next) disconnect.reset()
    onOpenChange(next)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Disconnect GitHub</DialogTitle>
          <DialogDescription>
            {result
              ? 'GitHub is disconnected.'
              : 'This revokes the access token on GitHub and removes it from this app.'}
          </DialogDescription>
        </DialogHeader>

        {result && (
          <p className="text-sm text-muted-foreground" role="status">
            {result.revoked_at_github
              ? 'GitHub confirmed the token was revoked.'
              : "GitHub couldn't be reached to revoke the token. It was removed here and will expire on its own. To revoke it yourself, use github.com/settings/applications."}
          </p>
        )}

        {disconnect.isError && (
          <ErrorState
            message={disconnect.error instanceof Error ? disconnect.error.message : 'Failed to disconnect'}
          />
        )}

        <DialogFooter>
          {result ? (
            <Button onClick={() => handleOpenChange(false)}>Done</Button>
          ) : (
            <Button variant="destructive" disabled={disconnect.isPending} onClick={() => disconnect.mutate()}>
              {disconnect.isPending ? 'Disconnecting…' : 'Disconnect'}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
