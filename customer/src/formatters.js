export function formatDateTime(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Date unavailable'
  return new Intl.DateTimeFormat('en-NZ', {
    dateStyle: 'medium',
    timeStyle: 'short',
    timeZone: 'Pacific/Auckland',
  }).format(date)
}

export function formatIdentifierLabel(value) {
  if (!value) return 'Evidence item'
  return value
    .split('_')
    .filter(Boolean)
    .map((part) => `${part[0].toUpperCase()}${part.slice(1)}`)
    .join(' ')
}

const CLAIM_TYPE_LABELS = {
  motor: 'Motor claim',
  home: 'Home claim',
  contents: 'Contents claim',
}

export function claimTitle(claim) {
  return CLAIM_TYPE_LABELS[claim.incident_type]
    || (claim.incident_type ? `${formatIdentifierLabel(claim.incident_type)} claim` : 'Claim in progress')
}

export function claimStatusLabel(status) {
  // formatIdentifierLabel names a missing value 'Evidence item'; a Claim status never falls back
  // to that, and never to an internal workflow state.
  return status ? formatIdentifierLabel(status) : 'Status unavailable'
}

const RESPONSIBLE_PARTY_LABELS = {
  claimant: 'You',
  claims_professional: 'Claims professional',
  external_party: 'External service provider',
  system: 'System',
}

export function responsiblePartyLabel(responsibleParty) {
  return RESPONSIBLE_PARTY_LABELS[responsibleParty] || 'Not available'
}

export function sortClaimsByLatestUpdate(claims) {
  return [...claims].sort((left, right) => {
    const timeDifference = new Date(right.updated_at).getTime() - new Date(left.updated_at).getTime()
    return timeDifference || right.claim_id.localeCompare(left.claim_id)
  })
}
