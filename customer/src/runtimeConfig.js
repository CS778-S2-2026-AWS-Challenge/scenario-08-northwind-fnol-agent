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
