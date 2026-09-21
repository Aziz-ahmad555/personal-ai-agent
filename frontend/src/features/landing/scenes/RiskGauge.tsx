import { useMemo, useRef, type RefObject } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { COLORS } from '@/features/landing/theme'
import { needleFraction, needleRotation, tierIndex } from '@/features/landing/progress'
import { SceneFrame } from '@/features/landing/scenes/SceneFrame'

const ARC = [COLORS.teal, COLORS.amber, COLORS.red]

function Gauge({ progress, reduced }: { progress: RefObject<number>; reduced: boolean }) {
  const needle = useRef<THREE.Group>(null)
  const segments = useRef<(THREE.MeshBasicMaterial | null)[]>([])
  const current = useRef(0.5)
  const shape = useMemo(() => {
    const s = new THREE.Shape()
    s.moveTo(-0.05, 0)
    s.lineTo(0, 1.45)
    s.lineTo(0.05, 0)
    s.closePath()
    return s
  }, [])

  useFrame((_, delta) => {
    const p = progress.current ?? 0
    const target = reduced ? 0.5 : needleFraction(p)
    current.current += (target - current.current) * (1 - Math.exp(-6 * delta))
    if (needle.current) needle.current.rotation.z = needleRotation(current.current)
    const active = tierIndex(p)
    segments.current.forEach((material, i) => {
      if (!material) return
      const goal = i === active ? 1 : 0.32
      material.opacity = reduced ? goal : material.opacity + (goal - material.opacity) * (1 - Math.exp(-8 * delta))
    })
  })

  return (
    <group position={[0, -0.7, 0]}>
      {ARC.map((color, i) => (
        <mesh key={color}>
          <ringGeometry args={[1.6, 2, 40, 1, Math.PI - (i + 1) * (Math.PI / 3) + 0.02, Math.PI / 3 - 0.04]} />
          <meshBasicMaterial
            ref={(m) => void (segments.current[i] = m)}
            color={color}
            transparent
            opacity={0.32}
            toneMapped={false}
          />
        </mesh>
      ))}
      <group ref={needle}>
        <mesh>
          <shapeGeometry args={[shape]} />
          <meshBasicMaterial color="#E6EDF3" />
        </mesh>
      </group>
      <mesh>
        <circleGeometry args={[0.13, 24]} />
        <meshBasicMaterial color="#E6EDF3" />
      </mesh>
    </group>
  )
}

export function RiskGauge(props: { progress: RefObject<number>; reduced: boolean }) {
  return (
    <SceneFrame z={6.5} extent={2.2}>
      <Gauge {...props} />
    </SceneFrame>
  )
}
