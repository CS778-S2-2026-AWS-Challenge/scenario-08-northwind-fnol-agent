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

export const DOCUMENT_UPLOAD_CONSTRAINTS = {
  allowedMediaTypes: ['image/jpeg', 'image/png', 'application/pdf'],
  accept: 'image/jpeg,image/png,application/pdf',
  maxSizeBytes: 10_485_760,
  summary: 'JPG, PNG or PDF · up to 10 MB each',
}

const PHOTO_KINDS = new Set(['incident_image', 'incident_photo', 'item_photo', 'photo'])

const DOCUMENT_TITLES = {
  agency_incident_record: 'Incident record',
  assessment_report: 'Assessment report',
  document: 'Supporting document',
  incident_image: 'Photos of the damage',
  incident_photo: 'Photos of the damage',
  incident_report: 'Incident report',
  item_photo: 'Photos of the damage',
  other_document: 'Supporting document',
  photo: 'Photos of the damage',
  police_report: 'Police report',
  proof_of_ownership: 'Proof of ownership',
  receipt: 'Receipts or proof of purchase',
  repair_quote: 'Repair quote',
}

const DOCUMENT_DESCRIPTIONS = {
  agency_incident_record: 'This record can help Northwind confirm what happened and assess your claim.',
  assessment_report: 'An assessment report can help Northwind understand the damage and next steps.',
  incident_image: 'Clear photos help Northwind understand the damage and assess your claim faster.',
  incident_photo: 'Clear photos help Northwind understand the damage and assess your claim faster.',
  incident_report: 'An incident report can help Northwind confirm the details of what happened.',
  item_photo: 'Clear photos help Northwind understand the damage and assess your claim faster.',
  photo: 'Clear photos help Northwind understand the damage and assess your claim faster.',
  police_report: 'A police report can help Northwind confirm the incident details when it becomes available.',
  proof_of_ownership: 'A receipt or other proof can help Northwind confirm that the item belongs to you.',
  receipt: 'Receipts can help Northwind confirm the item and its purchase details.',
  repair_quote: 'A repair quote can help Northwind understand the likely work and cost involved.',
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

export function documentIsProvided(item) {
  return item.file_status === 'ready' && item.status === 'received'
}

export function documentProvidedCount(items) {
  return items.filter(documentIsProvided).length
}

export function documentRequirement(item) {
  return neededFor(item, 'current_action') ? 'required' : 'recommended'
}

export function documentTaskTitle(item) {
  return DOCUMENT_TITLES[item.kind] || formatIdentifierLabel(item.kind)
}

export function documentTaskDescription(item) {
  return DOCUMENT_DESCRIPTIONS[item.kind] || 'This document may help Northwind understand and assess your claim.'
}

export function documentIsPhoto(item) {
  return PHOTO_KINDS.has(item.kind)
}

export function documentUploadLabel(item, replace = false) {
  if (replace) return documentIsPhoto(item) ? 'Replace photos' : 'Replace file'
  return documentIsPhoto(item) ? 'Upload photos' : 'Upload file'
}

export function documentMediaTypeLabel(mediaType) {
  if (mediaType === 'image/jpeg') return 'JPG'
  if (mediaType === 'image/png') return 'PNG'
  if (mediaType === 'application/pdf') return 'PDF'
  return 'File'
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
