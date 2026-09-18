let claimantToken = import.meta.env.VITE_NORTHWIND_CLAIMANT_TOKEN || ''
try {
  claimantToken = claimantToken || globalThis.localStorage?.getItem('northwind.claimantToken') || ''
} catch { /* storage may be unavailable in privacy-restricted browsers */ }
function createAnonymousSessionId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID()
  const bytes = globalThis.crypto?.getRandomValues?.(new Uint8Array(16))
  if (bytes) {
    bytes[6] = (bytes[6] & 0x0f) | 0x40
    bytes[8] = (bytes[8] & 0x3f) | 0x80
    const hex = Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')
    return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20)}`
  }
  return '00000000-0000-4000-8000-' + `${Date.now()}${Math.random()}`.replace(/\D/g, '').padEnd(12, '0').slice(-12)
}

let anonymousSession = sessionStorage.getItem('northwind.anonymousSession') || createAnonymousSessionId()
sessionStorage.setItem('northwind.anonymousSession', anonymousSession)

export function setClaimantAccessToken(token) {
  claimantToken = token || ''
  try {
    if (claimantToken) globalThis.localStorage?.setItem('northwind.claimantToken', claimantToken)
    else globalThis.localStorage?.removeItem('northwind.claimantToken')
  } catch { /* storage may be unavailable in privacy-restricted browsers */ }
}

export function hasClaimantAccessToken() {
  return Boolean(claimantToken)
}

export class ApiRequestError extends Error {
  constructor(message, { code, status, retryable = false, currentRevision = null } = {}) {
    super(message)
    this.name = 'ApiRequestError'
    this.code = code
    this.status = status
    this.retryable = retryable
    this.currentRevision = currentRevision
  }
}

export function requestId(prefix) {
  const id = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`
  return `${prefix}-${id}`
}

async function apiRequest(path, options = {}) {
  let response
  try {
    response = await fetch(path, {
      ...options,
      headers: {
        ...(claimantToken ? { Authorization: `Bearer ${claimantToken}` } : {}),
        ...(!claimantToken && anonymousSession ? { 'X-Northwind-Anonymous-Session': anonymousSession } : {}),
        'Content-Type': 'application/json',
        ...options.headers,
      },
    })
  } catch (error) {
    if (error?.name === 'AbortError') throw error
    throw new ApiRequestError(
      'We could not reach the claim service. Check your connection and try again.',
      { code: 'NETWORK_ERROR', retryable: true },
    )
  }

  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const error = payload?.error
    throw new ApiRequestError(
      error?.message || 'The claim service could not complete this request.',
      {
        code: error?.code || 'HTTP_ERROR',
        status: response.status,
        retryable: error?.retryable,
        currentRevision: error?.current_revision,
      },
    )
  }
  return payload
}

function claimantHeaders(headers = {}) {
  return {
    ...(claimantToken ? { Authorization: `Bearer ${claimantToken}` } : {}),
    ...(!claimantToken && anonymousSession ? { 'X-Northwind-Anonymous-Session': anonymousSession } : {}),
    ...headers,
  }
}

function streamError(message, options) {
  return new ApiRequestError(message, options)
}

async function cancelReaderAfterFailure(reader, signal) {
  if (signal?.aborted) return
  try { await reader.cancel() } catch { /* preserve the original stream failure */ }
}

async function readRealtimeEventStream(response, signal, onEvent, onOpen) {
  if (!response.body) {
    throw streamError(
      'This browser could not keep the claim connected for live updates.',
      { code: 'STREAM_UNAVAILABLE', retryable: true },
    )
  }
  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    if (onOpen) await onOpen()
    while (!signal?.aborted) {
      const { done, value } = await reader.read()
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
      buffer = buffer.replaceAll('\r\n', '\n')
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        const frame = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const lines = frame.split('\n')
        const event = lines.find((line) => line.startsWith('event:'))?.slice(6).trim()
        const cursor = lines.find((line) => line.startsWith('id:'))?.slice(3).trim() || null
        const data = lines.filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trimStart()).join('\n')
        if (event && data) {
          try {
            await onEvent({ event, cursor, data: JSON.parse(data) })
          } catch (error) {
            if (error instanceof SyntaxError) {
              throw streamError(
                'A live claim update could not be read. We will reconnect.',
                { code: 'INVALID_STREAM_EVENT', retryable: true },
              )
            }
            throw error
          }
        }
        boundary = buffer.indexOf('\n\n')
      }
      if (done) return
    }
  } catch (error) {
    await cancelReaderAfterFailure(reader, signal)
    throw error
  } finally {
    reader.releaseLock()
  }
}

