const CLAIMANT_TOKEN = import.meta.env.VITE_NORTHWIND_CLAIMANT_TOKEN || 'synthetic-claimant'

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
        Authorization: `Bearer ${CLAIMANT_TOKEN}`,
        'Content-Type': 'application/json',
        ...options.headers,
      },
    })
  } catch {
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

export function createClaim({ idempotencyKey = requestId('claim') } = {}) {
  return apiRequest('/api/v1/claims', {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({ channel: 'web_agent', locale: 'en-NZ' }),
  })
}

export function getClaim(claimId) {
  return apiRequest(`/api/v1/claims/${claimId}`)
}

export function listClaims() {
  return apiRequest('/api/v1/claims?limit=25')
}

export function resumeClaimSession({
  claimId,
  idempotencyKey = requestId('resume'),
}) {
  return apiRequest(`/api/v1/claims/${claimId}/sessions`, {
    method: 'POST',
    headers: { 'Idempotency-Key': idempotencyKey },
    body: JSON.stringify({ intent: 'resume' }),
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

export function submitClaimMessage({
  claimId,
  sessionId,
  revision,
  text,
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
