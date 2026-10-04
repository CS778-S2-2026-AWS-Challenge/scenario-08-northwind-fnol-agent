import { claimHeading } from './claimHeading.js'
import { claimantOwedItems, openItemsBarText } from './openItems.js'

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
  return {
    claimId: latest.claim_id,
    title: claimHeading(latest),
    detail: openItemsBarText(latest.open_items)
      || latest.customer_next_step?.summary
      || 'Pick up where you left off.',
  }
}
