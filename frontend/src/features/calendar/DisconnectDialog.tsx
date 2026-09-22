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
import { useDisconnectCalendar } from '@/features/calendar/hooks'

interface Props {
  open: boolean
  onOpenChange: (open: boolean) => void
}

const CHOICES = [
  {
    value: 'keep',
    title: 'Keep the synced data',
    detail: 'Disconnect only. Your event snapshot and any classifications you set stay in this app.',
  },
  {
    value: 'purge',
    title: 'Delete the synced data',
    detail: 'Also remove the synced events and sync history from this app.',
  },
] as const

export function DisconnectDialog({ open, onOpenChange }: Props) {
  const disconnect = useDisconnectCalendar()
  const [choice, setChoice] = useState<'keep' | 'purge'>('keep')
  const result = disconnect.data

  function handleOpenChange(next: boolean) {
    if (!next) {
      disconnect.reset()
      setChoice('keep')
    }
    onOpenChange(next)
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Disconnect Calendar</DialogTitle>
          <DialogDescription>
            {result
              ? 'Calendar is disconnected.'
              : 'This revokes the access token on Google and removes it from this app.'}
          </DialogDescription>
        </DialogHeader>

        {!result && (
          <div className="space-y-2">
            {CHOICES.map((option) => (
              <button
                key={option.value}
                type="button"
                aria-pressed={choice === option.value}
                onClick={() => setChoice(option.value)}
                className={
                  'w-full rounded-md border p-3 text-left text-sm transition-colors hover:bg-accent ' +
                  (choice === option.value ? 'border-ring bg-accent' : 'border-border')
                }
              >
                <p className="font-medium">{option.title}</p>
                <p className="text-muted-foreground">{option.detail}</p>
              </button>
            ))}
            <p className="text-xs text-muted-foreground">
              Applications you linked an event to are your own and stay either way.
            </p>
          </div>
        )}

        {result && (
          <p className="text-sm text-muted-foreground" role="status">
            {result.revoked_at_google
              ? 'Google confirmed the token was revoked.'
              : "Google couldn't be reached to revoke the token. It was removed here and will expire on its own. To revoke it yourself, use myaccount.google.com/permissions."}
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
            <Button
              variant={choice === 'purge' ? 'destructive' : 'default'}
              disabled={disconnect.isPending}
              onClick={() => disconnect.mutate(choice === 'purge')}
            >
              {disconnect.isPending ? 'Disconnecting…' : 'Disconnect'}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
