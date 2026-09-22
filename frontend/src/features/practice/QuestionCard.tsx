import { Badge } from '@/components/ui/badge'
import { Textarea } from '@/components/ui/textarea'
import type { PracticeQuestion, PracticeVerdict } from '@/lib/api'

const CATEGORY_LABEL: Record<PracticeQuestion['category'], string> = {
  technical: 'Technical',
  behavioral: 'Behavioral',
  situational: 'Situational',
}

const REF_LABEL: Record<PracticeQuestion['ref_type'], string> = {
  posting_requirement: 'From the posting',
  profile_experience: 'From your experience',
  profile_skill: 'From your skills',
}

const VERDICT_LABEL: Record<PracticeVerdict, string> = {
  addressed: 'Addressed',
  partially_addressed: 'Partially addressed',
  missed: 'Missed',
  unclear: 'Unclear',
}

const VERDICT_VARIANT: Record<PracticeVerdict, 'default' | 'secondary' | 'outline'> = {
  addressed: 'default',
  partially_addressed: 'secondary',
  missed: 'outline',
  unclear: 'outline',
}

interface Props {
  question: PracticeQuestion
  index: number
  editable: boolean
  value?: string
  onChange?: (value: string) => void
}

export function QuestionCard({ question, index, editable, value, onChange }: Props) {
  return (
    <li className="space-y-2 rounded-md border border-border p-4 text-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <p className="font-medium">
          {index + 1}. {question.text}
        </p>
        <div className="flex shrink-0 flex-wrap items-center gap-1.5">
          <Badge variant="outline">{CATEGORY_LABEL[question.category]}</Badge>
          {question.verdict && (
            <Badge variant={VERDICT_VARIANT[question.verdict]}>
              {VERDICT_LABEL[question.verdict]}
            </Badge>
          )}
        </div>
      </div>

      <details className="text-xs text-muted-foreground">
        <summary className="cursor-pointer hover:text-foreground">
          {REF_LABEL[question.ref_type]}: {question.ref_name}
        </summary>
        <p className="mt-1 whitespace-pre-wrap">{question.ref_excerpt}</p>
      </details>

      {editable ? (
        <Textarea
          aria-label={`Your answer to: ${question.text}`}
          value={value ?? ''}
          onChange={(e) => onChange?.(e.target.value)}
          placeholder="Type your answer…"
          rows={3}
        />
      ) : (
        <>
          <p className="rounded-md bg-muted p-2 text-muted-foreground">
            {question.answer_text ? (
              <>
                <span className="text-foreground">Your answer: </span>
                {question.answer_text}
              </>
            ) : (
              'No answer was given.'
            )}
          </p>
          {question.feedback_text && <p>{question.feedback_text}</p>}
        </>
      )}
    </li>
  )
}
