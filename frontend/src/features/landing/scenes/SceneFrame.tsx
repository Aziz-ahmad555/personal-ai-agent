import type { ReactNode } from 'react'
import { PerspectiveCamera } from '@react-three/drei'
import { useThree } from '@react-three/fiber'

const FOV = 40

interface Props {
  children: ReactNode
  /** Camera distance. */
  z?: number
  /** Half-width of the content; the scene shrinks to keep it inside a narrow view. */
  extent?: number
}

/** The camera and light every scene shares, so each View starts from the same baseline. */
export function SceneFrame({ children, z = 7, extent }: Props) {
  const size = useThree((state) => state.size)
  const halfWidth = z * Math.tan((FOV * Math.PI) / 360) * (size.width / Math.max(1, size.height))
  const scale = extent ? Math.min(1, halfWidth / extent) : 1
  return (
    <>
      <PerspectiveCamera makeDefault position={[0, 0, z]} fov={FOV} />
      <ambientLight intensity={0.9} />
      <group scale={scale}>{children}</group>
    </>
  )
}
