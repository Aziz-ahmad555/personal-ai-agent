import { useLayoutEffect, useMemo, useRef, type RefObject } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import * as THREE from 'three'
import { COLORS } from '@/features/landing/theme'
import { buildGraph } from '@/features/landing/graph'
import type { DragState } from '@/features/landing/hooks'
import { SceneFrame } from '@/features/landing/scenes/SceneFrame'

interface Props {
  drag: RefObject<DragState>
  reduced: boolean
}

function Graph({ drag, reduced }: Props) {
  const size = useThree((state) => state.size)
  const narrow = size.width < 640
  const graph = useMemo(() => buildGraph(narrow ? 40 : 56), [narrow])
  const group = useRef<THREE.Group>(null)
  const nodes = useRef<THREE.InstancedMesh>(null)
  const halos = useRef<THREE.InstancedMesh>(null)

  const lines = useMemo(() => {
    const positions = new Float32Array(graph.edges.length * 6)
    graph.edges.forEach(([a, b], i) => {
      positions.set(graph.nodes[a].position, i * 6)
      positions.set(graph.nodes[b].position, i * 6 + 3)
    })
    const geometry = new THREE.BufferGeometry()
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    const material = new THREE.LineBasicMaterial({ color: COLORS.teal, transparent: true, opacity: 0.22 })
    return new THREE.LineSegments(geometry, material)
  }, [graph])

  useLayoutEffect(() => {
    const matrix = new THREE.Matrix4()
    const color = new THREE.Color()
    graph.nodes.forEach((node, i) => {
      matrix.makeTranslation(...node.position)
      nodes.current?.setMatrixAt(i, matrix)
      halos.current?.setMatrixAt(i, matrix)
      color.set(node.verified ? COLORS.teal : COLORS.amber)
      nodes.current?.setColorAt(i, color)
      halos.current?.setColorAt(i, color)
    })
    for (const mesh of [nodes.current, halos.current]) {
      if (!mesh) continue
      mesh.instanceMatrix.needsUpdate = true
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true
    }
  }, [graph])

  useFrame((_, delta) => {
    const state = drag.current
    if (!group.current || !state) return
    state.tick(delta, !reduced)
    group.current.rotation.y = state.yaw
    group.current.rotation.x = state.pitch
  })

  const wide = size.width / size.height > 1.15
  return (
    <group position={[wide ? 2.3 : 0, wide ? 0 : -1.6, 0]} scale={wide ? 0.8 : 0.5}>
      <group ref={group}>
        <primitive object={lines} />
        <instancedMesh key={`n${graph.nodes.length}`} ref={nodes} args={[undefined, undefined, graph.nodes.length]}>
          <sphereGeometry args={[0.07, 12, 8]} />
          <meshBasicMaterial toneMapped={false} />
        </instancedMesh>
        <instancedMesh key={`h${graph.nodes.length}`} ref={halos} args={[undefined, undefined, graph.nodes.length]}>
          <sphereGeometry args={[0.17, 12, 8]} />
          <meshBasicMaterial transparent opacity={0.16} depthWrite={false} toneMapped={false} />
        </instancedMesh>
      </group>
    </group>
  )
}

export function HeroGraph(props: Props) {
  return (
    <SceneFrame z={8}>
      <Graph {...props} />
    </SceneFrame>
  )
}
