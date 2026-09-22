export function maskPolicyNumber(value = '') {
  const compact = value.replace(/\s/g, '')
  if (!compact) return 'Not provided'
  return `••••${compact.slice(-4)}`
}

export function policyNumberSummary(resource) {
  const policies = resource?.items
  if (resource?.error && !policies?.length) return 'Unavailable'
  if (policies === null) return 'Loading…'
  if (!policies?.length) return 'Not provided'
  if (policies.length === 1) return maskPolicyNumber(policies[0].policy_number)
  return `${policies.length} policy numbers saved`
}