export async function streamRealtimeEvents({
  cursor,
  signal,
  onOpen,
  onEvent,
  onCursor,
}) {
  const params = new URLSearchParams()
  if (cursor) params.set('cursor', cursor)
  const query = params.size ? `?${params}` : ''
  let response
  try {
    response = await fetch(`/api/v1/realtime/events${query}`, {
      headers: claimantHeaders({ Accept: 'text/event-stream' }),
      signal,
    })
  } catch (error) {
    if (error?.name === 'AbortError') return
    throw streamError(
      'Live claim updates are temporarily disconnected. We will keep trying.',
      { code: 'NETWORK_ERROR', retryable: true },
    )
  }
  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw streamError(
      payload?.error?.message || 'Live claim updates could not be started.',
      {
        code: payload?.error?.code || 'HTTP_ERROR',
        status: response.status,
        retryable: payload?.error?.retryable,
        currentRevision: payload?.error?.current_revision,
      },
    )
  }
  await readRealtimeEventStream(response, signal, async ({ event, cursor: eventCursor, data }) => {
    if (!['resources.changed', 'resync_required', 'agent.turn.progress'].includes(event)) return
    await onEvent({ type: event, cursor: eventCursor, data })
    if (eventCursor) onCursor?.(eventCursor)
  }, onOpen)
}

export async function streamClaimUpdates({
  claimId,
  sessionId,
  afterRevision,
  cursor,
  signal,
  onEvent,
  onCursor,
}) {
  const params = new URLSearchParams({ after_revision: String(afterRevision) })
  if (cursor) params.set('cursor', cursor)
  let response
  try {
    response = await fetch(
      `/api/v1/claims/${claimId}/sessions/${sessionId}/events?${params}`,
      {
        headers: claimantHeaders({ Accept: 'text/event-stream' }),
        signal,
      },
    )
  } catch (error) {
    if (error?.name === 'AbortError') return
    throw streamError(
      'Live claim updates are temporarily disconnected. We will keep trying.',
      { code: 'NETWORK_ERROR', retryable: true },
    )
  }

  if (!response.ok) {
    const payload = await response.json().catch(() => null)
    throw streamError(
      payload?.error?.message || 'Live claim updates could not be started.',
      {
        code: payload?.error?.code || 'HTTP_ERROR',
        status: response.status,
        retryable: payload?.error?.retryable,
        currentRevision: payload?.error?.current_revision,
      },
    )
  }
  if (!response.body) {
    throw streamError(
      'This browser could not keep the claim connected for live updates.',
      { code: 'STREAM_UNAVAILABLE', retryable: true },
    )
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  try {
    while (!signal?.aborted) {
      const { done, value } = await reader.read()
      buffer += decoder.decode(value || new Uint8Array(), { stream: !done })
      buffer = buffer.replaceAll('\r\n', '\n')
      let boundary = buffer.indexOf('\n\n')
      while (boundary >= 0) {
        const frame = buffer.slice(0, boundary)
        buffer = buffer.slice(boundary + 2)
        const lines = frame.split('\n')
        const event = lines.find((line) => line.startsWith('event:'))?.slice(6).trim()
        const cursor = lines.find((line) => line.startsWith('id:'))?.slice(3).trim() || null
        const data = lines
          .filter((line) => line.startsWith('data:'))
          .map((line) => line.slice(5).trimStart())
          .join('\n')
        if (['claim.updated', 'agent.turn.progress'].includes(event) && data) {
          try {
            await onEvent({ ...JSON.parse(data), event_type: event, cursor })
            if (cursor && !/^\d+$/.test(cursor)) onCursor?.(cursor)
          } catch (error) {
            if (error instanceof SyntaxError) {
              throw streamError(
                'A live claim update could not be read. We will reconnect.',
                { code: 'INVALID_STREAM_EVENT', retryable: true },
              )
            }
            throw error
          }
        }
        boundary = buffer.indexOf('\n\n')
      }
      if (done) return
    }
  } catch (error) {
    await cancelReaderAfterFailure(reader, signal)
    throw error
  } finally {
    reader.releaseLock()
  }
}

export function promoteAnonymousClaim(claimId) {
  return apiRequest(`/api/v1/claims/${claimId}/promote`, {
    method: 'POST',
    headers: { 'X-Northwind-Anonymous-Session': anonymousSession },
  })
}

export function loginClaimant({ email, password }) {
  return apiRequest('/api/v1/auth/sessions', {
    method: 'POST',
    headers: { Authorization: '' },
    body: JSON.stringify({ email, password }),
  })
}

export function registerClaimant({ email, password, display_name }) {
  return apiRequest('/api/v1/auth/accounts', {
    method: 'POST',
    headers: { Authorization: '' },
    body: JSON.stringify({ email, password, display_name }),
  })
}

export function getAuthenticatedAccount() {
  return apiRequest('/api/v1/account')
}

export function updateAccountProfile(profile) {
  return apiRequest('/api/v1/account/profile', {
    method: 'PATCH',
    body: JSON.stringify(profile),
  })
}

export function updateAccountPreferences(preferences) {
  return apiRequest('/api/v1/account/preferences', {
    method: 'PATCH',
    body: JSON.stringify(preferences),
  })
}

export async function logoutClaimant() {
  try {
    await apiRequest('/api/v1/auth/session', { method: 'DELETE' })
  } finally {
    setClaimantAccessToken(null)
  }
}

export function createClaim({ idempotencyKey = requestId('claim'), incidentType = null, modelProfileId = null } = {}) {
  return apiRequest('/api/v1/claims', {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({
      channel: 'web_agent',
      locale: 'en-NZ',
      incident_type: incidentType,
      ...(modelProfileId ? { model_profile_id: modelProfileId } : {}),
    }),
  })
}

export function getRuntimeCapabilities() {
  return apiRequest('/api/v1/claims/capabilities', {
    headers: { 'X-Northwind-Anonymous-Session': anonymousSession },
  })
}

export function updateClaimFields({ claimId, revision, updates }) {
  return apiRequest(`/api/v1/claims/${claimId}/form`, {
    method: 'PATCH',
    headers: { 'If-Match': String(revision) },
    body: JSON.stringify({ updates }),
  })
}

export function requestEvidenceUpload({ claimId, revision, file, kind = 'other_document', evidenceId = null, idempotencyKey = requestId('evidence-upload'), signal }) {
  return apiRequest(`/api/v1/claims/${claimId}/evidence/uploads`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey, 'If-Match': String(revision) },
    body: JSON.stringify({
      ...(evidenceId ? { evidence_id: evidenceId } : {}),
      kind,
      original_filename: file.name,
      media_type: file.type,
      size_bytes: file.size,
    }),
    signal,
  })
}

