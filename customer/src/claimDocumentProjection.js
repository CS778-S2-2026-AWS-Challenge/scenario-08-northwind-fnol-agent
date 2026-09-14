import { formatIdentifierLabel } from './formatters.js'

export const DOCUMENT_STATUS_ORDER = {
  required: 0,
  recommended: 1,
  processing: 2,
  received: 3,
  later: 4,
}

export const DOCUMENT_STATUS_DETAILS = {
  required: { label: 'Required', symbol: '!' },
  recommended: { label: 'Recommended', symbol: '+' },
  processing: { label: 'Processing', symbol: '…' },
  received: { label: 'Received', symbol: '✓' },
  later: { label: 'Can add later', symbol: '↗' },
}

function neededFor(item, purpose) {
  const purposes = Array.isArray(item.needed_for) ? item.needed_for : [item.needed_for]
  return purposes.includes(purpose)
}

export function documentStatus(item) {
  if (item.file_status === 'failed' || item.status === 'invalid') {
    return neededFor(item, 'current_action') ? 'required' : 'recommended'
  }
  if (['uploading', 'uploaded', 'processing'].includes(item.file_status)) return 'processing'
  if (item.file_status === 'ready' && item.status === 'received') return 'received'
  if (neededFor(item, 'current_action')) return 'required'
  if (
    neededFor(item, 'later_action')
    || (item.status === 'pending' && item.file_status === 'not_available')
  ) return 'later'
  return 'recommended'
}

export function documentAttentionCount(items) {
  return items.filter((item) => ['required', 'recommended'].includes(documentStatus(item))).length
}

export function documentReason(item, status) {
  if (item.file_status === 'failed') {
    return 'Northwind could not process this file, so it cannot be used. Upload it again.'
  }
  if (item.status === 'invalid') {
    return 'Northwind cannot use this material because it did not pass validation. Upload a valid replacement.'
  }
  if (item.claimant_note) return item.claimant_note
  if (status === 'required') return 'Needed for the current claim step.'
  if (status === 'recommended') return 'May help Northwind assess this claim.'
  if (status === 'processing') return 'Northwind is checking this file.'
  if (status === 'received') return 'Saved with this claim.'
  return 'Not needed for the current claim step.'
}

export function documentName(item) {
  return item.original_filename || formatIdentifierLabel(item.kind)
}
