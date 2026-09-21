import { useEffect, useRef, type RefObject } from 'react'
import { useReducedMotion } from 'framer-motion'
import { anchoredProgress, sectionProgress } from '@/features/landing/progress'

export const usePrefersReducedMotion = () => useReducedMotion() ?? false

interface Options {
  mode?: 'through' | 'anchored'
  /** Progress to hold instead of following the scroll (used under reduced motion). */
  fixed?: number
  onChange?: (progress: number) => void
}

/**
 * Tracks how far the element has scrolled through the viewport. The value lives in a ref so scenes
 * can read it every frame without re-rendering React; `onChange` fires for DOM that needs it.
 */
export function useSectionProgress(
  element: RefObject<HTMLElement | null>,
  { mode = 'through', fixed, onChange }: Options = {}
): RefObject<number> {
  const progress = useRef(fixed ?? 0)
  const notify = useRef(onChange)
  useEffect(() => {
    notify.current = onChange
  })

  useEffect(() => {
    if (fixed !== undefined) {
      progress.current = fixed
      return
    }
    let frame = 0
    const measure = () => {
      frame = 0
      const el = element.current
      if (!el) return
      const box = el.getBoundingClientRect()
      const value =
        mode === 'anchored'
          ? anchoredProgress(box, window.innerHeight)
          : sectionProgress(box, window.innerHeight)
      progress.current = value
      notify.current?.(value)
    }
    const schedule = () => {
      if (!frame) frame = requestAnimationFrame(measure)
    }
    schedule()
    window.addEventListener('scroll', schedule, { passive: true })
    window.addEventListener('resize', schedule)
    return () => {
      window.removeEventListener('scroll', schedule)
      window.removeEventListener('resize', schedule)
      if (frame) cancelAnimationFrame(frame)
    }
  }, [element, mode, fixed])

  return progress
}

export interface DragState {
  yaw: number
  pitch: number
  active: boolean
  /** Advance the slow auto-rotate; does nothing while dragging or when `auto` is false. */
  tick: (delta: number, auto: boolean) => void
}

/**
 * Horizontal-first drag rotation. The element keeps `touch-action: pan-y`, so a vertical swipe on
 * a phone still scrolls the page and only a sideways drag turns the graph.
 */
export function useDragRotation(element: RefObject<HTMLElement | null>, initialYaw = 0.4) {
  const state = useRef<DragState>({
    yaw: initialYaw,
    pitch: 0.15,
    active: false,
    tick(delta, auto) {
      if (auto && !this.active) this.yaw += delta * 0.1
    },
  })

  useEffect(() => {
    const el = element.current
    if (!el) return
    let lastX = 0
    let lastY = 0
    const down = (event: PointerEvent) => {
      state.current.active = true
      lastX = event.clientX
      lastY = event.clientY
    }
    const move = (event: PointerEvent) => {
      if (!state.current.active) return
      state.current.yaw += (event.clientX - lastX) * 0.006
      state.current.pitch = Math.max(-0.7, Math.min(0.7, state.current.pitch + (event.clientY - lastY) * 0.004))
      lastX = event.clientX
      lastY = event.clientY
    }
    const up = () => {
      state.current.active = false
    }
    el.addEventListener('pointerdown', down)
    window.addEventListener('pointermove', move)
    window.addEventListener('pointerup', up)
    window.addEventListener('pointercancel', up)
    return () => {
      el.removeEventListener('pointerdown', down)
      window.removeEventListener('pointermove', move)
      window.removeEventListener('pointerup', up)
      window.removeEventListener('pointercancel', up)
    }
  }, [element])

  return state
}
