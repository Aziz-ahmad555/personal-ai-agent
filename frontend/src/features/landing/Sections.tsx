import { useRef, useState } from 'react'
import { Link } from 'react-router-dom'
import { COLORS } from '@/features/landing/theme'
import { EVIDENCE, FOOTER, HERO, LADDER, RISK } from '@/features/landing/copy'
import { useDragRotation, useSectionProgress } from '@/features/landing/hooks'
import { tierIndex } from '@/features/landing/progress'
import { useSceneMode } from '@/features/landing/scene-context'
import { SceneSlot } from '@/features/landing/scene-mode'
import { EvidenceFallback, GaugeFallback, HeroFallback, LadderFallback } from '@/features/landing/Fallbacks'
import { HeroGraph } from '@/features/landing/scenes/HeroGraph'
import { EvidenceScene } from '@/features/landing/scenes/EvidenceScene'
import { LadderScene } from '@/features/landing/scenes/LadderScene'
import { RiskGauge } from '@/features/landing/scenes/RiskGauge'

const RISK_COLORS = [COLORS.teal, COLORS.amber, COLORS.red]
const LADDER_COLORS = [COLORS.teal, '#5FD89E', '#9CC57A', '#CDB562', COLORS.amber]

export function Hero({ signedIn }: { signedIn: boolean }) {
  const ref = useRef<HTMLElement>(null)
  const { reduced } = useSceneMode()
  const drag = useDragRotation(ref)
  const cta = signedIn ? HERO.signedIn : HERO.signedOut
  return (
    <section ref={ref} className="lp-hero" aria-labelledby="lp-hero-title">
      <SceneSlot className="lp-view" fallback={<HeroFallback />}>
        <HeroGraph drag={drag} reduced={reduced} />
      </SceneSlot>
      <div className="lp-hero-copy">
        <h1 id="lp-hero-title" className="lp-display lp-h1">
          {HERO.headline}
        </h1>
        <p className="lp-lede">{HERO.subhead}</p>
        <div className="lp-actions">
          <Link to={cta.to} className="lp-btn lp-btn-primary">
            {cta.label}
          </Link>
        </div>
        <p className="lp-legend">
          <span className="lp-dot" style={{ background: COLORS.teal }} /> Verified
          <span className="lp-dot" style={{ background: COLORS.amber }} /> Not yet confirmed
          <span className="lp-legend-hint">Drag the graph to turn it.</span>
        </p>
      </div>
    </section>
  )
}

export function EvidenceSection() {
  const ref = useRef<HTMLElement>(null)
  const { reduced } = useSceneMode()
  const [locked, setLocked] = useState(reduced)
  const progress = useSectionProgress(ref, {
    fixed: reduced ? 1 : undefined,
    onChange: (value) => setLocked(value >= 0.5),
  })
  return (
    <section ref={ref} className="lp-section" aria-labelledby="lp-evidence-title">
      <div className="lp-split">
        <div>
          <h2 id="lp-evidence-title" className="lp-display lp-h2">
            {EVIDENCE.heading}
          </h2>
          <p className="lp-lede">{EVIDENCE.intro}</p>
        </div>
        <div className="lp-visual-pair">
          <SceneSlot className="lp-visual" fallback={<EvidenceFallback />}>
            <EvidenceScene progress={progress} />
          </SceneSlot>
          <article className="lp-card" data-locked={locked} aria-label={`Example: ${EVIDENCE.title}`}>
            <p className="lp-note">{EVIDENCE.exampleLabel}</p>
            <h3 className="lp-display lp-card-title">{EVIDENCE.title}</h3>
            <p className="lp-score">
              <span className="lp-mono lp-score-value">{EVIDENCE.score}%</span>
              <span>{EVIDENCE.scoreLabel}</span>
            </p>
            <ul className="lp-checks">
              {EVIDENCE.checks.map((line) => (
                <li key={line}>{line}</li>
              ))}
            </ul>
            <p className="lp-uncertainty">{EVIDENCE.uncertainty}</p>
            <p className="lp-stamp lp-mono">{EVIDENCE.source}</p>
          </article>
        </div>
      </div>
    </section>
  )
}

export function LadderSection() {
  const ref = useRef<HTMLElement>(null)
  const { reduced } = useSceneMode()
  const progress = useSectionProgress(ref)
  return (
    <section ref={ref} className="lp-section" aria-labelledby="lp-ladder-title">
      <div className="lp-split lp-split-flip">
        <SceneSlot className="lp-visual" fallback={<LadderFallback />}>
          <LadderScene progress={progress} reduced={reduced} />
        </SceneSlot>
        <div>
          <h2 id="lp-ladder-title" className="lp-display lp-h2">
            {LADDER.heading}
          </h2>
          <p className="lp-lede">{LADDER.intro}</p>
          <ol className="lp-ladder">
            {LADDER.tiers.map((tier, i) => (
              <li key={tier.name} style={{ borderLeftColor: LADDER_COLORS[i] }}>
                <strong className="lp-display">{tier.name}</strong>
                <span>{tier.note}</span>
              </li>
            ))}
          </ol>
        </div>
      </div>
    </section>
  )
}

export function RiskSection() {
  const tiersRef = useRef<HTMLDivElement>(null)
  const { reduced } = useSceneMode()
  const [active, setActive] = useState(0)
  const progress = useSectionProgress(tiersRef, {
    mode: 'anchored',
    onChange: (value) => setActive(tierIndex(value)),
  })
  return (
    <section className="lp-section lp-risk" aria-labelledby="lp-risk-title">
      <div className="lp-split">
        <div className="lp-sticky">
          <SceneSlot className="lp-visual lp-visual-gauge" fallback={<GaugeFallback tier={active} />}>
            <RiskGauge progress={progress} reduced={reduced} />
          </SceneSlot>
        </div>
        <div>
          <h2 id="lp-risk-title" className="lp-display lp-h2">
            {RISK.heading}
          </h2>
          <p className="lp-lede">{RISK.intro}</p>
          <div ref={tiersRef} className="lp-risk-tiers">
            {RISK.tiers.map((tier, i) => (
              <article key={tier.name} className="lp-risk-tier" data-active={i === active}>
                <h3 className="lp-display" style={{ color: RISK_COLORS[i] }}>
                  {tier.name}
                </h3>
                <p>{tier.detail}</p>
              </article>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

export function LandingFooter({ signedIn }: { signedIn: boolean }) {
  return (
    <footer className="lp-footer">
      <p>{FOOTER.line}</p>
      <Link to={signedIn ? '/dashboard' : '/login'}>{signedIn ? 'Open the app' : 'Sign in'}</Link>
    </footer>
  )
}
