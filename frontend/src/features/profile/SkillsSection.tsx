import { useState } from 'react'
import type { FormEvent } from 'react'
import { Plus, Sparkles, Trash2 } from 'lucide-react'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/layout/empty-state'
import { ErrorState } from '@/components/layout/error-state'
import type { SkillLevel } from '@/lib/api'
import {
  useAddSkillVersion,
  useCreateSkill,
  useDeleteSkill,
  useExperience,
  useSkills,
} from '@/features/profile/hooks'

const LEVELS: SkillLevel[] = ['beginner', 'intermediate', 'advanced', 'expert']

export function SkillsSection() {
  const { data: skills, isLoading, isError, error, refetch } = useSkills()
  const { data: experiences } = useExperience()
  const createSkill = useCreateSkill()
  const deleteSkill = useDeleteSkill()
  const addVersion = useAddSkillVersion()

  const [skillName, setSkillName] = useState('')
  const [skillCategory, setSkillCategory] = useState('')
  const [activeSkillId, setActiveSkillId] = useState<string | null>(null)

  const [level, setLevel] = useState<SkillLevel>('intermediate')
  const [evidence, setEvidence] = useState('')
  const [evidenceUrl, setEvidenceUrl] = useState('')
  const [workExperienceId, setWorkExperienceId] = useState('')

  function handleCreateSkill(event: FormEvent) {
    event.preventDefault()
    if (!skillName.trim()) return
    createSkill.mutate(
      { name: skillName, category: skillCategory || null },
      { onSuccess: () => { setSkillName(''); setSkillCategory('') } }
    )
  }

  function resetVersionForm() {
    setLevel('intermediate')
    setEvidence('')
    setEvidenceUrl('')
    setWorkExperienceId('')
  }

  function handleAddVersion(event: FormEvent) {
    event.preventDefault()
    if (!activeSkillId) return
    addVersion.mutate(
      {
        skillId: activeSkillId,
        input: {
          level,
          evidence,
          evidence_url: evidenceUrl || null,
          work_experience_id: workExperienceId || null,
        },
      },
      {
        onSuccess: () => {
          setActiveSkillId(null)
          resetVersionForm()
        },
      }
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Skills</CardTitle>
        <CardDescription>
          Every assessment is kept, never overwritten — evidence is required, not optional.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <form onSubmit={handleCreateSkill} className="flex gap-2">
          <Input placeholder="Skill name" value={skillName} onChange={(e) => setSkillName(e.target.value)} />
          <Input
            placeholder="Category (optional)"
            value={skillCategory}
            onChange={(e) => setSkillCategory(e.target.value)}
            className="w-48"
          />
          <Button type="submit" variant="outline" disabled={createSkill.isPending}>
            <Plus className="h-4 w-4" /> Add skill
          </Button>
        </form>
        {createSkill.isError && (
          <ErrorState message={createSkill.error instanceof Error ? createSkill.error.message : 'Failed to add skill'} />
        )}

        {isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-20 w-full" />
            <Skeleton className="h-20 w-full" />
          </div>
        )}
        {isError && (
          <ErrorState
            message={error instanceof Error ? error.message : 'Failed to load skills'}
            onRetry={() => refetch()}
          />
        )}
        {skills?.length === 0 && (
          <EmptyState
            icon={<Sparkles className="h-8 w-8" />}
            title="No skills yet"
            description="Add a skill, then back it with a real assessment and evidence."
          />
        )}

        <ul className="space-y-4">
          {skills?.map((skill) => (
            <li key={skill.id} className="rounded-md border border-border p-4">
              <div className="flex items-start justify-between gap-2">
                <div className="flex items-center gap-2">
                  <p className="font-medium">{skill.name}</p>
                  {skill.category && <Badge variant="secondary">{skill.category}</Badge>}
                </div>
                <div className="flex items-center gap-1">
                  <Button variant="outline" size="sm" onClick={() => setActiveSkillId(skill.id)}>
                    New assessment
                  </Button>
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`Delete ${skill.name}`}
                    onClick={() => deleteSkill.mutate(skill.id)}
                  >
                    <Trash2 className="h-4 w-4" />
                  </Button>
                </div>
              </div>

              {skill.versions.length === 0 ? (
                <p className="mt-3 text-sm text-muted-foreground">No assessments yet.</p>
              ) : (
                <ol className="mt-3 space-y-3 border-l border-border pl-4">
                  {skill.versions.map((version) => (
                    <li key={version.id}>
                      <div className="flex items-center gap-2">
                        <Badge variant="outline" className="capitalize">
                          {version.level}
                        </Badge>
                        <span className="text-xs text-muted-foreground">
                          {new Date(version.asserted_at).toLocaleDateString()}
                        </span>
                      </div>
                      <p className="mt-1 text-sm">{version.evidence}</p>
                      {version.evidence_url && (
                        <a
                          href={version.evidence_url}
                          target="_blank"
                          rel="noreferrer"
                          className="text-xs text-primary underline-offset-4 hover:underline"
                        >
                          {version.evidence_url}
                        </a>
                      )}
                    </li>
                  ))}
                </ol>
              )}
            </li>
          ))}
        </ul>
      </CardContent>

      <Dialog open={activeSkillId !== null} onOpenChange={(open) => !open && setActiveSkillId(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>New assessment</DialogTitle>
          </DialogHeader>
          <form onSubmit={handleAddVersion} className="space-y-4">
            <div className="space-y-2">
              <Label htmlFor="level">Level</Label>
              <Select id="level" value={level} onChange={(e) => setLevel(e.target.value as SkillLevel)}>
                {LEVELS.map((l) => (
                  <option key={l} value={l} className="capitalize">
                    {l}
                  </option>
                ))}
              </Select>
            </div>
            <div className="space-y-2">
              <Label htmlFor="evidence">Evidence</Label>
              <Textarea
                id="evidence"
                required
                minLength={10}
                placeholder="What backs this claim — a project, a role, a credential. Not a guess."
                value={evidence}
                onChange={(e) => setEvidence(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="evidence_url">Evidence link (optional)</Label>
              <Input
                id="evidence_url"
                placeholder="https://…"
                value={evidenceUrl}
                onChange={(e) => setEvidenceUrl(e.target.value)}
              />
            </div>
            {experiences && experiences.length > 0 && (
              <div className="space-y-2">
                <Label htmlFor="work_experience">Linked role (optional)</Label>
                <Select
                  id="work_experience"
                  value={workExperienceId}
                  onChange={(e) => setWorkExperienceId(e.target.value)}
                >
                  <option value="">None</option>
                  {experiences.map((experience) => (
                    <option key={experience.id} value={experience.id}>
                      {experience.title} · {experience.company}
                    </option>
                  ))}
                </Select>
              </div>
            )}
            {addVersion.isError && (
              <ErrorState
                message={addVersion.error instanceof Error ? addVersion.error.message : 'Failed to save'}
              />
            )}
            <DialogFooter>
              <Button type="submit" disabled={addVersion.isPending}>
                {addVersion.isPending ? 'Saving…' : 'Save assessment'}
              </Button>
            </DialogFooter>
          </form>
        </DialogContent>
      </Dialog>
    </Card>
  )
}
