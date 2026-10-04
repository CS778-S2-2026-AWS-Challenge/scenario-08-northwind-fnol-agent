// The one status place in the conversation title bar. Exactly one thing shows,
// the most relevant: a person's involvement, then the lodged stage, then how
// much of the report is noted.

export function caseStatus({ claim, assistanceState, isUrgentSupport, progress, handlerAssigned }) {
  if (!claim) return null
  if (isUrgentSupport) return { tone: 'urgent', text: 'Urgent support requested' }
  if (assistanceState && assistanceState.key !== 'completed') {
    return { tone: 'staff', text: assistanceState.title, detail: assistanceState.description }
  }
  const lodged = claim.external_claim?.creation_status === 'created'
  if (lodged) {
    const stage = claim.claim_decision
      ? 'Decision made'
      : handlerAssigned ? 'With your claims handler' : 'Waiting for a claims handler'
    return { tone: 'lodged', text: `Lodged · ${stage}` }
  }
  if (claim.external_claim?.creation_status === 'pending') return { tone: 'neutral', text: 'Submitting…' }
  if (claim.external_claim?.creation_status === 'failed') return { tone: 'urgent', text: 'Submission needs attention' }
  if (progress) return { tone: 'neutral', text: `Noted ${progress.noted}/${progress.total}`, opensPanel: true }
  return { tone: 'neutral', text: 'Your claim', opensPanel: true }
}
