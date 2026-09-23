// Red-team Track A, item 7: a structural regression guard, not a behavior test. A red-team
// pass confirmed no `dangerouslySetInnerHTML` (or direct `.innerHTML =` DOM manipulation)
// exists anywhere in this frontend — meaning every place untrusted stored text (a job posting
// description, a calendar event summary, an email subject/snippet) gets rendered goes through
// React's default escaping. This turns that one-time confirmation into something that fails
// the suite if a future change quietly reintroduces raw HTML rendering.
//
// Uses Vite's import.meta.glob (not Node's fs/path) since this project's tsconfig is
// browser-only and doesn't carry Node type definitions.
import { describe, expect, it } from 'vitest'

const sourceFiles = import.meta.glob('./**/*.{ts,tsx}', { query: '?raw', import: 'default' })

const DANGEROUS_PATTERNS = [/dangerouslySetInnerHTML/, /\.innerHTML\s*=/]

describe('no raw HTML rendering', () => {
  it('never uses dangerouslySetInnerHTML or direct innerHTML assignment', async () => {
    const offenders: string[] = []
    for (const [path, loader] of Object.entries(sourceFiles)) {
      if (path.endsWith('security.test.ts')) continue
      const text = (await loader()) as string
      for (const pattern of DANGEROUS_PATTERNS) {
        if (pattern.test(text)) {
          offenders.push(`${path}: ${pattern}`)
        }
      }
    }
    expect(offenders).toEqual([])
  })
})
