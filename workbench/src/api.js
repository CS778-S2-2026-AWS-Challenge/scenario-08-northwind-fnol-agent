const SESSION_KEY = 'northwind.workbench.session'
const STAFF_MESSAGE_OPERATIONS_KEY = 'northwind.workbench.staff-message-operations.v2'
let volatileStaffMessageOperations = {}

export class ApiError extends Error {
  constructor(message, { status = 0, code = 'NETWORK_ERROR', details = [] } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
  }
}

export function readStoredSession() {
  try {
    const session = JSON.parse(localStorage.getItem(SESSION_KEY) || 'null')
    if (!session?.access_token || !session?.expires_at) return null
    if (new Date(session.expires_at).getTime() <= Date.now()) {
      localStorage.removeItem(SESSION_KEY)
      return null
    }
    return session
  } catch {
    localStorage.removeItem(SESSION_KEY)
    return null
  }
}

export function storeSession(session) {
  localStorage.setItem(SESSION_KEY, JSON.stringify(session))
}

export function clearStoredSession() {
  localStorage.removeItem(SESSION_KEY)
}

async function request(path, { token, headers, ...options } = {}) {
  let response
  try {
    response = await fetch(path, {
      ...options,
      headers: {
        Accept: 'application/json',
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
        ...headers,
      },
    })
  } catch {
    throw new ApiError('The Workbench service could not be reached. Try again shortly.')
  }

  if (response.status === 204) return null
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    throw new ApiError(payload?.error?.message || 'The request could not be completed.', {
      status: response.status,
      code: payload?.error?.code,
      details: payload?.error?.details,
    })
  }
  return payload
}

