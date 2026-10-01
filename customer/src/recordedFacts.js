import { fieldLabel, fieldValueText } from './claimFieldPresentation.js'

// What the "Just noted" card under an assistant reply shows, read straight from
// the Claim form so it never differs from what is stored.
//
// A fact belongs to the claimant message behind its current assertion: the one
// whose words set the stored value. A typed "yes", a repeat of the same value or
// a conflicting answer adds sources but does not change the value, so the fact
// stays where it is. A correction made on the card or in the details panel has
// no message source; the fact stays with the message that last stated it.
//
// Only suggested ("proposed") and confirmed facts appear. A fact with two
// conflicting answers is settled through the details panel, which the review
// prompt in the conversation keeps open for it.

const CARD_STATUSES = new Set(['proposed', 'confirmed'])
const HIDDEN_FIELDS = new Set(['claimant.client_number'])

function hasValue(field) {
  const { value } = field
  if (value === null || value === undefined || value === '') return false
  return !(Array.isArray(value) && value.length === 0)
}

function claimantMessageIn(refs, claimantOrder) {
  let latest = null
  let latestIndex = -1
  for (const ref of refs || []) {
    const index = claimantOrder.get(ref)
    if (index !== undefined && index > latestIndex) {
      latest = ref
      latestIndex = index
    }
  }
  return latest
}

function statedIn(field, claimantOrder) {
  const assertions = field.assertions || []
  if (assertions.length === 0) return claimantMessageIn(field.source_refs, claimantOrder)
  const currentIndex = field.current_assertion_id
    ? assertions.findIndex((item) => item.assertion_id === field.current_assertion_id)
    : -1
  const start = currentIndex >= 0 ? currentIndex : assertions.length - 1
  for (let index = start; index >= 0; index -= 1) {
    const messageId = claimantMessageIn(assertions[index].source_refs, claimantOrder)
    if (messageId) return messageId
  }
  return null
}

function fact(fieldCode, field) {
  return {
    fieldCode,
    field,
    label: fieldLabel(fieldCode),
    value: fieldValueText(field),
    toCheck: field.status === 'proposed',
  }
}

// One card per claimant message, under the latest reply to it (a retried turn
// can answer the same message twice). Map order follows the conversation.
export function factCardsByAgentMessage(messages, form) {
  const claimantOrder = new Map()
  const replyByClaimantMessage = new Map()
  ;(messages || []).forEach((message, index) => {
    if (message.actor === 'claimant') claimantOrder.set(message.message_id, index)
    if (message.actor === 'agent' && message.in_reply_to) {
      replyByClaimantMessage.set(message.in_reply_to, message.message_id)
    }
  })

  const factsByClaimantMessage = new Map()
  for (const [fieldCode, field] of Object.entries(form || {})) {
    if (HIDDEN_FIELDS.has(fieldCode) || !field || !CARD_STATUSES.has(field.status) || !hasValue(field)) {
      continue
    }
    const claimantMessageId = statedIn(field, claimantOrder)
    if (!claimantMessageId) continue
    const facts = factsByClaimantMessage.get(claimantMessageId) || []
    facts.push(fact(fieldCode, field))
    factsByClaimantMessage.set(claimantMessageId, facts)
  }

  const cards = new Map()
  for (const message of messages || []) {
    if (message.actor !== 'agent' || replyByClaimantMessage.get(message.in_reply_to) !== message.message_id) {
      continue
    }
    const facts = factsByClaimantMessage.get(message.in_reply_to)
    if (facts) cards.set(message.message_id, facts)
  }
  return cards
}

// Required details already given (checked or not) out of those this step needs.
export function notedProgress(dynamicForm) {
  const requirements = dynamicForm?.requirements
  const total = requirements?.current_action_total || 0
  if (!total) return null
  const missing = (requirements.missing_required_now || []).length
  const byState = requirements.by_state || {}
  return {
    noted: Math.min(total, Math.max(0, total - missing)),
    total,
    toCheck: (byState.proposed || []).length + (byState.disputed || []).length,
  }
}

export function progressLabel(progress) {
  const noted = `${progress.noted} of ${progress.total} noted`
  return progress.toCheck > 0 ? `${noted} · ${progress.toCheck} to check` : noted
}

// Readable label for a registered enum value, e.g. other_party_accepts.
export function choiceLabel(value) {
  const text = String(value).replaceAll('_', ' ')
  return text.charAt(0).toUpperCase() + text.slice(1)
}
