import { fieldLabel, fieldValueText } from './claimFieldPresentation.js'

// What the "Just noted" card under an assistant reply shows. The server stores,
// with each Agent message, which facts that turn recorded
// (content.turn_record.recorded_facts); the card lists those fields with their
// current stored value, so a later correction shows the corrected value.
//
// A field recorded again by a later turn appears only under the latest one.
// Only suggested ("proposed") and confirmed facts appear; a fact with two
// conflicting answers is settled in the case panel.

const CARD_STATUSES = new Set(['proposed', 'confirmed'])

function hasValue(field) {
  const { value } = field
  if (value === null || value === undefined || value === '') return false
  return !(Array.isArray(value) && value.length === 0)
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

export function turnRecord(message) {
  const record = message?.content?.turn_record
  return record && typeof record === 'object' ? record : null
}

export function factCardsByAgentMessage(messages, form) {
  const cards = new Map()
  const placed = new Set()
  const agentMessages = (messages || []).filter((message) => message.actor === 'agent')
  for (let index = agentMessages.length - 1; index >= 0; index -= 1) {
    const message = agentMessages[index]
    const facts = []
    for (const item of turnRecord(message)?.recorded_facts || []) {
      const field = form?.[item.field_code]
      if (placed.has(item.field_code) || !field || !CARD_STATUSES.has(field.status) || !hasValue(field)) {
        continue
      }
      placed.add(item.field_code)
      facts.push(fact(item.field_code, field))
    }
    if (facts.length > 0) cards.set(message.message_id, facts)
  }
  return cards
}

// What the model read each file to be, by evidence id (latest reading wins).
export function fileReadings(messages) {
  const readings = new Map()
  for (const message of messages || []) {
    if (message.actor !== 'agent') continue
    for (const read of turnRecord(message)?.file_reads || []) {
      if (read?.evidence_id && read?.kind) readings.set(read.evidence_id, read.kind)
    }
  }
  return readings
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

export function displayValue(fact, input) {
  if (input?.value_type === 'enum' && typeof fact.field.value === 'string') {
    return choiceLabel(fact.field.value)
  }
  return fact.value
}

// Structured values (a time range, an address object) are corrected in the
// details panel, which edits their parts; a chip only edits plain values.
export function isEditable(fact) {
  const { value } = fact.field
  return Array.isArray(value) || value === null || typeof value !== 'object'
}
