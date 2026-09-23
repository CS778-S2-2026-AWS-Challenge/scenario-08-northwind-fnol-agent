export function maskPolicyNumber(value = '') {
  const compact = value.replace(/\s/g, '')
  if (!compact) return 'Not provided'
  if (compact.length <= 4) return '••••'
  return `••••${compact.slice(-4)}`
}

function retainedPolicyStatus(resource) {
  if (resource?.error || resource?.stale) return 'Could not refresh'
  if (resource?.loading) return resource?.items?.length ? 'Refreshing…' : 'Loading…'
  return ''
}

export function policyNumberSummary(resource) {
  const policies = resource?.items
  if (resource?.error && !policies?.length) return 'Unavailable'
  if (policies === null) return 'Loading…'
  if (!policies?.length) return 'Not provided'
  const value = policies.length === 1
    ? maskPolicyNumber(policies[0].policy_number)
    : `${policies.length} policy numbers saved`
  const status = retainedPolicyStatus(resource)
  return status ? `${value} · ${status}` : value
}

export function policyDisclosureSummary(resource) {
  const base = resource?.items?.length ? 'View or edit policy number' : 'Add policy number'
  const status = retainedPolicyStatus(resource)
  if (status === 'Could not refresh') return `${base} — refresh failed`
  if (status === 'Refreshing…') return `${base} — refreshing`
  if (status === 'Loading…') return `${base} — loading`
  return base
}
