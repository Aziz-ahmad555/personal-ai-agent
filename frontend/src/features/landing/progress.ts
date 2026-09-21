export function clamp01(value: number): number {
  return Math.min(1, Math.max(0, value))
}

export function smoothstep(edge0: number, edge1: number, value: number): number {
  const t = clamp01((value - edge0) / (edge1 - edge0))
  return t * t * (3 - 2 * t)
}

interface Box {
  top: number
  height: number
}

/**
 * How far a section has travelled through the viewport: 0 as its top edge enters at the bottom,
 * 0.5 when it is centred, 1 as its bottom edge leaves at the top.
 */
export function sectionProgress(box: Box, viewportHeight: number): number {
  return clamp01((viewportHeight - box.top) / (viewportHeight + box.height))
}

/**
 * Progress through a tall section measured from an anchor line in the viewport (a fraction of its
 * height). With N equal blocks, block k is under the anchor when progress is in [k/N, (k+1)/N).
 */
export function anchoredProgress(box: Box, viewportHeight: number, anchor = 0.55): number {
  return clamp01((viewportHeight * anchor - box.top) / box.height)
}

export function tierIndex(progress: number, tiers = 3): number {
  return Math.min(tiers - 1, Math.floor(clamp01(progress) * tiers))
}

/**
 * Needle position along the gauge arc (0 = far left, 1 = far right). It rests at the centre of the
 * tier whose copy is in view and moves to the next tier's centre near the end of each block.
 */
export function needleFraction(progress: number, tiers = 3): number {
  const centre = (index: number) => (index + 0.5) / tiers
  const scaled = clamp01(progress) * tiers
  const index = Math.min(tiers - 1, Math.floor(scaled))
  if (index === tiers - 1) return centre(index)
  const blend = smoothstep(0.6, 1, scaled - index)
  return centre(index) + (centre(index + 1) - centre(index)) * blend
}

/** A needle drawn pointing +y: far left is +90deg, far right is -90deg. */
export const needleRotation = (fraction: number) => Math.PI / 2 - fraction * Math.PI
