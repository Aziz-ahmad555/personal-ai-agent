import { useState } from 'react'
import type { FormEvent } from 'react'
import { Trash2 } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/layout/error-state'
import type { Profile } from '@/lib/api'
import { useAddLink, useDeleteLink, useProfile, useUpdateProfile } from '@/features/profile/hooks'

export function OverviewSection() {
  const { data: profile, isLoading, isError, error, refetch } = useProfile()

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Overview</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-20 w-full" />
          <Skeleton className="h-9 w-1/2" />
        </CardContent>
      </Card>
    )
  }

  if (isError || !profile) {
    return (
      <Card>
        <CardContent className="pt-6">
          <ErrorState
            message={error instanceof Error ? error.message : 'Failed to load profile'}
            onRetry={() => refetch()}
          />
        </CardContent>
      </Card>
    )
  }

  return <OverviewForm key={profile.id} profile={profile} />
}

function OverviewForm({ profile }: { profile: Profile }) {
  const updateProfile = useUpdateProfile()
  const addLink = useAddLink()
  const deleteLink = useDeleteLink()

  const [headline, setHeadline] = useState(profile.headline ?? '')
  const [summary, setSummary] = useState(profile.summary ?? '')
  const [location, setLocation] = useState(profile.location ?? '')
  const [linkLabel, setLinkLabel] = useState('')
  const [linkUrl, setLinkUrl] = useState('')

  function handleSave(event: FormEvent) {
    event.preventDefault()
    updateProfile.mutate({ headline, summary, location })
  }

  function handleAddLink(event: FormEvent) {
    event.preventDefault()
    if (!linkLabel.trim() || !linkUrl.trim()) return
    addLink.mutate(
      { label: linkLabel, url: linkUrl },
      { onSuccess: () => { setLinkLabel(''); setLinkUrl('') } }
    )
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Overview</CardTitle>
        <CardDescription>
          Your headline, summary, and links — used as the basis for research and matching later.
        </CardDescription>
      </CardHeader>
      <CardContent className="space-y-6">
        <form onSubmit={handleSave} className="space-y-4">
          <div className="space-y-2">
            <Label htmlFor="headline">Headline</Label>
            <Input
              id="headline"
              value={headline}
              onChange={(e) => setHeadline(e.target.value)}
              placeholder="e.g. ML Engineer"
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="summary">Summary</Label>
            <Textarea
              id="summary"
              value={summary}
              onChange={(e) => setSummary(e.target.value)}
              placeholder="A few sentences about what you do."
            />
          </div>
          <div className="space-y-2">
            <Label htmlFor="location">Location</Label>
            <Input id="location" value={location} onChange={(e) => setLocation(e.target.value)} />
          </div>
          {updateProfile.isError && (
            <ErrorState
              message={updateProfile.error instanceof Error ? updateProfile.error.message : 'Failed to save'}
            />
          )}
          <Button type="submit" disabled={updateProfile.isPending}>
            {updateProfile.isPending ? 'Saving…' : 'Save'}
          </Button>
        </form>

        <div className="space-y-3 border-t border-border pt-6">
          <p className="text-sm font-medium">Links</p>
          {profile.links.length === 0 && <p className="text-sm text-muted-foreground">No links yet.</p>}
          <ul className="space-y-2">
            {profile.links.map((link) => (
              <li key={link.id} className="flex items-center justify-between gap-2 text-sm">
                <a
                  href={link.url}
                  target="_blank"
                  rel="noreferrer"
                  className="truncate text-primary underline-offset-4 hover:underline"
                >
                  {link.label}: {link.url}
                </a>
                <Button
                  variant="ghost"
                  size="icon"
                  aria-label={`Remove ${link.label}`}
                  onClick={() => deleteLink.mutate(link.id)}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </li>
            ))}
          </ul>
          <form onSubmit={handleAddLink} className="flex gap-2">
            <Input
              placeholder="Label (e.g. GitHub)"
              value={linkLabel}
              onChange={(e) => setLinkLabel(e.target.value)}
              className="w-40"
            />
            <Input placeholder="https://…" value={linkUrl} onChange={(e) => setLinkUrl(e.target.value)} />
            <Button type="submit" variant="outline" disabled={addLink.isPending}>
              Add
            </Button>
          </form>
        </div>
      </CardContent>
    </Card>
  )
}
