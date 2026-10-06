import { fieldLabel, fieldValueText } from './claimFieldPresentation.js'

// What the captured-information card under an assistant reply shows. The server stores,
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

function isRepeatedDerivedLoss(fieldCode, form) {
  if (fieldCode !== 'loss.description') return false
  const loss = form?.['loss.description']
  const vehicleDamage = form?.['vehicle.damage_description']
  if (!hasValue(loss) || !hasValue(vehicleDamage)) return false
  return fieldValueText(loss).trim() === fieldValueText(vehicleDamage).trim()
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
      if (placed.has(item.field_code)
        || !field
        || !CARD_STATUSES.has(field.status)
        || !hasValue(field)
        || isRepeatedDerivedLoss(item.field_code, form)) {
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

export function fieldDraftValue(value, input) {
  if (input?.value_type === 'boolean') return value === true ? 'true' : value === false ? 'false' : ''
  if (input?.value_type === 'enum') return typeof value === 'string' ? value : ''
  if (input?.value_type === 'text_list') return Array.isArray(value) ? value.join(', ') : ''
  return value === null || value === undefined ? '' : String(value)
}

const REGISTERED_NUMBER_PATTERN = /^(?:nz)?\$?\s*(\d+(?:\.\d{1,2})?)$/i

export function parseRegisteredNumber(value) {
  if (typeof value === 'boolean' || value === null || value === undefined) return null
  const normalized = String(value).trim().replaceAll(',', '')
  const match = REGISTERED_NUMBER_PATTERN.exec(normalized)
  if (!match) return null
  const number = Number(match[1])
  return Number.isFinite(number) && number >= 0 ? number : null
}

export function fieldInputValue(draft, input) {
  if (input?.value_type === 'boolean') return draft === 'true'
  if (input?.value_type === 'number') return parseRegisteredNumber(draft)
  if (input?.value_type === 'text_list') {
    return String(draft).split(',').map((item) => item.trim()).filter(Boolean)
  }
  return String(draft).trim()
}

export function fieldInputChoices(input) {
  if (input?.value_type === 'boolean') return [['true', 'Yes'], ['false', 'No']]
  if (input?.value_type === 'enum') {
    const values = input.allowed_values || []
    return values.length > 0 ? values.map((value) => [value, choiceLabel(value)]) : null
  }
  return null
}

export function displayValue(fact, input) {
  if (fact.fieldCode === 'claim.product_family' && fact.field.value === 'motor') {
    return 'Motor vehicle accident'
  }
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
