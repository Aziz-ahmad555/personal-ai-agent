import { Badge } from '@/components/ui/badge'
import type { SearchResultType } from '@/lib/api'

const TYPE_LABEL: Record<SearchResultType, string> = {
  bio: 'Bio',
  work_experience: 'Experience',
  education: 'Education',
  skill_evidence: 'Skill',
  preferences: 'Preferences',
  research_claim: 'Research Claim',
  research_source: 'Research Source',
}

export function ResultTypeBadge({ type }: { type: SearchResultType }) {
  return (
    <Badge variant="outline" className="whitespace-nowrap text-[11px]">
      {TYPE_LABEL[type]}
    </Badge>
  )
}
