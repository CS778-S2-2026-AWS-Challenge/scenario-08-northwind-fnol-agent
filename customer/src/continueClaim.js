import { claimStatusLabel, claimTitle } from './formatters.js'
import { claimantOwedItems, openItemsBarText } from './openItems.js'

function savedTime(value) {
  const saved = value ? new Date(value) : null
  if (!saved || Number.isNaN(saved.getTime())) return null
  return saved.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
}

function savedClaimStatus(report) {
  if (report.workflow_state === 'collecting') return 'Draft'
  return report.workflow_state ? claimStatusLabel(report.workflow_state) : 'In progress'
}

// The one claim a returning claimant is offered under the landing composer:
// the most recently updated claim that still owes something or can resume.
export function continueClaimCard(reports = []) {
  const candidates = reports.filter((report) => (
    report?.claim_id
    && (claimantOwedItems(report.open_items).length > 0 || report.can_resume)
  ))
  if (candidates.length === 0) return null
  const latest = [...candidates].sort((left, right) => (
    String(right.updated_at || '').localeCompare(String(left.updated_at || ''))
  ))[0]
  const savedAt = savedTime(latest.updated_at)
  return {
    claimId: latest.claim_id,
    title: claimTitle(latest),
    statusLabel: savedClaimStatus(latest),
    savedLabel: savedAt ? `Saved ${savedAt}` : 'Saved',
    detail: latest.customer_next_step?.summary
      || openItemsBarText(latest.open_items)
      || 'Pick up where you left off.',
  }
}
