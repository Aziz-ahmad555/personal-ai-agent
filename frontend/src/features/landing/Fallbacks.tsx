import { buildGraph } from '@/features/landing/graph'
import { COLORS } from '@/features/landing/theme'
import { needleFraction } from '@/features/landing/progress'

/**
 * Static SVG stand-ins for each scene. They show when WebGL is unavailable or the canvas fails, so
 * the page keeps its meaning and layout without any 3D.
 */

export function HeroFallback() {
  const graph = buildGraph(40)
  const point = (i: number): [number, number] => {
    const [x, y, z] = graph.nodes[i].position
    const yaw = 0.5
    return [x * Math.cos(yaw) - z * Math.sin(yaw), y]
  }
  return (
    <svg className="lp-fallback-hero" viewBox="-3.4 -3.4 6.8 6.8" role="presentation">
      {graph.edges.map(([a, b]) => {
        const [x1, y1] = point(a)
        const [x2, y2] = point(b)
        return <line key={`${a}-${b}`} x1={x1} y1={y1} x2={x2} y2={y2} stroke={COLORS.teal} strokeOpacity={0.22} strokeWidth={0.015} />
      })}
      {graph.nodes.map((node, i) => {
        const [x, y] = point(i)
        const color = node.verified ? COLORS.teal : COLORS.amber
        return (
          <g key={i}>
            <circle cx={x} cy={y} r={0.17} fill={color} fillOpacity={0.16} />
            <circle cx={x} cy={y} r={0.07} fill={color} />
          </g>
        )
      })}
    </svg>
  )
}

export function EvidenceFallback() {
  const ys = [-1.6, -0.8, 0, 0.8, 1.6]
  return (
    <svg className="lp-fallback" viewBox="-4 -2.6 8 5.2" role="presentation">
      {ys.map((y) => (
        <g key={y}>
          <rect x={-3.5} y={y - 0.35} width={1.4} height={0.7} rx={0.06} fill={COLORS.panel} stroke={COLORS.teal} strokeWidth={0.03} />
          <line x1={-2.1} y1={y} x2={1.5} y2={0} stroke={COLORS.teal} strokeOpacity={0.7} strokeWidth={0.03} />
        </g>
      ))}
      <polygon points="1.5,-0.45 1.95,0 1.5,0.45 1.05,0" fill={COLORS.teal} />
      <circle cx={1.5} cy={0} r={0.7} fill="none" stroke={COLORS.teal} strokeOpacity={0.5} strokeWidth={0.03} />
    </svg>
  )
}

export function LadderFallback() {
  const colors = [COLORS.teal, '#5FD89E', '#9CC57A', '#CDB562', COLORS.amber]
  return (
    <svg className="lp-fallback" viewBox="-4 -3 8 6" role="presentation">
      {colors.map((color, i) => {
        const y = -2 + i * 0.95
        return (
          <polygon
            key={color}
            points={`-2.4,${y + 0.5} -0.6,${y - 0.35} 2.4,${y - 0.35} 0.6,${y + 0.5}`}
            fill={color}
            fillOpacity={0.2 - i * 0.02}
            stroke={color}
            strokeWidth={0.03}
          />
        )
      })}
    </svg>
  )
}

const arcPoint = (degrees: number): [number, number] => [
  100 + 80 * Math.cos((degrees * Math.PI) / 180),
  100 - 80 * Math.sin((degrees * Math.PI) / 180),
]

export function GaugeFallback({ tier }: { tier: number }) {
  const colors = [COLORS.teal, COLORS.amber, COLORS.red]
  const rotation = 90 - needleFraction((tier + 0.5) / 3) * 180
  return (
    <svg className="lp-fallback" viewBox="0 0 200 120" role="presentation">
      {colors.map((color, i) => {
        const [x1, y1] = arcPoint(178 - i * 60)
        const [x2, y2] = arcPoint(122 - i * 60)
        return (
          <path
            key={color}
            d={`M ${x1} ${y1} A 80 80 0 0 1 ${x2} ${y2}`}
            fill="none"
            stroke={color}
            strokeWidth={14}
            strokeOpacity={i === tier ? 1 : 0.32}
          />
        )
      })}
      <g className="lp-needle" style={{ transform: `rotate(${rotation}deg)`, transformOrigin: '100px 100px' }}>
        <line x1={100} y1={100} x2={100} y2={30} stroke="#E6EDF3" strokeWidth={3} strokeLinecap="round" />
      </g>
      <circle cx={100} cy={100} r={6} fill="#E6EDF3" />
    </svg>
  )
}
