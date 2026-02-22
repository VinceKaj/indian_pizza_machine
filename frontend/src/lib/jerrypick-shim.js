/**
 * Minimal shim for "jerrypick" (used by react-kapsule).
 * Only exports omit; pluck not needed by react-force-graph-2d.
 */
export function omit(obj, ...keys) {
  const keySet = new Set(keys.flat())
  return Object.fromEntries(
    Object.entries(obj).filter(([key]) => !keySet.has(key))
  )
}