export const workbenchApi = {
  login(email, password) {
    return request('/api/v1/staff/auth/sessions', {
      method: 'POST',
      body: JSON.stringify({ email, password }),
    })
  },
  session(token) {
    return request('/api/v1/staff/auth/session', { token })
  },
  profile(token) {
    return request('/api/v1/staff/me', { token })
  },
  logout(token) {
    return request('/api/v1/staff/auth/session', { method: 'DELETE', token })
  },
  claims(token, filters = {}) {
    const params = new URLSearchParams()
    for (const [key, value] of Object.entries(filters)) {
      if (value !== undefined && value !== null && value !== '') params.set(key, value)
    }
    const query = params.size ? `?${params}` : ''
    return request(`/api/v1/workbench/claims${query}`, { token })
  },
  claimFilterMetadata(token) {
    return request('/api/v1/workbench/claims/filter-metadata', { token })
  },
  conversations(token, cursor) {
    const params = new URLSearchParams({ limit: '50' })
    if (cursor) params.set('cursor', cursor)
    return request(`/api/v1/workbench/conversations?${params}`, { token })
  },
  staffAgentSessions(token) {
    return request('/api/v1/workbench/agent/sessions', { token })
  },
  createStaffAgentSession(token, title = 'New Staff Agent session') {
    return request('/api/v1/workbench/agent/sessions', {
      method: 'POST',
      token,
      body: JSON.stringify({ title }),
    })
  },
  staffAgentMessages(token, sessionId) {
    return request(
      `/api/v1/workbench/agent/sessions/${encodeURIComponent(sessionId)}/messages`,
      { token },
    )
  },
  sendStaffAgentMessage(token, sessionId, content, claimIds) {
    return request(
      `/api/v1/workbench/agent/sessions/${encodeURIComponent(sessionId)}/messages`,
      {
        method: 'POST',
        token,
        body: JSON.stringify({
          client_message_id: crypto.randomUUID(),
          content,
          claim_ids: claimIds,
        }),
      },
    )
  },
  claim(token, claimId) {
    return request(`/api/v1/workbench/claims/${encodeURIComponent(claimId)}`, { token })
  },
  fields(token, claimId, cursor) {
    return pagedClaimResource(token, claimId, 'fields', cursor)
  },
  sessions(token, claimId, cursor) {
    return pagedClaimResource(token, claimId, 'sessions', cursor)
  },
  collaborationRequests(token, claimId, cursor) {
    return pagedClaimResource(token, claimId, 'collaboration-requests', cursor)
  },
  messages(token, claimId, sessionId, cursor) {
    const path = `${encodeURIComponent(claimId)}/sessions/${encodeURIComponent(sessionId)}/messages`
    return pagedWorkbenchResource(token, path, cursor, 50)
  },
  evidence(token, claimId, cursor) {
    return pagedClaimResource(token, claimId, 'evidence', cursor)
  },
  retrievals(token, claimId, cursor) {
    return pagedClaimResource(token, claimId, 'retrievals', cursor)
  },
  signals(token, claimId, cursor) {
    return pagedClaimResource(token, claimId, 'signals', cursor)
  },
  handoffs(token, claimId, cursor) {
    return pagedClaimResource(token, claimId, 'handoffs', cursor)
  },
  workItems(token, claimId, cursor) {
    return pagedClaimResource(token, claimId, 'work-items', cursor)
  },
  customerUpdates(token, claimId, cursor) {
    return pagedClaimResource(token, claimId, 'customer-updates', cursor)
  },
  externalRequests(token, claimId, cursor) {
    return pagedClaimResource(token, claimId, 'external-requests', cursor)
  },
  events(token, claimId, cursor) {
    return pagedClaimResource(token, claimId, 'events', cursor)
  },
  acceptHandoff(token, claimId, handoffId, revision) {
    return request(
      `/api/v1/workbench/claims/${encodeURIComponent(claimId)}/handoffs/${encodeURIComponent(handoffId)}/accept`,
      {
        method: 'POST',
        token,
        headers: {
          'Idempotency-Key': crypto.randomUUID(),
          'If-Match': String(revision),
        },
        body: JSON.stringify({}),
      },
    )
  },
  requestCowork(token, claimId, revision, payload) {
    return ownershipRequest(token, claimId, 'cowork-requests', revision, payload)
  },
  requestTransfer(token, claimId, revision, payload) {
    return ownershipRequest(token, claimId, 'transfer-requests', revision, payload)
  },
  decideCollaboration(token, claimId, requestId, revision, payload) {
    return request(
      `/api/v1/workbench/claims/${encodeURIComponent(claimId)}/collaboration-requests/${encodeURIComponent(requestId)}`,
      {
        method: 'PATCH',
        token,
        headers: {
          'Idempotency-Key': crypto.randomUUID(),
          'If-Match': String(revision),
        },
        body: JSON.stringify(payload),
      },
    )
  },
  requeue(token, claimId, revision, payload) {
    return ownershipRequest(token, claimId, 'requeue', revision, payload)
  },
  resolveHandoff(token, claimId, handoffId, revision, payload) {
    return request(
      `/api/v1/workbench/claims/${encodeURIComponent(claimId)}/handoffs/${encodeURIComponent(handoffId)}/resolve`,
      {
        method: 'POST',
        token,
        headers: {
          'Idempotency-Key': crypto.randomUUID(),
          'If-Match': String(revision),
        },
        body: JSON.stringify(payload),
      },
    )
  },
  decideSignal(token, claimId, signalId, revision, payload) {
    return request(
      `/api/v1/workbench/claims/${encodeURIComponent(claimId)}/signals/${encodeURIComponent(signalId)}/decisions`,
      {
        method: 'POST',
        token,
        headers: {
          'Idempotency-Key': crypto.randomUUID(),
          'If-Match': String(revision),
        },
        body: JSON.stringify(payload),
      },
    )
  },
  createStaffAction(token, claimId, revision, payload) {
    return request(`/api/v1/workbench/claims/${encodeURIComponent(claimId)}/staff-actions`, {
      method: 'POST',
      token,
      headers: {
        'Idempotency-Key': crypto.randomUUID(),
        'If-Match': String(revision),
      },
      body: JSON.stringify(payload),
    })
  },
  updateStaffAction(token, claimId, actionId, revision, payload) {
    return request(
      `/api/v1/workbench/claims/${encodeURIComponent(claimId)}/staff-actions/${encodeURIComponent(actionId)}`,
      {
        method: 'PATCH',
        token,
        headers: {
          'Idempotency-Key': crypto.randomUUID(),
          'If-Match': String(revision),
        },
        body: JSON.stringify(payload),
      },
    )
  },
  evidenceContent(token, claimId, evidenceId) {
    return request(
      `/api/v1/workbench/claims/${encodeURIComponent(claimId)}/evidence/${encodeURIComponent(evidenceId)}/content-data`,
      { token },
    )
  },
  async sendMessage(token, claimId, operation, revision) {
    const { message, sessionId } = operation
    const pendingOperation = pendingStaffMessageOperation(claimId, sessionId, message)
    try {
      const response = await request(`/api/v1/workbench/claims/${encodeURIComponent(claimId)}/messages`, {
        method: 'POST',
        token,
        headers: {
          'Idempotency-Key': pendingOperation.key,
          'If-Match': String(revision),
        },
        body: JSON.stringify({ content: { type: 'text', text: message } }),
      })
      clearPendingStaffMessageOperation(claimId)
      return response
    } catch (error) {
      if (!ambiguousStaffMessageFailure(error)) {
        clearPendingStaffMessageOperation(claimId)
      }
      throw error
    }
  },
}

