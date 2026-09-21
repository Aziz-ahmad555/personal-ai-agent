import { describe, expect, it, vi } from 'vitest'
import { buildGraph } from '@/features/landing/graph'
import {
  anchoredProgress,
  needleFraction,
  needleRotation,
  sectionProgress,
  smoothstep,
  tierIndex,
} from '@/features/landing/progress'
import { hasWebGL } from '@/features/landing/webgl'

describe('sectionProgress', () => {
  const viewport = 800

  it('is 0 as the section enters, 0.5 when centred, 1 as it leaves', () => {
    expect(sectionProgress({ top: 800, height: 400 }, viewport)).toBe(0)
    expect(sectionProgress({ top: 200, height: 400 }, viewport)).toBe(0.5)
    expect(sectionProgress({ top: -400, height: 400 }, viewport)).toBe(1)
  })

  it('stays clamped when the section is far off screen', () => {
    expect(sectionProgress({ top: 5000, height: 400 }, viewport)).toBe(0)
    expect(sectionProgress({ top: -5000, height: 400 }, viewport)).toBe(1)
  })
})

describe('anchoredProgress and tierIndex', () => {
  it('puts each of three equal blocks under the anchor in turn', () => {
    // anchor at 55% of 800 = 440px; blocks are 300px tall
    const at = (top: number) => tierIndex(anchoredProgress({ top, height: 900 }, 800))
    expect(at(440 - 10)).toBe(0)
    expect(at(440 - 400)).toBe(1)
    expect(at(440 - 700)).toBe(2)
  })

  it('never returns a tier outside the range', () => {
    expect(tierIndex(-1)).toBe(0)
    expect(tierIndex(1)).toBe(2)
    expect(tierIndex(5)).toBe(2)
  })
})

describe('needleFraction', () => {
  it('rests at the centre of each tier while its copy is in view', () => {
    expect(needleFraction(0.1)).toBeCloseTo(1 / 6, 5)
    expect(needleFraction(0.45)).toBeCloseTo(0.5, 5)
    expect(needleFraction(0.9)).toBeCloseTo(5 / 6, 5)
  })

  it('moves toward the next tier near the end of a block and never goes backwards', () => {
    let previous = -1
    for (let p = 0; p <= 1; p += 0.01) {
      const value = needleFraction(p)
      expect(value).toBeGreaterThanOrEqual(previous)
      previous = value
    }
    expect(needleFraction(0.3)).toBeGreaterThan(1 / 6)
  })

  it('maps far left and far right to a quarter turn either side of vertical', () => {
    expect(needleRotation(0)).toBeCloseTo(Math.PI / 2)
    expect(needleRotation(0.5)).toBeCloseTo(0)
    expect(needleRotation(1)).toBeCloseTo(-Math.PI / 2)
  })

  it('smoothstep is 0 below, 1 above and monotonic between', () => {
    expect(smoothstep(0.2, 0.8, 0)).toBe(0)
    expect(smoothstep(0.2, 0.8, 1)).toBe(1)
    expect(smoothstep(0.2, 0.8, 0.5)).toBeCloseTo(0.5)
  })
})

describe('buildGraph', () => {
  it('is identical on every call so the hero looks the same each load', () => {
    expect(buildGraph(56)).toEqual(buildGraph(56))
  })

  it('makes the requested number of nodes, mostly verified but not all', () => {
    const { nodes } = buildGraph(56)
    const verified = nodes.filter((node) => node.verified).length

    expect(nodes).toHaveLength(56)
    expect(verified).toBeGreaterThan(56 * 0.5)
    expect(verified).toBeLessThan(56)
  })

  it('links nodes with valid, unique, non-self edges', () => {
    const { nodes, edges } = buildGraph(40)
    const keys = new Set(edges.map(([a, b]) => `${a}-${b}`))

    expect(edges.length).toBeGreaterThan(nodes.length / 2)
    expect(keys.size).toBe(edges.length)
    for (const [a, b] of edges) {
      expect(a).toBeLessThan(b)
      expect(b).toBeLessThan(nodes.length)
    }
  })

  it('stays modest for phones', () => {
    expect(buildGraph(56).edges.length).toBeLessThan(120)
  })
})

describe('hasWebGL', () => {
  it('is false when the browser cannot make a context (jsdom has none)', () => {
    vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(null)
    expect(hasWebGL(document, '')).toBe(false)
  })

  it('is true when a context can be created', () => {
    const doc = { createElement: () => ({ getContext: () => ({}) }) } as unknown as Document
    expect(hasWebGL(doc, '')).toBe(true)
  })

  it('is false if creating the canvas throws', () => {
    const doc = {
      createElement: () => {
        throw new Error('blocked')
      },
    } as unknown as Document
    expect(hasWebGL(doc, '')).toBe(false)
  })

  it('can be forced off with ?webgl=off', () => {
    const doc = { createElement: () => ({ getContext: () => ({}) }) } as unknown as Document
    expect(hasWebGL(doc, '?webgl=off')).toBe(false)
  })
})
