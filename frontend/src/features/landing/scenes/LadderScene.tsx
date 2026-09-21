import { useRef, type RefObject } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { COLORS } from '@/features/landing/theme'
import { smoothstep } from '@/features/landing/progress'
import { SceneFrame } from '@/features/landing/scenes/SceneFrame'

const TIERS = 5
const PLANE_EDGES = new THREE.EdgesGeometry(new THREE.PlaneGeometry(3.6, 2.4))
/** Official is teal (verified); forums are amber (anecdote). */
const tierColor = (i: number) => new THREE.Color(COLORS.teal).lerp(new THREE.Color(COLORS.amber), i / (TIERS - 1))

function Planes({ progress, reduced }: { progress: RefObject<number>; reduced: boolean }) {
  const group = useRef<THREE.Group>(null)
  const layers = useRef<(THREE.Group | null)[]>([])

  useFrame(() => {
    const p = reduced ? 0.5 : (progress.current ?? 0)
    const spread = 0.42 + smoothstep(0.1, 0.55, p) * 0.4
    layers.current.forEach((layer, i) => {
      if (layer) layer.position.y = (2 - i) * spread
    })
    if (group.current) {
      group.current.rotation.y = (p - 0.5) * 0.9
      group.current.rotation.x = 0.55
    }
  })

  return (
    <group ref={group} position={[0, 0.2, 0]}>
      {Array.from({ length: TIERS }, (_, i) => {
        const color = tierColor(i)
        return (
          <group key={i} ref={(g) => void (layers.current[i] = g)}>
            <mesh rotation={[-Math.PI / 2, 0, 0]}>
              <planeGeometry args={[3.6, 2.4]} />
              <meshBasicMaterial
                color={color}
                transparent
                opacity={0.2 - i * 0.02}
                side={THREE.DoubleSide}
                depthWrite={false}
              />
            </mesh>
            <lineSegments rotation={[-Math.PI / 2, 0, 0]} geometry={PLANE_EDGES}>
              <lineBasicMaterial color={color} />
            </lineSegments>
          </group>
        )
      })}
    </group>
  )
}

export function LadderScene(props: { progress: RefObject<number>; reduced: boolean }) {
  return (
    <SceneFrame z={8} extent={2.6}>
      <Planes {...props} />
    </SceneFrame>
  )
}
