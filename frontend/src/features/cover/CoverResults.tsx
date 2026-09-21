import { useState } from 'react'
import { AlertTriangle, Copy, Download, HelpCircle, RefreshCw, ShieldCheck, Trash2 } from 'lucide-react'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import type { CoverLetter, ResumeDecision } from '@/lib/api'
import { ParagraphCard } from '@/features/cover/ParagraphCard'

interface CoverResultsProps {
  letter: CoverLetter
  onDecide: (paragraphId: string, decision: ResumeDecision) => void
  onEdit: (paragraphId: string, text: string | null) => void
  onRegenerate: () => void
  onDelete: () => void
  onCopy: () => void
  onDownload: () => void
  isBusy: boolean
  /** Set after an export, so the buttons can confirm what happened. */
  notice: string | null
}

/** The drafted letter: paragraphs to accept, reject, or edit; what was discarded and why; and the
 * skills the posting wants that this profile can't back up. */
export function CoverResults({
  letter,
  onDecide,
  onEdit,
  onRegenerate,
  onDelete,
  onCopy,
  onDownload,
  isBusy,
  notice,
}: CoverResultsProps) {
  const [confirming, setConfirming] = useState<'regenerate' | 'delete' | null>(null)
  const { counts } = letter
  const hasWork =
    counts.accepted + counts.rejected > 0 || letter.paragraphs.some((p) => p.is_edited)
  const canExport = counts.accepted > 0

  return (
    <div className="space-y-4">
      {letter.is_stale && (
        <Alert>
          <RefreshCw className="h-4 w-4" />
          <AlertTitle>Your profile changed since this draft was written</AlertTitle>
          <AlertDescription>
            The draft reflects the older version. Regenerate to write from your current profile.
          </AlertDescription>
        </Alert>
      )}

      <Alert>
        <ShieldCheck className="h-4 w-4" />
        <AlertTitle>Nothing goes in the letter until you accept it</AlertTitle>
        <AlertDescription>
          Every factual sentence was checked against your profile or the posting, and any that
          couldn&apos;t be backed were dropped. Open &ldquo;Where this comes from&rdquo; on a paragraph to
          see the source of each claim.
        </AlertDescription>
      </Alert>

      <p className="text-sm text-muted-foreground">
        {counts.pending} to review · {counts.accepted} accepted · {counts.rejected} rejected
      </p>
      <ul className="space-y-3">
        {letter.paragraphs.map((paragraph) => (
          <ParagraphCard
            key={paragraph.id}
            paragraph={paragraph}
            onDecide={onDecide}
            onEdit={onEdit}
            disabled={isBusy}
          />
        ))}
      </ul>

      {letter.dropped.length > 0 && (
        <Alert variant="warning">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>
            {letter.dropped.length} sentence{letter.dropped.length === 1 ? ' was' : 's were'} discarded
          </AlertTitle>
          <AlertDescription>
            <p>They would have stated things your profile or the posting doesn&apos;t support.</p>
            <ul className="mt-2 list-disc space-y-1 pl-4">
              {letter.dropped.map((item, index) => (
                <li key={index}>
                  <span className="italic">&ldquo;{item.sentence}&rdquo;</span> — {item.reason}
                </li>
              ))}
            </ul>
          </AlertDescription>
        </Alert>
      )}

      {letter.gaps.length > 0 && (
        <Alert>
          <HelpCircle className="h-4 w-4" />
          <AlertTitle>What this posting wants that your profile can&apos;t back up</AlertTitle>
          <AlertDescription>
            <p>
              The letter never claims these. If you genuinely have the skill, record it with evidence on
              your Profile page.
            </p>
            <ul className="mt-2 space-y-1">
              {letter.gaps.map((gap) => (
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
          Preview the letter as it stands ({counts.accepted} paragraph{counts.accepted === 1 ? '' : 's'}{' '}
          accepted)
        </summary>
        {letter.preview_text ? (
          <pre className="mt-3 max-h-96 overflow-auto whitespace-pre-wrap rounded-md bg-muted/50 p-3 text-sm">
            {letter.preview_text}
          </pre>
        ) : (
          <p className="mt-3 text-sm text-muted-foreground">
            Accept at least one paragraph to start building the letter.
          </p>
        )}
      </details>

      <div className="flex flex-wrap items-center gap-2">
        <Button variant="outline" size="sm" onClick={onCopy} disabled={isBusy || !canExport}>
          <Copy className="h-3.5 w-3.5" /> Copy text
        </Button>
        <Button variant="outline" size="sm" onClick={onDownload} disabled={isBusy || !canExport}>
          <Download className="h-3.5 w-3.5" /> Download .txt
        </Button>
        {notice && <span className="text-xs text-muted-foreground">{notice}</span>}
        <span className="flex-1" />
        {confirming === 'regenerate' && (
          <span className="flex flex-wrap items-center gap-2 text-sm">
            <span className="text-muted-foreground">
              {hasWork
                ? 'This discards the draft, your accept/reject choices, and any edits.'
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
              Delete this draft and any edits? Your profile isn&apos;t affected.
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
