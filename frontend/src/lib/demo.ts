// Set only in the public demo's own build (never the personal deployment's) — a build-time
// twin of the backend's `demo_mode` setting, since the two are always deployed together but
// live in separate build artifacts. See app/config.py's demo_mode docstring and
// docs/decisions.md for what this turns on and off server-side; this flag only ever changes
// what the UI shows, never what the backend allows — every route it fronts for is enforced
// there regardless of what this says.
export const isDemoMode = import.meta.env.VITE_DEMO_MODE === 'true'
