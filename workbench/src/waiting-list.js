// Waiting-list items are the open items the claims team settles after collection.
const WAITING_KINDS = new Set(['question', 'contact_request'])

export function waitingListItems(items = []) {
  return items.filter((item) => WAITING_KINDS.has(item.kind))
}

export function openWaitingCount(items = []) {
  return waitingListItems(items).filter((item) => item.state === 'open').length
}
