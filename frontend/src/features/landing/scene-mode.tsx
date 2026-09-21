import { Component, type ReactNode } from 'react'
import { View } from '@react-three/drei'
import { useSceneMode } from '@/features/landing/scene-context'

interface SlotProps {
  className?: string
  fallback: ReactNode
  children: ReactNode
}

/** One section's visual: a View into the shared canvas, or its static fallback. */
export function SceneSlot({ className, fallback, children }: SlotProps) {
  const { mode } = useSceneMode()
  if (mode === 'fallback') {
    return (
      <div className={className} aria-hidden="true">
        {fallback}
      </div>
    )
  }
  return (
    <View className={className} aria-hidden="true">
      {children}
    </View>
  )
}

interface BoundaryProps {
  onError: () => void
  children: ReactNode
}

/** Any error while creating or drawing the canvas drops the page to the static fallback. */
export class SceneBoundary extends Component<BoundaryProps, { failed: boolean }> {
  state = { failed: false }

  static getDerivedStateFromError() {
    return { failed: true }
  }

  componentDidCatch() {
    this.props.onError()
  }

  render() {
    return this.state.failed ? null : this.props.children
  }
}
