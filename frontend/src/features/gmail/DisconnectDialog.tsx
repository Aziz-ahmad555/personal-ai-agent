import { useState } from 'react'
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
import { useDisconnectGmail } from '@/features/gmail/hooks'

interface DisconnectDialogProps {
  open: boolean
  onOpenChange: (open: boolean) => void
}

export function DisconnectDialog({ open, onOpenChange }: DisconnectDialogProps) {
  const disconnect = useDisconnectGmail()
  const [choice, setChoice] = useState<'keep' | 'purge' | null>(null)

  function handleConfirm() {
    if (choice === null) return
    disconnect.mutate(choice === 'purge', { onSuccess: () => onOpenChange(false) })
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Disconnect Gmail</DialogTitle>
          <DialogDescription>
            This stops future syncing right away. What should happen to the mail already
            stored here?
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <button
            type="button"
            onClick={() => setChoice('keep')}
            className={
              'w-full rounded-md border p-3 text-left text-sm transition-colors hover:bg-accent ' +
              (choice === 'keep' ? 'border-ring bg-accent' : 'border-border')
            }
          >
            <p className="font-medium">Keep the stored data</p>
            <p className="text-muted-foreground">
              Disconnect only — previously synced messages stay until you delete them later.
            </p>
          </button>
          <button
            type="button"
            onClick={() => setChoice('purge')}
            className={
              'w-full rounded-md border p-3 text-left text-sm transition-colors hover:bg-accent ' +
              (choice === 'purge' ? 'border-ring bg-accent' : 'border-border')
            }
          >
            <p className="font-medium">Delete the stored data</p>
            <p className="text-muted-foreground">
              Disconnect and permanently remove every synced message from this app.
            </p>
          </button>
        </div>

        {disconnect.isError && (
          <ErrorState
            message={disconnect.error instanceof Error ? disconnect.error.message : 'Failed to disconnect'}
          />
        )}

        <DialogFooter>
          <Button
            variant={choice === 'purge' ? 'destructive' : 'default'}
            disabled={choice === null || disconnect.isPending}
            onClick={handleConfirm}
          >
            {disconnect.isPending ? 'Disconnecting…' : 'Confirm'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
