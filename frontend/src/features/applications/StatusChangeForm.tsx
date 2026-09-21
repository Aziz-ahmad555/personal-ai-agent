import { useState } from 'react'
import type { FormEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { ErrorState } from '@/components/layout/error-state'
import type { ApplicationStatus, ApplicationStatusChangeInput } from '@/lib/api'
import { STATUS_LABEL, todayISO } from '@/features/applications/labels'

interface StatusChangeFormProps {
  allowed: ApplicationStatus[]
  reopenTargets: ApplicationStatus[]
  isPending: boolean
  error: string | null
  onSubmit: (input: ApplicationStatusChangeInput) => void
}

/** Offers exactly the moves the server says are allowed — it never decides that itself.
 * Reopening a closed application is a separate, explicitly labeled choice. */
export function StatusChangeForm({
  allowed,
  reopenTargets,
  isPending,
  error,
  onSubmit,
}: StatusChangeFormProps) {
  const options = [
    ...allowed.map((status) => ({ status, label: STATUS_LABEL[status] })),
    ...reopenTargets.map((status) => ({ status, label: `Reopen as ${STATUS_LABEL[status]}` })),
  ]
  const [status, setStatus] = useState<ApplicationStatus | ''>(options[0]?.status ?? '')
  const [occurredOn, setOccurredOn] = useState(todayISO())
  const [note, setNote] = useState('')

  if (options.length === 0) {
    return (
      <p className="text-sm text-muted-foreground">
        This application is final — there&apos;s nothing further to move it to.
      </p>
    )
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    if (!status) return
    onSubmit({ status, occurred_on: occurredOn || null, note: note.trim() || null })
    setNote('')
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="status_to">Move to</Label>
          <Select
            id="status_to"
            value={status}
            onChange={(e) => setStatus(e.target.value as ApplicationStatus)}
          >
            {options.map((option) => (
              <option key={option.status} value={option.status}>
                {option.label}
              </option>
            ))}
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="status_date">Date it happened</Label>
          <Input
            id="status_date"
            type="date"
            max={todayISO()}
            value={occurredOn}
            onChange={(e) => setOccurredOn(e.target.value)}
          />
        </div>
      </div>
      <div className="space-y-2">
        <Label htmlFor="status_note">Note (optional)</Label>
        <Textarea
          id="status_note"
          rows={2}
          maxLength={4000}
          value={note}
          onChange={(e) => setNote(e.target.value)}
        />
      </div>
      {error && <ErrorState title="Couldn't update the status" message={error} />}
      <Button type="submit" disabled={isPending || !status}>
        {isPending ? 'Saving…' : 'Update status'}
      </Button>
    </form>
  )
}
