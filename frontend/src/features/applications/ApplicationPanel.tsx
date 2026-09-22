import { useState } from 'react'
import type { FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { ClipboardList, ExternalLink, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { Skeleton } from '@/components/ui/skeleton'
import { Textarea } from '@/components/ui/textarea'
import { EmptyState } from '@/components/layout/empty-state'
import { ErrorState } from '@/components/layout/error-state'
import type { ApplicationDetail } from '@/lib/api'
import {
  ApplicationStatusBadge,
  FollowUpChip,
  MatchChip,
} from '@/features/applications/badges'
import {
  useAddEvent,
  useApplication,
  useChangeStatus,
  useDeleteApplication,
  useUpdateApplication,
} from '@/features/applications/hooks'
import { StatusChangeForm } from '@/features/applications/StatusChangeForm'
import { Timeline } from '@/features/applications/Timeline'
import { todayISO } from '@/features/applications/labels'

function messageOf(error: unknown): string | null {
  if (!error) return null
  return error instanceof Error ? error.message : 'Something went wrong'
}

function FollowUpForm({ application }: { application: ApplicationDetail }) {
  const update = useUpdateApplication()
  const [text, setText] = useState(application.next_action_text ?? '')
  const [on, setOn] = useState(application.next_action_on ?? '')

  function save(event: FormEvent) {
    event.preventDefault()
    update.mutate({
      id: application.id,
      input: { next_action_text: text.trim() || null, next_action_on: on || null },
    })
  }

  function clear() {
    setText('')
    setOn('')
    update.mutate({ id: application.id, input: { next_action_text: null, next_action_on: null } })
  }

  return (
    <form onSubmit={save} className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-[1fr_180px]">
        <div className="space-y-2">
          <Label htmlFor="follow_text">What&apos;s next</Label>
          <Input
            id="follow_text"
            maxLength={255}
            placeholder="e.g. Email the recruiter"
            value={text}
            onChange={(e) => setText(e.target.value)}
          />
        </div>
        <div className="space-y-2">
          <Label htmlFor="follow_date">By</Label>
          <Input id="follow_date" type="date" value={on} onChange={(e) => setOn(e.target.value)} />
        </div>
      </div>
      {update.isError && <ErrorState message={messageOf(update.error) ?? 'Failed to save'} />}
      <div className="flex gap-2">
        <Button type="submit" variant="outline" size="sm" disabled={update.isPending}>
          Save reminder
        </Button>
        {(application.next_action_text || application.next_action_on) && (
          <Button type="button" variant="ghost" size="sm" onClick={clear} disabled={update.isPending}>
            Clear
          </Button>
        )}
      </div>
      <p className="text-xs text-muted-foreground">
        A reminder inside this app only — nothing is sent to anyone.
      </p>
    </form>
  )
}

function NotesForm({ application }: { application: ApplicationDetail }) {
  const update = useUpdateApplication()
  const [notes, setNotes] = useState(application.notes ?? '')
  const dirty = notes !== (application.notes ?? '')

  return (
    <form
      onSubmit={(event) => {
        event.preventDefault()
        update.mutate({ id: application.id, input: { notes: notes.trim() || null } })
      }}
      className="space-y-2"
    >
      <Label htmlFor="app_notes">Notes</Label>
      <Textarea
        id="app_notes"
        rows={3}
        maxLength={4000}
        placeholder="Anything worth remembering about this application."
        value={notes}
        onChange={(e) => setNotes(e.target.value)}
      />
      {update.isError && <ErrorState message={messageOf(update.error) ?? 'Failed to save'} />}
      <Button type="submit" variant="outline" size="sm" disabled={!dirty || update.isPending}>
        Save notes
      </Button>
    </form>
  )
}

function AddEventForm({ applicationId }: { applicationId: string }) {
  const addEvent = useAddEvent()
  const [type, setType] = useState<'note' | 'interview'>('note')
  const [on, setOn] = useState(todayISO())
  const [body, setBody] = useState('')

  function submit(event: FormEvent) {
    event.preventDefault()
    if (!body.trim()) return
    addEvent.mutate(
      { id: applicationId, input: { event_type: type, occurred_on: on || null, body: body.trim() } },
      { onSuccess: () => setBody('') }
    )
  }

  return (
    <form onSubmit={submit} className="space-y-3">
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="space-y-2">
          <Label htmlFor="event_type">Add to timeline</Label>
          <Select
            id="event_type"
            value={type}
            onChange={(e) => setType(e.target.value as 'note' | 'interview')}
          >
            <option value="note">Note</option>
            <option value="interview">Interview</option>
          </Select>
        </div>
        <div className="space-y-2">
          <Label htmlFor="event_date">Date</Label>
          <Input
            id="event_date"
            type="date"
            max={todayISO()}
            value={on}
            onChange={(e) => setOn(e.target.value)}
          />
        </div>
      </div>
      <Textarea
        aria-label="Details"
        rows={2}
        maxLength={4000}
        required
        placeholder={type === 'interview' ? 'Who you spoke to, what was covered…' : 'What happened?'}
        value={body}
        onChange={(e) => setBody(e.target.value)}
      />
      {addEvent.isError && <ErrorState message={messageOf(addEvent.error) ?? 'Failed to add'} />}
      <Button type="submit" variant="outline" size="sm" disabled={addEvent.isPending || !body.trim()}>
        Add
      </Button>
    </form>
  )
}

function DeleteControl({ id, onDeleted }: { id: string; onDeleted: () => void }) {
  const remove = useDeleteApplication()
  const [confirming, setConfirming] = useState(false)

  if (!confirming) {
    return (
      <Button variant="ghost" size="sm" onClick={() => setConfirming(true)}>
        <Trash2 className="h-3.5 w-3.5" /> Stop tracking
      </Button>
    )
  }
  return (
    <div className="flex flex-wrap items-center gap-2 text-sm">
      <span className="text-muted-foreground">
        Delete this application and its timeline? The job posting stays.
      </span>
      <Button
        variant="destructive"
        size="sm"
        disabled={remove.isPending}
        onClick={() => remove.mutate(id, { onSuccess: onDeleted })}
      >
        {remove.isPending ? 'Deleting…' : 'Delete'}
      </Button>
      <Button variant="ghost" size="sm" onClick={() => setConfirming(false)}>
        Cancel
      </Button>
    </div>
  )
}

interface ApplicationPanelProps {
  applicationId: string | null
  onDeleted: () => void
}

export function ApplicationPanel({ applicationId, onDeleted }: ApplicationPanelProps) {
  const { data: application, isLoading, isError, error, refetch } = useApplication(applicationId)
  const changeStatus = useChangeStatus()

  if (applicationId === null) {
    return (
      <Card>
        <CardContent className="pt-6">
          <EmptyState
            icon={<ClipboardList className="h-8 w-8" />}
            title="No application selected"
            description="Pick one from the board to see its timeline and move it forward."
          />
        </CardContent>
      </Card>
    )
  }
  if (isLoading) {
    return (
      <Card>
        <CardContent className="space-y-3 pt-6">
          <Skeleton className="h-6 w-2/3" />
          <Skeleton className="h-24 w-full" />
        </CardContent>
      </Card>
    )
  }
  if (isError || !application) {
    return (
      <Card>
        <CardContent className="pt-6">
          <ErrorState message={messageOf(error) ?? 'Failed to load this application'} onRetry={() => refetch()} />
        </CardContent>
      </Card>
    )
  }

  const { job } = application
  return (
    <div className="space-y-6">
      <Card>
        <CardHeader className="space-y-2">
          <CardTitle className="text-base">{job?.title ?? 'Untitled posting'}</CardTitle>
          {job && (
            <p className="text-sm text-muted-foreground">
              {[job.company_name, job.location, job.remote_type !== 'unknown' ? job.remote_type : null]
                .filter(Boolean)
                .join(' · ')}
            </p>
          )}
          <div className="flex flex-wrap items-center gap-2">
            <ApplicationStatusBadge status={application.status} />
            <MatchChip match={application.match} />
            <FollowUpChip
              state={application.follow_up_state}
              text={application.next_action_text}
              on={application.next_action_on}
            />
          </div>
          <div className="flex flex-wrap items-center gap-3 text-xs">
            <Link
              to={job ? `/career?job=${job.id}` : '/career'}
              className="text-muted-foreground underline-offset-4 hover:underline"
            >
              View the job &amp; its match
            </Link>
            {job && (
              <Link
                to={`/career?job=${job.id}#practice`}
                className="text-muted-foreground underline-offset-4 hover:underline"
              >
                Practice interview questions
              </Link>
            )}
            {job?.source_url && (
              <a
                href={job.source_url}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex items-center gap-1 text-muted-foreground underline-offset-4 hover:underline"
              >
                Original posting <ExternalLink className="h-3 w-3" />
              </a>
            )}
          </div>
        </CardHeader>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Move this application</CardTitle>
        </CardHeader>
        <CardContent>
          <StatusChangeForm
            key={`${application.id}:${application.status}`}
            allowed={application.allowed_transitions}
            reopenTargets={application.reopen_targets}
            isPending={changeStatus.isPending}
            error={messageOf(changeStatus.error)}
            onSubmit={(input) => changeStatus.mutate({ id: application.id, input })}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Timeline</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <Timeline events={application.events} />
          <AddEventForm applicationId={application.id} />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Follow-up &amp; notes</CardTitle>
        </CardHeader>
        <CardContent className="space-y-5">
          <FollowUpForm
            key={`${application.id}:${application.next_action_text}:${application.next_action_on}`}
            application={application}
          />
          <NotesForm key={`${application.id}:notes`} application={application} />
        </CardContent>
      </Card>

      <DeleteControl id={application.id} onDeleted={onDeleted} />
    </div>
  )
}
