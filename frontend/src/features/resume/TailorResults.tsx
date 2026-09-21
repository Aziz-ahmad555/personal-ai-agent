import { useState } from 'react'
import { AlertTriangle, Copy, Download, HelpCircle, RefreshCw, ShieldCheck, Trash2 } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { ResumeDecision, TailoredResume } from '@/lib/api'
import { ChangeCard } from '@/features/resume/ChangeCard'

interface TailorResultsProps {
  resume: TailoredResume
  onDecide: (changeId: string, decision: ResumeDecision) => void
  onRegenerate: () => void
  onDelete: () => void
  onCopy: () => void
  onDownload: () => void
  isBusy: boolean
  /** Set once an export has been made, so the buttons can confirm what happened. */
  notice: string | null
}

/** The completed draft: what changed (to accept or reject), what was left out and why, and
 * the skills the posting wants that this profile can't back up. */
export function TailorResults({
  resume,
  onDecide,
  onRegenerate,
  onDelete,
  onCopy,
  onDownload,
  isBusy,
  notice,
}: TailorResultsProps) {
  const [confirming, setConfirming] = useState<'regenerate' | 'delete' | null>(null)
  const { counts } = resume
  const hasDecisions = counts.accepted + counts.rejected > 0

  return (
    <div className="space-y-4">
      {resume.is_stale && (
        <Alert>
          <RefreshCw className="h-4 w-4" />
          <AlertTitle>Your profile changed since this draft was made</AlertTitle>
          <AlertDescription>
            These suggestions are based on the older version. Regenerate to reflect your current profile.
          </AlertDescription>
        </Alert>
      )}

      <Alert>
        <ShieldCheck className="h-4 w-4" />
        <AlertTitle>Nothing changes until you accept it</AlertTitle>
        <AlertDescription>
          These are rewordings of what your profile already says, checked so they add no skills,
          numbers, or names your profile doesn&apos;t support. Pending and rejected changes leave your
          original wording untouched.
        </AlertDescription>
      </Alert>

      {resume.changes.length === 0 ? (
        <Alert>
          <HelpCircle className="h-4 w-4" />
          <AlertTitle>No changes to suggest</AlertTitle>
          <AlertDescription>
            Nothing in your resume could be honestly improved for this posting.
            {resume.gaps.length > 0 && ' See the gaps below for what it asks for that your profile lacks.'}
          </AlertDescription>
        </Alert>
      ) : (
        <>
          <p className="text-sm text-muted-foreground">
            {counts.pending} to review · {counts.accepted} accepted · {counts.rejected} rejected
          </p>
          <ul className="space-y-3">
            {resume.changes.map((change) => (
              <ChangeCard key={change.id} change={change} onDecide={onDecide} disabled={isBusy} />
            ))}
          </ul>
        </>
      )}

      {resume.dropped.length > 0 && (
        <Alert variant="warning">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>
            {resume.dropped.length} suggestion{resume.dropped.length === 1 ? ' was' : 's were'} discarded
          </AlertTitle>
          <AlertDescription>
            <p>They would have added claims your profile doesn&apos;t support, so they were never shown as options.</p>
            <ul className="mt-2 list-disc space-y-1 pl-4">
              {resume.dropped.map((item, index) => (
                <li key={index}>
                  <span className="font-medium">{item.source}:</span> {item.reason}
                </li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      {resume.gaps.length > 0 && (
        <Alert>
          <HelpCircle className="h-4 w-4" />
          <AlertTitle>What this posting wants that your profile can&apos;t back up</AlertTitle>
          <AlertDescription>
            <p>None of these were added to your resume. If you genuinely have the skill, record it with evidence on your Profile page.</p>
            <ul className="mt-2 space-y-1">
              {resume.gaps.map((gap) => (
                <li key={gap.skill} className="flex flex-wrap items-center gap-2">
                  <span className="font-medium">{gap.skill}</span>
                  <Badge variant="outline">{gap.kind}</Badge>
                  <span className="text-muted-foreground">— {gap.reason}</span>
                </li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      <details className="rounded-lg border border-border p-4">
        <summary className="cursor-pointer text-sm font-medium">
          Preview your resume as it stands ({counts.accepted} accepted change
          {counts.accepted === 1 ? '' : 's'} applied)
        </summary>
        <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-muted/50 p-3 text-xs">
          {resume.preview_markdown}
        </pre>
      </details>

      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" size="sm" onClick={onCopy} disabled={isBusy}>
          <Copy className="h-3.5 w-3.5" /> Copy Markdown
        </Button>
        <Button variant="outline" size="sm" onClick={onDownload} disabled={isBusy}>
          <Download className="h-3.5 w-3.5" /> Download .md
        </Button>
        {notice && <span className="text-xs text-muted-foreground">{notice}</span>}
        <span className="flex-1" />
        {confirming === 'regenerate' && (
          <span className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted-foreground">
              {hasDecisions
                ? 'This discards the draft and your accept/reject choices.'
                : 'Regenerate the draft?'}
            </span>
            <Button
              variant="destructive"
              size="sm"
              disabled={isBusy}
              onClick={() => {
                setConfirming(null)
                onRegenerate()
              }}
            >
              Regenerate
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setConfirming(null)}>
              Cancel
            </Button>
          </span>
        )}
        {confirming === 'delete' && (
          <span className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted-foreground">
              Delete this draft? Your profile isn&apos;t affected.
            </span>
            <Button
              variant="destructive"
              size="sm"
              disabled={isBusy}
              onClick={() => {
                setConfirming(null)
                onDelete()
              }}
            >
              Delete draft
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setConfirming(null)}>
              Cancel
            </Button>
          </span>
        )}
        {confirming === null && (
          <>
            <Button variant="ghost" size="sm" onClick={() => setConfirming('delete')}>
              <Trash2 className="h-3.5 w-3.5" /> Delete
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setConfirming('regenerate')}>
              <RefreshCw className="h-3.5 w-3.5" /> Regenerate
            </Button>
          </>
        )}
      </div>
    </div>
  )
}
