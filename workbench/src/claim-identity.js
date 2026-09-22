import { words } from './format.js'

export function claimIdentity(claim = {}) {
  const claimantName = cleanText(claim.claimant?.display_name)
  const incidentSummary = cleanText(claim.incident?.summary)
  const incidentFamily = cleanText(claim.incident?.family)
  const claimId = cleanText(claim.claim_id)
  const reference = cleanText(claim.display_reference) || claimId
  const typeLabel = incidentFamily ? `${words(incidentFamily)} claim` : 'Claim type not confirmed'
  const conciseIncidentTitle = conciseTitle(incidentSummary)
  const title = claimantName || incidentSummary || typeLabel
  const cardTitle = claimantName || conciseIncidentTitle || typeLabel
  const tabLabel = claimantName || conciseIncidentTitle || typeLabel

  return {
    cardTitle,
    claimantName,
    claimId,
    incidentSummary,
    reference,
    referenceLabel: reference || 'Reference pending',
    tabLabel,
    title,
    typeLabel,
  }
}

function conciseTitle(summary) {
  if (!summary) return null
  return summary.split(';', 1)[0].trim() || summary
}

function cleanText(value) {
  return typeof value === 'string' && value.trim() ? value.trim() : null
}
