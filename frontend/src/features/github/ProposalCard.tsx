import { useState } from 'react'
import { CheckCircle2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Select } from '@/components/ui/select'
import { ErrorState } from '@/components/layout/error-state'
import type { GithubProposal, SkillLevel } from '@/lib/api'
import { describeContribution } from '@/features/github/format'
import { useAcceptProposal, useDismissProposal } from '@/features/github/hooks'

const LEVELS: SkillLevel[] = ['beginner', 'intermediate', 'advanced', 'expert']
const KIND_LABEL = { language: 'Language', framework: 'Framework / library', tool: 'Tool' } as const

function messageOf(error: unknown): string {
  return error instanceof Error ? error.message : 'Something went wrong'
}

export function ProposalCard({ proposal }: { proposal: GithubProposal }) {
  const accept = useAcceptProposal()
  const dismiss = useDismissProposal()
  // '' means "keep my current level" for a skill that has one, or "not chosen yet" for a new one.
  const [level, setLevel] = useState<SkillLevel | ''>('')
  const pending = proposal.status === 'pending'
  const needsLevel = proposal.requires_level
  const busy = accept.isPending || dismiss.isPending

  return (
    <li className="space-y-3 rounded-md border border-border p-4 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-medium">{proposal.skill_name}</span>
        <Badge variant="outline">{KIND_LABEL[proposal.kind]}</Badge>
        {proposal.attribution === 'ownership_only' && (
          <Badge variant="outline" className="border-warning/60 text-warning-foreground">
            Owned, no attributed commits
          </Badge>
        )}
        {proposal.attribution === 'unknown' && (
          <Badge variant="outline">Commit attribution unavailable</Badge>
        )}
        {proposal.status === 'accepted' && (
          <Badge className="gap-1">
            <CheckCircle2 className="h-3 w-3" /> Added to your profile
          </Badge>
        )}
        {proposal.status === 'dismissed' && <Badge variant="secondary">Dismissed</Badge>}
      </div>

      <ul className="space-y-1" aria-label={`Evidence for ${proposal.skill_name}`}>
        {proposal.contributions.map((c) => (
          <li key={`${c.repo}-${c.via}-${c.source_file ?? ''}`} className="text-muted-foreground">
            <a
              href={c.source_url}
              target="_blank"
              rel="noreferrer"
              className="font-medium text-foreground underline-offset-4 hover:underline"
            >
              {c.repo}
            </a>{' '}
            — {describeContribution(c)}
          </li>
        ))}
      </ul>

      <details className="text-xs text-muted-foreground">
        <summary className="cursor-pointer">What will be saved on your profile</summary>
        <p className="mt-1.5 rounded-md bg-muted p-2 text-foreground">{proposal.evidence_preview}</p>
      </details>

      {pending && (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center gap-2">
            <label className="text-muted-foreground" htmlFor={`level-${proposal.id}`}>
              Level
            </label>
            <div className="w-60">
              <Select
                id={`level-${proposal.id}`}
                value={level}
                onChange={(event) => setLevel(event.target.value as SkillLevel | '')}
              >
                <option value="">
                  {needsLevel ? 'Choose your level…' : `Keep my current level (${proposal.existing_level})`}
                </option>
                {LEVELS.map((option) => (
                  <option key={option} value={option}>
                    {option}
                  </option>
                ))}
              </Select>
            </div>
          </div>
          {accept.isError && (
            <ErrorState title="Couldn't add it" message={messageOf(accept.error)} />
          )}
          {dismiss.isError && <ErrorState message={messageOf(dismiss.error)} />}

          <div className="flex flex-wrap gap-2">
            <Button
              size="sm"
              disabled={busy || (needsLevel && level === '')}
              onClick={() => accept.mutate({ id: proposal.id, level: level === '' ? null : level })}
            >
              {accept.isPending ? 'Adding…' : 'Add to my profile'}
            </Button>
            <Button size="sm" variant="outline" disabled={busy} onClick={() => dismiss.mutate(proposal.id)}>
              {dismiss.isPending ? 'Dismissing…' : 'Dismiss'}
            </Button>
          </div>
        </div>
      )}
    </li>
  )
}