export function completeEvidenceUpload({ claimId, evidenceId, revision, checksum, idempotencyKey = requestId('evidence-complete'), signal }) {
  return apiRequest(`/api/v1/claims/${claimId}/evidence/${evidenceId}/complete`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey, 'If-Match': String(revision) },
    body: JSON.stringify({ upload_checksum: checksum }),
    signal,
  })
}

export function uploadEvidenceContent({ upload, file, signal }) {
  return apiRequest(upload.url, {
    method: upload.method,
    headers: upload.headers,
    body: file,
    signal,
  })
}

export function registerPendingEvidence({ claimId, revision, kind, note, idempotencyKey = requestId('evidence-pending') }) {
  return apiRequest(`/api/v1/claims/${claimId}/evidence`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey, 'If-Match': String(revision) },
    body: JSON.stringify({ kind, status: 'incomplete', related_fields: [], needed_for: ['later_action'], claimant_note: note }),
  })
}

export function getClaimEvidence(claimId, { signal } = {}) {
  return apiRequest(`/api/v1/claims/${claimId}/evidence`, { signal })
}

export function listEvidenceHistory({ cursor, limit = 25, signal } = {}) {
  const params = new URLSearchParams({ limit: String(limit) })
  if (cursor) params.set('cursor', cursor)
  return apiRequest(`/api/v1/evidence?${params}`, { signal })
}

export function applyEvidenceHistoryAction({
  claimId,
  evidenceId,
  action,
  sourceClaimId,
  revision,
  proposalRef,
  confirmationRef,
  idempotencyKey = requestId(`evidence-${action}`),
  signal,
}) {
  return apiRequest(`/api/v1/claims/${claimId}/evidence/${evidenceId}/${action}`, {
    method: 'POST',
    headers: {
      'Idempotency-Key': idempotencyKey,
      'If-Match': String(revision),
    },
    body: JSON.stringify({ source_claim_id: sourceClaimId, proposal_ref: proposalRef, confirmation_ref: confirmationRef }),
    signal,
  })
}

export function getClaim(claimId) {
  return apiRequest(`/api/v1/claims/${claimId}`)
}

export function listClaims({ cursor, limit = 25, signal } = {}) {
  const params = new URLSearchParams({ limit: String(limit) })
  if (cursor) params.set('cursor', cursor)
  return apiRequest(`/api/v1/claims?${params}`, { signal })
}

