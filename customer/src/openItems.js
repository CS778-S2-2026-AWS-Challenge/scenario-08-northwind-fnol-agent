import { documentTaskTitle } from './claimDocumentProjection.js'

// What is still owed on a Claim and by whom, as the server projects it
// (claim.open_items). Nothing here decides state; it only words it.
//
//   claimant     a document the claimant will send, or said they do not have
//   northwind    a question the claims team will answer
//   third_party  a document Northwind gets from a service (police, assessor)

export function openItemTitle(item) {
  if (item.kind === 'question') return item.subject
  return documentTaskTitle({ kind: item.subject })
}

export function openItemStatusText(item) {
  if (item.kind === 'question') {
    return item.state === 'done' ? 'Answered by Northwind' : 'Waiting for Northwind to answer'
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
    { key: 'northwind', title: 'Northwind is answering', items: all.filter((item) => item.owner === 'northwind') },
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
  if (item.kind === 'question') {
    return item.state === 'done'
      ? `Northwind answered: ${item.answer}`
      : `Passed to the claims team: ${item.subject}`
  }
  if (item.state === 'done') return `Received: ${openItemTitle(item)}`
  if (item.state === 'not_available') return `Noted that you do not have: ${openItemTitle(item)}`
  if (item.owner === 'third_party') return `Northwind will get: ${openItemTitle(item)}`
  return `Added to your to-do: ${openItemTitle(item)}`
}
