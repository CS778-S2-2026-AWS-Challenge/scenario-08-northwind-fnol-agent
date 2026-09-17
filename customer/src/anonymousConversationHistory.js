const ANONYMOUS_SESSION_KEY = 'northwind.anonymousSession'
const HISTORY_KEY_PREFIX = 'northwind.anonymousConversationHistory.v1'
const HISTORY_LIMIT = 25
const CLAIM_ID_PATTERN = /^clm_[A-Za-z0-9_-]+$/

function storageKey() {
  try {
    const anonymousSessionId = globalThis.sessionStorage?.getItem(ANONYMOUS_SESSION_KEY)
    return anonymousSessionId ? `${HISTORY_KEY_PREFIX}.${anonymousSessionId}` : null
  } catch {
    return null
  }
}

function safeTimestamp(value) {
  if (typeof value !== 'string' || Number.isNaN(Date.parse(value))) return null
  return value
}

function safeConversationProjection(claim) {
  if (!claim || !CLAIM_ID_PATTERN.test(claim.claim_id || '')) return null
  const canResume = claim.can_resume ?? claim.customer_next_step?.can_resume
  if (canResume !== true) return null
  const createdAt = safeTimestamp(claim.created_at)
  const updatedAt = safeTimestamp(claim.updated_at) || createdAt
  if (!updatedAt) return null
  return {
    claim_id: claim.claim_id,
    incident_type: typeof claim.incident_type === 'string' ? claim.incident_type : null,
    customer_next_step: {
      summary: 'Continue this conversation.',
      can_resume: true,
    },
    created_at: createdAt || updatedAt,
    updated_at: updatedAt,
    can_resume: true,
  }
}

export function readAnonymousConversationHistory() {
  const key = storageKey()
  if (!key) return []
  try {
    const stored = JSON.parse(globalThis.sessionStorage?.getItem(key) || '[]')
    if (!Array.isArray(stored)) return []
    return stored
      .map(safeConversationProjection)
      .filter(Boolean)
      .slice(0, HISTORY_LIMIT)
  } catch {
    return []
  }
}

export function rememberAnonymousConversation(claim) {
  const key = storageKey()
  const projection = safeConversationProjection(claim)
  if (!key) return []
  if (!projection) {
    const canResume = claim?.can_resume ?? claim?.customer_next_step?.can_resume
    return canResume === false && CLAIM_ID_PATTERN.test(claim?.claim_id || '')
      ? forgetAnonymousConversation(claim.claim_id)
      : readAnonymousConversationHistory()
  }
  const history = [
    projection,
    ...readAnonymousConversationHistory().filter((item) => item.claim_id !== projection.claim_id),
  ].slice(0, HISTORY_LIMIT)
  try {
    globalThis.sessionStorage?.setItem(key, JSON.stringify(history))
  } catch { /* storage may be unavailable in privacy-restricted browsers */ }
  return history
}

export function forgetAnonymousConversation(claimId) {
  const key = storageKey()
  if (!key) return []
  const history = readAnonymousConversationHistory().filter((item) => item.claim_id !== claimId)
  try {
    globalThis.sessionStorage?.setItem(key, JSON.stringify(history))
  } catch { /* storage may be unavailable in privacy-restricted browsers */ }
  return history
}
