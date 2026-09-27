import { Sparkles } from 'lucide-react'
import { Alert, AlertDescription } from '@/components/ui/alert'
import { isDemoMode } from '@/lib/demo'

/** Shown on every authenticated page of the public demo build only (see lib/demo.ts) — a
 * visitor should never be confused about whether this is someone's real inbox and real job
 * applications. */
export function DemoBanner() {
  if (!isDemoMode) return null

  return (
    <Alert className="mx-4 mt-3 sm:mx-6">
      <Sparkles className="h-4 w-4" />
      <AlertDescription>
        Demo mode — you're viewing sample data for a fictional person. Real account connections,
        sending, and account deletion are disabled here.
      </AlertDescription>
    </Alert>
  )
}
