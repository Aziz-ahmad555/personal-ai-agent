import { useState } from 'react'
import type { FormEvent } from 'react'
import { Briefcase, Trash2 } from 'lucide-react'
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
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import { EmptyState } from '@/components/layout/empty-state'
import { ErrorState } from '@/components/layout/error-state'
import { useCreateExperience, useDeleteExperience, useExperience } from '@/features/profile/hooks'

export function ExperienceSection() {
  const { data: experiences, isLoading, isError, error, refetch } = useExperience()
  const createExperience = useCreateExperience()
  const deleteExperience = useDeleteExperience()
  const [open, setOpen] = useState(false)

  const [company, setCompany] = useState('')
  const [title, setTitle] = useState('')
  const [location, setLocation] = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate] = useState('')
  const [description, setDescription] = useState('')

  function resetForm() {
    setCompany('')
    setTitle('')
    setLocation('')
    setStartDate('')
    setEndDate('')
    setDescription('')
  }

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    createExperience.mutate(
      {
        company,
        title,
        location: location || null,
        start_date: startDate,
        end_date: endDate || null,
        description: description || null,
      },
      { onSuccess: () => { setOpen(false); resetForm() } }
    )
  }

  return (
    <Card>
      <CardHeader className="flex flex-row items-center justify-between">
        <div>
          <CardTitle>Work experience</CardTitle>
          <CardDescription>Roles you've held — evidence for skill claims can link back to these.</CardDescription>
        </div>
        <Dialog open={open} onOpenChange={setOpen}>
          <DialogTrigger asChild>
            <Button size="sm">Add</Button>
          </DialogTrigger>
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Add work experience</DialogTitle>
            </DialogHeader>
            <form onSubmit={handleSubmit} className="space-y-4">
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="company">Company</Label>
                  <Input id="company" required value={company} onChange={(e) => setCompany(e.target.value)} />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="title">Title</Label>
                  <Input id="title" required value={title} onChange={(e) => setTitle(e.target.value)} />
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="exp-location">Location</Label>
                <Input id="exp-location" value={location} onChange={(e) => setLocation(e.target.value)} />
              </div>
              <div className="grid grid-cols-2 gap-4">
                <div className="space-y-2">
                  <Label htmlFor="start_date">Start date</Label>
                  <Input
                    id="start_date"
                    type="date"
                    required
                    value={startDate}
                    onChange={(e) => setStartDate(e.target.value)}
                  />
                </div>
                <div className="space-y-2">
                  <Label htmlFor="end_date">End date (blank = current)</Label>
                  <Input id="end_date" type="date" value={endDate} onChange={(e) => setEndDate(e.target.value)} />
                </div>
              </div>
              <div className="space-y-2">
                <Label htmlFor="description">Description</Label>
                <Textarea id="description" value={description} onChange={(e) => setDescription(e.target.value)} />
              </div>
              {createExperience.isError && (
                <ErrorState
                  message={
                    createExperience.error instanceof Error
                      ? createExperience.error.message
                      : 'Failed to save'
                  }
                />
              )}
              <DialogFooter>
                <Button type="submit" disabled={createExperience.isPending}>
                  {createExperience.isPending ? 'Saving…' : 'Save'}
                </Button>
              </DialogFooter>
            </form>
          </DialogContent>
        </Dialog>
      </CardHeader>
      <CardContent>
        {isLoading && (
          <div className="space-y-2">
            <Skeleton className="h-16 w-full" />
            <Skeleton className="h-16 w-full" />
          </div>
        )}
        {isError && (
          <ErrorState
            message={error instanceof Error ? error.message : 'Failed to load work experience'}
            onRetry={() => refetch()}
          />
        )}
        {experiences?.length === 0 && (
          <EmptyState
            icon={<Briefcase className="h-8 w-8" />}
            title="No work experience yet"
            description="Add a role to start building evidence-backed skill history."
          />
        )}
        <ul className="space-y-3">
          {experiences?.map((experience) => (
            <li key={experience.id} className="rounded-md border border-border p-4">
              <div className="flex items-start justify-between gap-2">
                <div>
                  <p className="font-medium">
                    {experience.title} · {experience.company}
                  </p>
                  <p className="text-sm text-muted-foreground">
                    {experience.start_date} — {experience.end_date ?? 'present'}
                    {experience.location ? ` · ${experience.location}` : ''}
                  </p>
                  {experience.description && (
                    <p className="mt-2 text-sm">{experience.description}</p>
                  )}
                </div>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Delete ${experience.title} at ${experience.company}`}
                  onClick={() => deleteExperience.mutate(experience.id)}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </div>
            </li>
          ))}
        </ul>
      </CardContent>
    </Card>
  )
}
