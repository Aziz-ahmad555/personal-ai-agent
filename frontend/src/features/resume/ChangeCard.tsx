import { Check, Undo2, X } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import type { ResumeChange, ResumeDecision } from '@/lib/api'
import { type DiffSegment, diffWords } from '@/features/resume/diff'

function DiffText({ segments, side }: { segments: DiffSegment[]; side: 'before' | 'after' }) {
  return (
    <p className="whitespace-pre-wrap text-sm leading-relaxed">
      {segments.map((segment, index) => (
        <span key={index}>
          {index > 0 && ' '}
          {segment.kind === 'same' ? (
            segment.text
          ) : (
            <mark
              className={cn(
                'rounded px-0.5',
                side === 'before'
                  ? 'bg-destructive/15 text-destructive line-through decoration-destructive/60'
                  : 'bg-primary/15 font-medium text-foreground underline decoration-primary/50 underline-offset-2'
              )}
            >
              {segment.text}
            </mark>
          )}
        </span>
      ))}
    </p>
  )
}

/** The skills change is a pure reordering, so it's shown as two lists with what moved marked
 * — a word diff of "Python FastAPI" vs "FastAPI Python" would only be confusing. */
function SkillsDiff({ change }: { change: ResumeChange }) {
  const before = change.before_text.split('\n')
  const after = change.after_text.split('\n')
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <ol aria-label="Skills before" className="space-y-1 text-sm">
        {before.map((skill, index) => (
          <li key={skill} className="flex gap-2 text-muted-foreground">
            <span className="w-4 tabular-nums">{index + 1}.</span>
            {skill}
          </li>
        ))}
      </ol>
      <ol aria-label="Skills after" className="space-y-1 text-sm">
        {after.map((skill, index) => {
          const moved = before.indexOf(skill) !== index
          return (
            <li key={skill} className="flex items-center gap-2">
              <span className="w-4 tabular-nums text-muted-foreground">{index + 1}.</span>
              <span className={cn(moved && 'font-medium')}>{skill}</span>
              {moved && (
                <Badge variant="outline" className="text-[10px]">
                  moved
                </Badge>
              )}
            </li>
          )
        })}
      </ol>
    </div>
  )
}

const DECISION_BADGE: Record<ResumeDecision, { label: string; className: string }> = {
  pending: { label: 'Needs your decision', className: 'text-muted-foreground' },
  accepted: { label: 'Accepted', className: 'border-primary/60' },
  rejected: { label: 'Rejected', className: 'text-muted-foreground line-through' },
}

interface ChangeCardProps {
  change: ResumeChange
  onDecide: (changeId: string, decision: ResumeDecision) => void
  disabled: boolean
}

export function ChangeCard({ change, onDecide, disabled }: ChangeCardProps) {
  const decided = change.decision !== 'pending'
  const badge = DECISION_BADGE[change.decision]
  const diff = change.change_type === 'rewrite' ? diffWords(change.before_text, change.after_text) : null

  return (
    <li
      className={cn(
        'space-y-3 rounded-lg border border-border p-4',
        change.decision === 'accepted' && 'border-primary/50',
        change.decision === 'rejected' && 'opacity-70'
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h4 className="text-sm font-medium">{change.target_label}</h4>
        <Badge variant="outline" className={badge.className}>
          {badge.label}
        </Badge>
      </div>

      <p className="text-sm text-muted-foreground">{change.rationale}</p>

      {change.addresses.length > 0 && (
        <ul className="flex flex-wrap gap-1.5" aria-label="Requirements this speaks to">
          {change.addresses.map((address) => (
            <li key={address.requirement}>
              <Badge variant="secondary" title={`Posting: “${address.quote}”`}>
                {address.requirement}
              </Badge>
            </li>
          ))}
        </ul>
      )}

      {diff ? (
        <div className="grid gap-3 sm:grid-cols-2">
          <div className="space-y-1">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">Before</p>
            <DiffText segments={diff.before} side="before" />
          </div>
          <div className="space-y-1">
            <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">After</p>
            <DiffText segments={diff.after} side="after" />
          </div>
        </div>
      ) : (
        <SkillsDiff change={change} />
      )}

      <div className="flex flex-wrap gap-2">
        {decided ? (
          <Button
            variant="ghost"
            size="sm"
            disabled={disabled}
            onClick={() => onDecide(change.id, 'pending')}
          >
            <Undo2 className="h-3.5 w-3.5" /> Undo
          </Button>
        ) : (
          <>
            <Button size="sm" disabled={disabled} onClick={() => onDecide(change.id, 'accepted')}>
              <Check className="h-3.5 w-3.5" /> Accept
            </Button>
            <Button
              variant="outline"
              size="sm"
              disabled={disabled}
              onClick={() => onDecide(change.id, 'rejected')}
            >
              <X className="h-3.5 w-3.5" /> Reject
            </Button>
          </>
        )}
      </div>
    </li>
  )
}
