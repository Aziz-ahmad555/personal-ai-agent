import { lazy, Suspense, useCallback, useMemo, useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import '@fontsource-variable/space-grotesk'
import '@fontsource/ibm-plex-sans/400.css'
import '@fontsource/ibm-plex-sans/600.css'
import '@fontsource/ibm-plex-mono/400.css'
import '@fontsource/ibm-plex-mono/500.css'
import '@/features/landing/landing.css'
import { useAuthStore } from '@/stores/auth'
import { usePrefersReducedMotion } from '@/features/landing/hooks'
import { SceneModeContext } from '@/features/landing/scene-context'
import { SceneBoundary } from '@/features/landing/scene-mode'
import { EvidenceSection, Hero, LadderSection, LandingFooter, RiskSection } from '@/features/landing/Sections'
import { hasWebGL } from '@/features/landing/webgl'

const SceneCanvas = lazy(() => import('@/features/landing/SceneCanvas'))

export default function LandingPage() {
  const root = useRef<HTMLDivElement>(null)
  const signedIn = useAuthStore((state) => Boolean(state.accessToken))
  const reduced = usePrefersReducedMotion()
  const [failed, setFailed] = useState(() => !hasWebGL())
  const fail = useCallback(() => setFailed(true), [])
  const scene = useMemo(() => ({ mode: failed ? ('fallback' as const) : ('3d' as const), reduced }), [failed, reduced])

  return (
    <div ref={root} className="landing">
      <SceneModeContext.Provider value={scene}>
        {!failed && (
          <SceneBoundary onError={fail}>
            <Suspense fallback={null}>
              <SceneCanvas reduced={reduced} eventSource={root} onLost={fail} />
            </Suspense>
          </SceneBoundary>
        )}
        <div className="lp-content">
          <header className="lp-nav">
            <span className="lp-brand">
              <span className="lp-dot" style={{ background: 'var(--l-teal)' }} />
              Personal AI Agent
            </span>
            <Link to={signedIn ? '/dashboard' : '/login'}>{signedIn ? 'Open the app' : 'Sign in'}</Link>
          </header>
          <main>
            <Hero signedIn={signedIn} />
            <EvidenceSection />
            <LadderSection />
            <RiskSection />
          </main>
          <LandingFooter signedIn={signedIn} />
        </div>
      </SceneModeContext.Provider>
    </div>
  )
}
