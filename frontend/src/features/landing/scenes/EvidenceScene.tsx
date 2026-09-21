import { useMemo, useRef, type RefObject } from 'react'
import { useFrame } from '@react-three/fiber'
import * as THREE from 'three'
import { COLORS } from '@/features/landing/theme'
import { clamp01, smoothstep } from '@/features/landing/progress'
import { SceneFrame } from '@/features/landing/scenes/SceneFrame'

const DOCS = [1.6, 0.8, 0, -0.8, -1.6].map((y, i) => ({
  position: new THREE.Vector3(-2.0 - (i % 2) * 0.25, y, 0),
}))
const CLAIM = new THREE.Vector3(2.0, 0, 0)
const GREY = new THREE.Color('#7A8794')
const TEAL = new THREE.Color(COLORS.teal)
const DOC_TEXT = new THREE.BufferGeometry().setFromPoints(
  [0.2, 0, -0.2].flatMap((y, i) => [new THREE.Vector3(-0.5, y, 0.01), new THREE.Vector3(0.5 - i * 0.25, y, 0.01)])
)
const DOC_EDGES = new THREE.EdgesGeometry(new THREE.PlaneGeometry(1.4, 0.95))

function Scene({ progress }: { progress: RefObject<number> }) {
  const claim = useRef<THREE.Mesh>(null)
  const ring = useRef<THREE.Mesh>(null)
  const docMaterials = useRef<(THREE.LineBasicMaterial | null)[]>([])

  const lines = useMemo(
    () =>
      DOCS.map(() => {
        const geometry = new THREE.BufferGeometry()
        geometry.setAttribute('position', new THREE.BufferAttribute(new Float32Array(6), 3))
        const material = new THREE.LineBasicMaterial({ color: COLORS.teal, transparent: true, opacity: 0.7 })
        return new THREE.Line(geometry, material)
      }),
    []
  )

  useFrame(() => {
    const p = progress.current ?? 0
    const lock = smoothstep(0.46, 0.56, p)
    DOCS.forEach((doc, i) => {
      const draw = clamp01((p - 0.1 - i * 0.05) / 0.3)
      const start = doc.position.clone().add(new THREE.Vector3(0.7, 0, 0))
      const end = start.clone().lerp(CLAIM, draw)
      const attribute = lines[i].geometry.attributes.position as THREE.BufferAttribute
      attribute.setXYZ(0, start.x, start.y, start.z)
      attribute.setXYZ(1, end.x, end.y, end.z)
      attribute.needsUpdate = true
      docMaterials.current[i]?.color.copy(GREY).lerp(TEAL, draw)
    })
    if (claim.current) {
      const material = claim.current.material as THREE.MeshBasicMaterial
      material.color.copy(GREY).lerp(TEAL, lock)
      claim.current.scale.setScalar(0.8 + lock * 0.35)
    }
    if (ring.current) {
      ring.current.scale.setScalar(0.6 + lock * 0.7)
      ;(ring.current.material as THREE.MeshBasicMaterial).opacity = lock * 0.5
    }
  })

  return (
    <>
      {DOCS.map((doc, i) => (
        <group key={i} position={doc.position} rotation={[0, 0.35, 0]}>
          <mesh>
            <planeGeometry args={[1.4, 0.95]} />
            <meshBasicMaterial color="#1b242e" side={THREE.DoubleSide} />
          </mesh>
          <lineSegments geometry={DOC_TEXT}>
            <lineBasicMaterial color="#3a4653" />
          </lineSegments>
          <lineSegments geometry={DOC_EDGES}>
            <lineBasicMaterial ref={(m) => void (docMaterials.current[i] = m)} color="#7A8794" />
          </lineSegments>
        </group>
      ))}
      {lines.map((line, i) => (
        <primitive key={i} object={line} />
      ))}
      <mesh ref={claim} position={CLAIM}>
        <octahedronGeometry args={[0.32, 0]} />
        <meshBasicMaterial color="#7A8794" toneMapped={false} />
      </mesh>
      <mesh ref={ring} position={CLAIM}>
        <ringGeometry args={[0.55, 0.6, 48]} />
        <meshBasicMaterial color={COLORS.teal} transparent opacity={0} toneMapped={false} />
      </mesh>
    </>
  )
}

export function EvidenceScene({ progress }: { progress: RefObject<number> }) {
  return (
    <SceneFrame z={7.5} extent={3.2}>
      <Scene progress={progress} />
    </SceneFrame>
  )
}
