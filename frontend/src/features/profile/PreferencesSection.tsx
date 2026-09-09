import { useState } from 'react'
import type { FormEvent } from 'react'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Select } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { Skeleton } from '@/components/ui/skeleton'
import { ErrorState } from '@/components/layout/error-state'
import type { Preferences, RemotePreference } from '@/lib/api'
import { usePreferences, useUpdatePreferences } from '@/features/profile/hooks'

const REMOTE_OPTIONS: { value: RemotePreference; label: string }[] = [
  { value: 'no_preference', label: 'No preference' },
  { value: 'remote', label: 'Remote' },
  { value: 'hybrid', label: 'Hybrid' },
  { value: 'onsite', label: 'Onsite' },
]

function toCsv(items: string[]): string {
  return items.join(', ')
}

function fromCsv(value: string): string[] {
  return value
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean)
}

export function PreferencesSection() {
  const { data: preferences, isLoading, isError, error, refetch } = usePreferences()

  if (isLoading) {
    return (
      <Card>
        <CardHeader>
          <CardTitle>Preferences</CardTitle>
        </CardHeader>
        <CardContent className="space-y-3">
          <Skeleton className="h-9 w-full" />
          <Skeleton className="h-9 w-full" />
        </CardContent>
      </Card>
    )
  }

  if (isError || !preferences) {
    return (
      <Card>
        <CardContent className="pt-6">
          <ErrorState
            message={error instanceof Error ? error.message : 'Failed to load preferences'}
            onRetry={() => refetch()}
          />
        </CardContent>
      </Card>
    )
  }

  return <PreferencesForm key={preferences.updated_at} preferences={preferences} />
}

function PreferencesForm({ preferences }: { preferences: Preferences }) {
  const updatePreferences = useUpdatePreferences()

  const [jobTypes, setJobTypes] = useState(toCsv(preferences.job_types))
  const [remotePreference, setRemotePreference] = useState<RemotePreference>(preferences.remote_preference)
  const [locations, setLocations] = useState(toCsv(preferences.locations))
  const [salaryMin, setSalaryMin] = useState(preferences.salary_min?.toString() ?? '')
  const [salaryMax, setSalaryMax] = useState(preferences.salary_max?.toString() ?? '')
  const [industriesInclude, setIndustriesInclude] = useState(toCsv(preferences.industries_include))
  const [industriesExclude, setIndustriesExclude] = useState(toCsv(preferences.industries_exclude))
  const [dealBreakers, setDealBreakers] = useState(preferences.deal_breakers ?? '')

  function handleSubmit(event: FormEvent) {
    event.preventDefault()
    updatePreferences.mutate({
      job_types: fromCsv(jobTypes),
      remote_preference: remotePreference,
      locations: fromCsv(locations),
      salary_min: salaryMin ? Number(salaryMin) : null,
      salary_max: salaryMax ? Number(salaryMax) : null,
      industries_include: fromCsv(industriesInclude),
      industries_exclude: fromCsv(industriesExclude),
      deal_breakers: dealBreakers || null,
    })
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle>Preferences</CardTitle>
        <CardDescription>What matters for job matching later — never inferred without you saying so.</CardDescription>
      </CardHeader>
      <CardContent>
        <form onSubmit={handleSubmit} className="space-y-4">
          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="job_types">Job types (comma-separated)</Label>
              <Input
                id="job_types"
                placeholder="full_time, contract"
                value={jobTypes}
                onChange={(e) => setJobTypes(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="remote_preference">Remote preference</Label>
              <Select
                id="remote_preference"
                value={remotePreference}
                onChange={(e) => setRemotePreference(e.target.value as RemotePreference)}
              >
                {REMOTE_OPTIONS.map((option) => (
                  <option key={option.value} value={option.value}>
                    {option.label}
                  </option>
                ))}
              </Select>
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="locations">Locations (comma-separated)</Label>
            <Input
              id="locations"
              placeholder="Remote, Austin TX"
              value={locations}
              onChange={(e) => setLocations(e.target.value)}
            />
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="salary_min">Salary min</Label>
              <Input
                id="salary_min"
                type="number"
                min={0}
                value={salaryMin}
                onChange={(e) => setSalaryMin(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="salary_max">Salary max</Label>
              <Input
                id="salary_max"
                type="number"
                min={0}
                value={salaryMax}
                onChange={(e) => setSalaryMax(e.target.value)}
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-2">
              <Label htmlFor="industries_include">Industries to include (comma-separated)</Label>
              <Input
                id="industries_include"
                value={industriesInclude}
                onChange={(e) => setIndustriesInclude(e.target.value)}
              />
            </div>
            <div className="space-y-2">
              <Label htmlFor="industries_exclude">Industries to exclude (comma-separated)</Label>
              <Input
                id="industries_exclude"
                value={industriesExclude}
                onChange={(e) => setIndustriesExclude(e.target.value)}
              />
            </div>
          </div>

          <div className="space-y-2">
            <Label htmlFor="deal_breakers">Deal-breakers</Label>
            <Textarea
              id="deal_breakers"
              placeholder="Anything that rules out a role outright."
              value={dealBreakers}
              onChange={(e) => setDealBreakers(e.target.value)}
            />
          </div>

          {updatePreferences.isError && (
            <ErrorState
              message={
                updatePreferences.error instanceof Error ? updatePreferences.error.message : 'Failed to save'
              }
            />
          )}
          <Button type="submit" disabled={updatePreferences.isPending}>
            {updatePreferences.isPending ? 'Saving…' : 'Save preferences'}
          </Button>
        </form>
      </CardContent>
    </Card>
  )
}
