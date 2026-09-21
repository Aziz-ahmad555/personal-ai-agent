export interface GraphNode {
  position: [number, number, number]
  verified: boolean
}

export interface EvidenceGraph {
  nodes: GraphNode[]
  edges: [number, number][]
}

/** Small seeded PRNG so the layout is identical on every load (and testable). */
function mulberry32(seed: number): () => number {
  let a = seed >>> 0
  return () => {
    a = (a + 0x6d2b79f5) >>> 0
    let t = a
    t = Math.imul(t ^ (t >>> 15), t | 1)
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61)
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296
  }
}

const distance = (a: GraphNode, b: GraphNode) =>
  Math.hypot(
    a.position[0] - b.position[0],
    a.position[1] - b.position[1],
    a.position[2] - b.position[2]
  )

/**
 * A network of evidence nodes on a jittered sphere. Most are verified; the rest are unconfirmed.
 * Each node links to its nearest neighbours, so the lines read as sources supporting one another.
 */
export function buildGraph(count: number, seed = 7, verifiedShare = 0.7, links = 2): EvidenceGraph {
  const random = mulberry32(seed)
  const nodes: GraphNode[] = []
  const golden = Math.PI * (3 - Math.sqrt(5))
  for (let i = 0; i < count; i++) {
    const y = 1 - (i / Math.max(1, count - 1)) * 2
    const ring = Math.sqrt(Math.max(0, 1 - y * y))
    const theta = golden * i
    const radius = 1.6 + random() * 0.7
    nodes.push({
      position: [Math.cos(theta) * ring * radius, y * radius, Math.sin(theta) * ring * radius],
      verified: random() < verifiedShare,
    })
  }

  const seen = new Set<string>()
  const edges: [number, number][] = []
  nodes.forEach((node, i) => {
    const nearest = nodes
      .map((other, j) => ({ j, d: i === j ? Infinity : distance(node, other) }))
      .sort((a, b) => a.d - b.d)
      .slice(0, links)
    for (const { j } of nearest) {
      const key = i < j ? `${i}-${j}` : `${j}-${i}`
      if (seen.has(key)) continue
      seen.add(key)
      edges.push([Math.min(i, j), Math.max(i, j)])
    }
  })
  return { nodes, edges }
}
