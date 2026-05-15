// Workspace accent color system. Each workspace slug maps to a single
// hex value that tints the chat input border, send button, message
// badges, thread title, sidebar active state, etc. Kept here rather
// than buried inside any one component so we can change a workspace's
// color in one spot.
//
// The slate fallback (#94a3b8) doubles as the value for the "general"
// terminal workspace AND for any unknown slug that arrives at runtime
// — e.g. if a workspace is added to config.py but this map isn't
// updated yet. That degrades to neutral grey instead of crashing.

export type WorkspaceSlug =
  | 'chief-of-staff'
  | 'admin'
  | 'institute'
  | 'health'
  | 'engineering'
  | 'parker'
  | 'general'

export const WORKSPACE_ACCENT: Record<WorkspaceSlug, string> = {
  'chief-of-staff': '#00f0ff', // Architect — cyan
  admin: '#8b5cf6',            // Admin Prime — violet
  institute: '#ff3366',        // Institute Prime — hot pink
  health: '#22c55e',           // Med-Bay — green
  engineering: '#eab308',      // The Rig — neon yellow
  parker: '#f97316',           // Parker.exe — orange
  general: '#94a3b8',          // Terminal — slate
}

const NEUTRAL_FALLBACK = '#94a3b8'

/** Returns the accent hex for a workspace slug, falling back to slate
 *  for unknown/missing values so callers can use this unconditionally. */
export function getWorkspaceAccent(slug: string | null | undefined): string {
  if (!slug) return NEUTRAL_FALLBACK
  return (WORKSPACE_ACCENT as Record<string, string>)[slug] ?? NEUTRAL_FALLBACK
}

/** Returns the accent color with an alpha channel applied. `alpha` is
 *  0–1. Used for tinted backgrounds where we want the accent at low
 *  opacity (e.g. active workspace row background). */
export function getWorkspaceAccentAlpha(
  slug: string | null | undefined,
  alpha: number,
): string {
  const hex = getWorkspaceAccent(slug)
  const r = parseInt(hex.slice(1, 3), 16)
  const g = parseInt(hex.slice(3, 5), 16)
  const b = parseInt(hex.slice(5, 7), 16)
  const a = Math.max(0, Math.min(1, alpha))
  return `rgba(${r}, ${g}, ${b}, ${a})`
}
