import { lazy, Suspense } from 'react'

// The landing page carries three.js, so it loads only for visitors who open it.
const LandingPage = lazy(() => import('@/features/landing/LandingPage'))

export function LandingRoute() {
  return (
    <Suspense fallback={<div className="min-h-screen bg-[#0A0E13]" />}>
      <LandingPage />
    </Suspense>
  )
}
