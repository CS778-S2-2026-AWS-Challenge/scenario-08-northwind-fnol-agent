import { documentTaskTitle } from './claimDocumentProjection.js'

// What is still owed on a Claim and by whom, as the server projects it
// (claim.open_items). Nothing here decides state; it only words it.
//
//   claimant     a document the claimant will send, or said they do not have
//   northwind    a waiting-list item: a question, or a request to be contacted,
//                that the claims team handles once the report is submitted
//   third_party  a document Northwind gets from a service (police, assessor)

const WAITING_KINDS = new Set(['question', 'contact_request'])

export function isWaitingListItem(item) {
  return WAITING_KINDS.has(item?.kind)
}

export function openItemTitle(item) {
  if (item.kind === 'contact_request') return item.subject || 'Someone from Northwind to contact you'
  if (item.kind === 'question') return item.subject
  return documentTaskTitle({ kind: item.subject })
}

export function openItemStatusText(item) {
  if (item.kind === 'contact_request') {
    if (item.state === 'done') return 'Northwind contacted you'
    if (item.state === 'declined') return 'Northwind replied'
    return 'The claims team will contact you after you submit'
  }
  if (item.kind === 'question') {
    if (item.state === 'done') return 'Answered by Northwind'
    if (item.state === 'declined') return 'Northwind replied'
    return 'The claims team will answer after you submit'
  }
  if (item.state === 'done') return 'Received'
  if (item.state === 'not_available') return 'You said you do not have this'
  if (item.owner === 'third_party') return 'Northwind is getting this for you'
  return 'You said you will send this later'
}

// Items the claimant can act on right now: documents they said they will send.
export function claimantOwedItems(items) {
  return (items || []).filter((item) => (
    item.kind === 'document' && item.owner === 'claimant' && item.state === 'open'
  ))
}

// Items Northwind or a third party still owes the claimant.
export function waitingItems(items) {
  return (items || []).filter((item) => (
    item.state === 'open' && (item.owner === 'northwind' || item.owner === 'third_party')
  ))
}

export function openItemGroups(items) {
  const all = items || []
  return [
    { key: 'claimant', title: 'For you to send', items: all.filter((item) => item.owner === 'claimant') },
    { key: 'northwind', title: 'For the claims team', items: all.filter((item) => item.owner === 'northwind') },
    { key: 'third_party', title: 'Northwind is getting', items: all.filter((item) => item.owner === 'third_party') },
  ].filter((group) => group.items.length > 0)
}

// The one-line strip above the composer while something is outstanding.
export function openItemsBarText(items) {
  const owed = claimantOwedItems(items)
  const waiting = waitingItems(items)
  if (owed.length === 0 && waiting.length === 0) return null
  const parts = []
  if (owed.length === 1) parts.push(`Still to send: ${openItemTitle(owed[0])}`)
  else if (owed.length > 1) parts.push(`Still to send: ${owed.length} documents`)
  if (waiting.length === 1) parts.push(`Waiting on Northwind: ${openItemTitle(waiting[0])}`)
  else if (waiting.length > 1) parts.push(`Waiting on Northwind: ${waiting.length} items`)
  return parts.join(' · ')
}

// Receipts under the reply that opened each item, keyed by agent message id.
export function receiptsByMessage(items) {
  const receipts = new Map()
  for (const item of items || []) {
    if (!item.opened_in_message_id) continue
    const list = receipts.get(item.opened_in_message_id) || []
    list.push(item)
    receipts.set(item.opened_in_message_id, list)
  }
  return receipts
}

export function receiptText(item) {
  if (isWaitingListItem(item)) {
    if (item.state === 'done' && item.kind === 'question') return `Northwind answered: ${item.answer}`
    if (item.state === 'done') return `Northwind contacted you: ${openItemTitle(item)}`
    if (item.state === 'declined') return `Northwind replied: ${item.answer}`
    return `For the claims team: ${openItemTitle(item)}`
  }
  if (item.state === 'done') return `Received: ${openItemTitle(item)}`
  if (item.state === 'not_available') return `Noted that you do not have: ${openItemTitle(item)}`
  if (item.owner === 'third_party') return `Northwind will get: ${openItemTitle(item)}`
  return `To do: ${openItemTitle(item)}`
}

// The receipt as a chip: a mark, short text, and whether it is the claimant's to do.
export function receiptChip(item) {
  const owed = item.kind === 'document' && item.owner === 'claimant' && item.state === 'open'
  const settled = item.state !== 'open'
  return {
    mark: settled ? '✓' : isWaitingListItem(item) ? '→' : '+',
    text: receiptText(item),
    owed,
    settled,
  }
}
