import { useState } from 'react'
import type { FormEvent } from 'react'
import { GraduationCap, Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/layout/empty-state'
import { ErrorState } from '@/components/layout/error-state'
import { useCreateEducation, useDeleteEducation, useEducation } from '@/features/profile/hooks'

export function EducationSection() {
  const { data: education, isLoading, isError, error, refetch } = useEducation()
  const createEducation = useCreateEducation()
  const deleteEducation = useDeleteEducation()
  const [open, setOpen] = useState(false)

  const [institution, setInstitution] = useState('')
  const [degree, setDegree] = useState('')
  const [field, setField] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')

  function resetForm() {
    setInstitution('')
    setDegree('')
    setField('')
    setStartDate('')
    setEndDate('')
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    createEducation.mutate(
      {
        institution,
        degree: degree || null,
        field: field || null,
        start_date: startDate || null,
        end_date: endDate || null,
      },
      { onSuccess: () => { setOpen(false); resetForm() } }
    )
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle>Education</CardTitle>
          <CardDescription>Degrees and credentials.</CardDescription>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button size="sm">Add</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add education</DialogTitle>
            </DialogHeader>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="space-y-2">
                <Label htmlFor="institution">Institution</Label>
                <Input
                  id="institution"
                  required
                  value={institution}
                  onChange={(e) => setInstitution(e.target.value)}
                />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="degree">Degree</Label>
                  <Input id="degree" value={degree} onChange={(e) => setDegree(e.target.value)} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="field">Field</Label>
                  <Input id="field" value={field} onChange={(e) => setField(e.target.value)} />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="edu_start">Start date</Label>
                  <Input id="edu_start" type="date" value={startDate} onChange={(e) => setStartDate(e.target.value)} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="edu_end">End date</Label>
                  <Input id="edu_end" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
                </div>
              </div>
              {createEducation.isError && (
                <ErrorState
                  message={
                    createEducation.error instanceof Error ? createEducation.error.message : 'Failed to save'
                  }
                />
              )}
              <DialogFooter>
                <Button type="submit" disabled={createEducation.isPending}>
                  {createEducation.isPending ? 'Saving…' : 'Save'}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </CardHeader>
      <CardContent>
        {isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-14 w-full" />
          </div>
        )}
        {isError && (
          <ErrorState
            message={error instanceof Error ? error.message : 'Failed to load education'}
            onRetry={() => refetch()}
          />
        )}
        {education?.length === 0 && (
          <EmptyState icon={<GraduationCap className="h-8 w-8" />} title="No education added yet" />
        )}
        <ul className="space-y-3">
          {education?.map((entry) => (
            <li key={entry.id} className="flex items-start justify-between gap-2 rounded-md border border-border p-4">
              <div>
                <p className="font-medium">
                  {entry.degree ? `${entry.degree}${entry.field ? `, ${entry.field}` : ''}` : entry.institution}
                </p>
                <p className="text-sm text-muted-foreground">
                  {entry.institution}
                  {entry.start_date ? ` · ${entry.start_date} — ${entry.end_date ?? 'present'}` : ''}
                </p>
              </div>
              <Button
                variant="ghost"
                size="icon"
                aria-label={`Delete ${entry.institution}`}
                onClick={() => deleteEducation.mutate(entry.id)}
              >
                <Trash2 className="h-4 w-4" />
              </Button>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
