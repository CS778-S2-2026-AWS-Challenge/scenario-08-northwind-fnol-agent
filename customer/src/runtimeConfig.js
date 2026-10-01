const SAME_ORIGIN_WORKBENCH_PATH = '/workbench/'

export function resolveWorkbenchUrl(configuredUrl = '') {
  const candidate = String(configuredUrl || '').trim()
  if (!candidate) return SAME_ORIGIN_WORKBENCH_PATH

  if (candidate.startsWith('/') && !candidate.startsWith('//')) return candidate

  try {
    const parsed = new URL(candidate)
    return ['http:', 'https:'].includes(parsed.protocol)
      ? parsed.toString()
      : SAME_ORIGIN_WORKBENCH_PATH
  } catch {
    return SAME_ORIGIN_WORKBENCH_PATH
  }
}

export const WORKBENCH_URL = resolveWorkbenchUrl(import.meta.env.VITE_NORTHWIND_WORKBENCH_URL)

// Developer mode shows diagnostics claimants do not need, such as which
// information the assistant reviewed for each reply. Off unless explicitly set.
export function developerModeEnabled() {
  return import.meta.env.VITE_NORTHWIND_DEVELOPER_MODE === 'true'
}
