import { useState } from 'react'
import { Check, PencilLine, Undo2, X } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Textarea } from '@/components/ui/textarea'
import { cn } from '@/lib/utils'
import type { CoverParagraph, CoverSupport, ResumeDecision } from '@/lib/api'

const ROLE_LABEL = { opening: 'Opening', body: 'Body', closing: 'Closing' } as const

const DECISION_BADGE: Record<ResumeDecision, { label: string; className: string }> = {
  pending: { label: 'Needs your decision', className: 'text-muted-foreground' },
  accepted: { label: 'Accepted', className: 'border-primary/60' },
  rejected: { label: 'Rejected', className: 'text-muted-foreground line-through' },
}

const SUPPORT_LABEL: Record<CoverSupport['type'], string> = {
  profile_experience: 'Your role',
  profile_skill: 'Your skill',
  profile_summary: 'Your summary',
  posting_quote: 'The posting says',
}

/** Where each sentence comes from, so a claim in the letter can be traced back to a source. */
function Provenance({ paragraph }: { paragraph: CoverParagraph }) {
  return (
    <details>
      <summary className="cursor-pointer text-xs text-muted-foreground hover:text-foreground">
        Where this comes from
      </summary>
      <ol className="mt-2 space-y-2">
        {paragraph.sentences.map((sentence, index) => (
          <li key={index} className="rounded-md border border-border p-3 text-sm">
            <p>{sentence.text}</p>
            {sentence.kind === 'framing' ? (
              <p className="mt-1 text-xs text-muted-foreground">
                Connective wording — it states no facts, and was checked to contain none.
              </p>
            ) : (
              <ul className="mt-2 space-y-1.5">
                {sentence.supports.map((support, supportIndex) => (
                  <li key={supportIndex} className="text-xs text-muted-foreground">
                    <Badge variant="secondary" className="mr-1.5">
                      {SUPPORT_LABEL[support.type]}
                    </Badge>
                    <span className="font-medium text-foreground">{support.label}</span>
                    {support.excerpt && support.type !== 'posting_quote' && (
                      <span> — “{support.excerpt}”</span>
                    )}
                    {support.type === 'posting_quote' && <span>: “{support.excerpt}”</span>}
                  </li>
                ))}
              </ul>
            )}
          </li>
        ))}
      </ol>
    </details>
  )
}

interface ParagraphCardProps {
  paragraph: CoverParagraph
  onDecide: (paragraphId: string, decision: ResumeDecision) => void
  /** text = null restores the fact-checked original. */
  onEdit: (paragraphId: string, text: string | null) => void
  disabled: boolean
}

export function ParagraphCard({ paragraph, onDecide, onEdit, disabled }: ParagraphCardProps) {
  const [editing, setEditing] = useState(false)
  const shownText = paragraph.is_edited ? (paragraph.edited_text ?? paragraph.text) : paragraph.text
  const [draft, setDraft] = useState(shownText)
  const decided = paragraph.decision !== 'pending'
  const badge = DECISION_BADGE[paragraph.decision]

  function startEditing() {
    setDraft(shownText)
    setEditing(true)
  }

  function save() {
    const cleaned = draft.trim()
    if (!cleaned) return
    // Saving the original text unchanged isn't an edit.
    onEdit(paragraph.id, cleaned === paragraph.text ? null : cleaned)
    setEditing(false)
  }

  return (
    <li
      className={cn(
        'space-y-3 rounded-lg border border-border p-4',
        paragraph.decision === 'accepted' && 'border-primary/50',
        paragraph.decision === 'rejected' && 'opacity-70'
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-medium">{ROLE_LABEL[paragraph.role]} paragraph</h4>
        <div className="flex flex-wrap items-center gap-1.5">
          {paragraph.is_edited && (
            <Badge variant="outline" className="border-warning/70 text-warning-foreground">
              Edited by you — not fact-checked
            </Badge>
          )}
          <Badge variant="outline" className={badge.className}>
            {badge.label}
          </Badge>
        </div>
      </div>

      {editing ? (
        <div className="space-y-2">
          <Textarea
            aria-label="Edit paragraph"
            rows={5}
            maxLength={4000}
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
          />
          <p className="text-xs text-muted-foreground">
            Your own wording isn&apos;t fact-checked — you&apos;re the author, so make sure every claim is
            true.
          </p>
          <div className="flex gap-2">
            <Button size="sm" onClick={save} disabled={disabled || !draft.trim()}>
              Save
            </Button>
            <Button variant="ghost" size="sm" onClick={() => setEditing(false)}>
              Cancel
            </Button>
          </div>
        </div>
      ) : (
        <p className="whitespace-pre-wrap text-sm leading-relaxed">{shownText}</p>
      )}

      {paragraph.is_edited && !editing && (
        <details className="text-xs text-muted-foreground">
          <summary className="cursor-pointer hover:text-foreground">See the fact-checked original</summary>
          <p className="mt-2 whitespace-pre-wrap text-sm">{paragraph.text}</p>
        </details>
      )}

      {!editing && <Provenance paragraph={paragraph} />}

      {!editing && (
        <div className="flex flex-wrap gap-2">
          {decided ? (
            <Button
              variant="ghost"
              size="sm"
              disabled={disabled}
              onClick={() => onDecide(paragraph.id, 'pending')}
            >
              <Undo2 className="h-3.5 w-3.5" /> Undo
            </Button>
          ) : (
            <>
              <Button size="sm" disabled={disabled} onClick={() => onDecide(paragraph.id, 'accepted')}>
                <Check className="h-3.5 w-3.5" /> Accept
              </Button>
              <Button
                variant="outline"
                size="sm"
                disabled={disabled}
                onClick={() => onDecide(paragraph.id, 'rejected')}
              >
                <X className="h-3.5 w-3.5" /> Reject
              </Button>
            </>
          )}
          <Button variant="ghost" size="sm" disabled={disabled} onClick={startEditing}>
            <PencilLine className="h-3.5 w-3.5" /> Edit
          </Button>
          {paragraph.is_edited && (
            <Button
              variant="ghost"
              size="sm"
              disabled={disabled}
              onClick={() => onEdit(paragraph.id, null)}
            >
              Restore original
            </Button>
          )}
        </div>
      )}
    </li>
  )
}
