// Claimant-facing name for the current conversation. Internal Claim ids
// (clm_...) are never shown: before Northwind issues a claim number the
// conversation is named after its claim type and start time.

const CLAIM_TYPE_NAMES = {
  motor: 'Motor claim',
  home: 'Home claim',
  contents: 'Contents claim',
}

function startedTime(value) {
  const started = value ? new Date(value) : null
  if (!started || Number.isNaN(started.getTime())) return null
  return started.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
}

export function claimHeading(claim) {
  const claimNumber = claim?.external_claim?.claim_number
  if (claimNumber) return claimNumber
  const typeName = CLAIM_TYPE_NAMES[claim?.incident_type]
  if (!typeName) return 'New claim'
  const time = startedTime(claim?.created_at)
  return time ? `${typeName} · started ${time}` : typeName
}

// Secondary line for a saved conversation in the history list.
export function claimStartedLabel(claim) {
  const time = startedTime(claim?.created_at)
  return time ? `Started ${time}` : 'In progress'
}
