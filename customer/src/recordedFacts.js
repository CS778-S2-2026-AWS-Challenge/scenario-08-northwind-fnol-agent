import { fieldLabel, fieldValueText } from './claimFieldPresentation.js'

// What the "Just noted" card under an assistant reply shows, read straight from
// the Claim form so it never differs from what is stored.
//
// A fact belongs to the claimant message that last stated it: the newest
// claimant message named in the field's sources or assertion history. A
// correction made on the card or in the details panel keeps the fact where it
// is; saying it again in a later message moves it to that message's card.

const CARD_STATUSES = new Set(['proposed', 'confirmed', 'disputed'])
const HIDDEN_FIELDS = new Set(['claimant.client_number'])

function hasValue(field) {
  const { value } = field
  if (value === null || value === undefined || value === '') return false
  return !(Array.isArray(value) && value.length === 0)
}

function lastStatedIn(field, claimantOrder) {
  const refs = [
    ...(field.source_refs || []),
    ...(field.assertions || []).flatMap((assertion) => assertion.source_refs || []),
  ]
  let latest = null
  let latestIndex = -1
  for (const ref of refs) {
    const index = claimantOrder.get(ref)
    if (index !== undefined && index > latestIndex) {
      latest = ref
      latestIndex = index
    }
  }
  return latest
}

function fact(fieldCode, field) {
  return {
    fieldCode,
    field,
    label: fieldLabel(fieldCode),
    value: fieldValueText(field),
    toCheck: field.status !== 'confirmed',
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
    const claimantMessageId = lastStatedIn(field, claimantOrder)
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
