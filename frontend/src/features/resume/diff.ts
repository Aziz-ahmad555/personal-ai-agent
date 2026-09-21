export type DiffKind = 'same' | 'added' | 'removed'

export interface DiffSegment {
  text: string
  kind: DiffKind
}

/**
 * Word-level diff of two texts, split into the two views a side-by-side review needs:
 * `before` (unchanged + removed words) and `after` (unchanged + added words).
 *
 * A longest-common-subsequence over whitespace-separated words — resume bullets are short, so
 * the O(n·m) table is trivial, and word granularity reads far better than character diffs.
 */
export function diffWords(before: string, after: string): { before: DiffSegment[]; after: DiffSegment[] } {
  const a = before.split(/\s+/).filter(Boolean)
  const b = after.split(/\s+/).filter(Boolean)

  // lcs[i][j] = length of the LCS of a[i:] and b[j:]
  const lcs: number[][] = Array.from({ length: a.length + 1 }, () => new Array<number>(b.length + 1).fill(0))
  for (let i = a.length - 1; i >= 0; i--) {
    for (let j = b.length - 1; j >= 0; j--) {
      lcs[i][j] = a[i] === b[j] ? lcs[i + 1][j + 1] + 1 : Math.max(lcs[i + 1][j], lcs[i][j + 1])
    }
  }

  const beforeWords: DiffSegment[] = []
  const afterWords: DiffSegment[] = []
  let i = 0
  let j = 0
  while (i < a.length && j < b.length) {
    if (a[i] === b[j]) {
      beforeWords.push({ text: a[i], kind: 'same' })
      afterWords.push({ text: b[j], kind: 'same' })
      i++
      j++
    } else if (lcs[i + 1][j] >= lcs[i][j + 1]) {
      beforeWords.push({ text: a[i++], kind: 'removed' })
    } else {
      afterWords.push({ text: b[j++], kind: 'added' })
    }
  }
  while (i < a.length) beforeWords.push({ text: a[i++], kind: 'removed' })
  while (j < b.length) afterWords.push({ text: b[j++], kind: 'added' })

  return { before: mergeRuns(beforeWords), after: mergeRuns(afterWords) }
}

/** Joins consecutive words of the same kind, so highlighting spans whole phrases. */
function mergeRuns(words: DiffSegment[]): DiffSegment[] {
  const runs: DiffSegment[] = []
  for (const word of words) {
    const last = runs[runs.length - 1]
    if (last && last.kind === word.kind) last.text += ` ${word.text}`
    else runs.push({ ...word })
  }
  return runs
}