function ownershipRequest(token, claimId, resource, revision, payload) {
  return request(`/api/v1/workbench/claims/${encodeURIComponent(claimId)}/${resource}`, {
    method: 'POST',
    token,
    headers: {
      'Idempotency-Key': crypto.randomUUID(),
      'If-Match': String(revision),
    },
    body: JSON.stringify(payload),
  })
}

function pagedClaimResource(token, claimId, resource, cursor) {
  return pagedWorkbenchResource(
    token,
    `${encodeURIComponent(claimId)}/${resource}`,
    cursor,
    25,
  )
}

function pagedWorkbenchResource(token, path, cursor, limit) {
  const params = new URLSearchParams({ limit: String(limit) })
  if (cursor) params.set('cursor', cursor)
  return request(`/api/v1/workbench/claims/${path}?${params}`, { token })
}

function pendingStaffMessageOperation(claimId, sessionId, message) {
  const operations = readStaffMessageOperations()
  const existing = operations[claimId]
  if (existing) {
    if (existing.sessionId !== sessionId || existing.message !== message) {
      throw new ApiError(
        'The previous claimant message has an unknown delivery outcome. Retry the unchanged message in the same conversation before starting another send.',
        { code: 'MESSAGE_DELIVERY_UNKNOWN' },
      )
    }
    return existing
  }

  const operation = {
    sessionId,
    message,
    key: crypto.randomUUID(),
  }
  operations[claimId] = operation
  writeStaffMessageOperations(operations)
  return operation
}

function clearPendingStaffMessageOperation(claimId) {
  const operations = readStaffMessageOperations()
  if (!(claimId in operations)) return
  delete operations[claimId]
  writeStaffMessageOperations(operations)
}

function readStaffMessageOperations() {
  try {
    const operations = JSON.parse(sessionStorage.getItem(STAFF_MESSAGE_OPERATIONS_KEY) || '{}')
    if (operations && typeof operations === 'object' && !Array.isArray(operations)) {
      volatileStaffMessageOperations = { ...operations }
      return operations
    }
  } catch {
    // Fall through to the in-memory copy when browser storage is unavailable or malformed.
  }
  return { ...volatileStaffMessageOperations }
}

function writeStaffMessageOperations(operations) {
  volatileStaffMessageOperations = { ...operations }
  try {
    sessionStorage.setItem(STAFF_MESSAGE_OPERATIONS_KEY, JSON.stringify(operations))
  } catch {
    // The in-memory copy still preserves retry identity for the current page lifetime.
  }
}

function ambiguousStaffMessageFailure(error) {
  return error?.code === 'NETWORK_ERROR' || error?.status === 0 || error?.status === 429 || error?.status >= 500
}
