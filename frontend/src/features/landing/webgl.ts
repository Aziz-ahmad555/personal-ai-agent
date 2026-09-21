/**
 * True if this browser can create a WebGL context. Any failure counts as "no".
 * `?webgl=off` forces the static fallback, so that path can be checked on a machine that has WebGL.
 */
export function hasWebGL(doc: Document = document, search: string = window.location.search): boolean {
  if (new URLSearchParams(search).get('webgl') === 'off') return false
  try {
    const canvas = doc.createElement('canvas')
    return Boolean(canvas.getContext('webgl2') ?? canvas.getContext('webgl'))
  } catch {
    return false
  }
}
