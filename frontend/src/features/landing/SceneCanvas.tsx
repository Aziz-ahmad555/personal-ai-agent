import { useEffect, type RefObject } from 'react'
import { Canvas, useThree } from '@react-three/fiber'
import { View } from '@react-three/drei'

/**
 * With `frameloop="demand"` nothing redraws by itself, so under reduced motion the canvas is only
 * asked to draw again when the page scrolls, resizes or the pointer moves. No animation runs.
 */
function RedrawOnInput() {
  const invalidate = useThree((state) => state.invalidate)
  useEffect(() => {
    const events = ['scroll', 'resize', 'pointermove', 'pointerup'] as const
    const redraw = () => invalidate()
    events.forEach((name) => window.addEventListener(name, redraw, { passive: true }))
    return () => events.forEach((name) => window.removeEventListener(name, redraw))
  }, [invalidate])
  return null
}

interface Props {
  reduced: boolean
  eventSource: RefObject<HTMLElement | null>
  onLost: () => void
}

/** The one WebGL context for the whole page. Every section renders into it through a View. */
export default function SceneCanvas({ reduced, eventSource, onLost }: Props) {
  return (
    <Canvas
      className="lp-canvas"
      eventSource={eventSource as RefObject<HTMLElement>}
      dpr={[1, 1.5]}
      frameloop={reduced ? 'demand' : 'always'}
      gl={{ antialias: true, alpha: true }}
      onCreated={({ gl }) => {
        gl.domElement.addEventListener('webglcontextlost', (event) => {
          event.preventDefault()
          onLost()
        })
      }}
    >
      <View.Port />
      {reduced && <RedrawOnInput />}
    </Canvas>
  )
}