export function resumeClaimSession({
  claimId,
  idempotencyKey = requestId('resume'),
  modelProfileId = null,
}) {
  return apiRequest(`/api/v1/claims/${claimId}/sessions`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({ intent: 'resume', ...(modelProfileId ? { model_profile_id: modelProfileId } : {}) }),
  })
}

export function startClaimSession({ claimId, intent = 'new', idempotencyKey = requestId('session'), modelProfileId = null }) {
  return apiRequest(`/api/v1/claims/${claimId}/sessions`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({ intent, ...(modelProfileId ? { model_profile_id: modelProfileId } : {}) }),
  })
}

export function getClaimMessages(claimId, sessionId) {
  return apiRequest(`/api/v1/claims/${claimId}/sessions/${sessionId}/messages?limit=100`)
}

export function createExternalClaim({
  claimId,
  revision,
  idempotencyKey = requestId('claim-creation'),
}) {
  return apiRequest(`/api/v1/claims/${claimId}/creation`, {
    method: 'POST',
    headers: {
      'Idempotency-Key': idempotencyKey,
      'If-Match': String(revision),
    },
  })
}

export function grantAssessorConsent({
  claimId,
  revision,
  idempotencyKey = requestId('assessor-consent'),
}) {
  return apiRequest(`/api/v1/claims/${claimId}/assessor-routing/consent`, {
    method: 'POST',
    headers: {
      'Idempotency-Key': idempotencyKey,
      'If-Match': String(revision),
    },
    body: JSON.stringify({ consent: true }),
  })
}

export function requestAssessorRouting({
  claimId,
  revision,
  idempotencyKey = requestId('assessor-routing'),
}) {
  return apiRequest(`/api/v1/claims/${claimId}/assessor-routing`, {
    method: 'POST',
    headers: {
      'Idempotency-Key': idempotencyKey,
      'If-Match': String(revision),
    },
  })
}

export function decideExternalServiceOffer({
  claimId,
  offerId,
  revision,
  decision,
  idempotencyKey = requestId(`external-offer-${decision}`),
}) {
  return apiRequest(`/api/v1/claims/${claimId}/external-service-offers/${offerId}/decision`, {
    method: 'POST',
    headers: {
      'Idempotency-Key': idempotencyKey,
      'If-Match': String(revision),
    },
    body: JSON.stringify({ decision }),
  })
}

export function submitClaimMessage({
  claimId,
  sessionId,
  revision,
  text,
  modelProfileId = null,
  idempotencyKey = requestId('turn'),
  clientMessageId = requestId('message'),
}) {
  return apiRequest(`/api/v1/claims/${claimId}/sessions/${sessionId}/messages`, {
    method: 'POST',
    headers: {
      'Idempotency-Key': idempotencyKey,
      'If-Match': String(revision),
    },
    body: JSON.stringify({
      client_message_id: clientMessageId,
      content: { type: 'text', text },
      evidence_refs: [],
      ...(modelProfileId ? { model_profile_id: modelProfileId } : {}),
    }),
  })
}

export function updateClaimField({ claimId, revision, fieldCode, value, status, reason }) {
  return apiRequest(`/api/v1/claims/${claimId}/form`, {
    method: 'PATCH',
    headers: { 'If-Match': String(revision) },
    body: JSON.stringify({
      updates: [
        {
          field_code: fieldCode,
          value,
          status,
          ...(reason ? { correction_reason: reason } : {}),
        },
      ],
    }),
  })
}

export function confirmClaimFields({
  claimId,
  revision,
  fieldCodes,
  idempotencyKey = requestId('confirmation'),
}) {
  return apiRequest(`/api/v1/claims/${claimId}/form/confirmations`, {
    method: 'POST',
    headers: {
      'Idempotency-Key': idempotencyKey,
      'If-Match': String(revision),
    },
    body: JSON.stringify({ field_codes: fieldCodes }),
  })
}

export function requestHumanSupport({
  claimId,
  revision,
  reason = 'I want to speak to a person.',
  preferredChannel = null,
  idempotencyKey = requestId('support'),
}) {
  return apiRequest(`/api/v1/claims/${claimId}/support-requests`, {
    method: 'POST',
    headers: {
      'Idempotency-Key': idempotencyKey,
      'If-Match': String(revision),
    },
    body: JSON.stringify({
      reason,
      support_need: 'human_requested',
      ...(preferredChannel ? { preferred_channel: preferredChannel } : {}),
    }),
  })
}
