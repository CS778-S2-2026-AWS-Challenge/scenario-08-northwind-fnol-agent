const SESSION_KEY = 'northwind.workbench.session'
const retryableMutationKeys = new Map()
const STAFF_MESSAGE_OPERATIONS_KEY = 'northwind.workbench.staff-message-operations.v2'
let volatileStaffMessageOperations = {}

export class ApiError extends Error {
  constructor(message, {
    status = 0,
    code = 'NETWORK_ERROR',
    details = [],
    requestId = null,
    retryable = false,
    currentRevision = null,
  } = {}) {
    super(message)
    this.name = 'ApiError'
    this.status = status
    this.code = code
    this.details = details
    this.requestId = requestId
    this.retryable = retryable
    this.currentRevision = currentRevision
  }
}

export function readStoredSession() {
  try {
    const session = JSON.parse(localStorage.getItem(SESSION_KEY) || 'null')
    if (!session?.access_token || !session?.expires_at) {
      clearStoredSession()
      return null
    }
    if (new Date(session.expires_at).getTime() <= Date.now()) {
      clearStoredSession()
      return null
    }
    return session
  } catch {
    clearStoredSession()
    return null
  }
}

export function storeSession(session) {
  const existing = readStoredSession()
  if (existing?.access_token !== session.access_token) {
    retryableMutationKeys.clear()
    clearStaffMessageOperations()
  }
  localStorage.setItem(SESSION_KEY, JSON.stringify(session))
}

export function clearStoredSession() {
  retryableMutationKeys.clear()
  clearStaffMessageOperations()
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
    throw new ApiError('The Workbench service could not be reached.', { retryable: true })
  }

  if (response.status === 204) return null
  const payload = await response.json().catch(() => null)
  if (!response.ok) {
    const error = payload?.error || {}
    throw new ApiError(error.message || 'The request could not be completed.', {
      status: response.status,
      code: error.code,
      details: error.details,
      requestId: error.request_id,
      retryable: error.retryable,
      currentRevision: error.current_revision,
    })
  }
  return payload
}

async function mutationRequest(path, { headers = {}, ...options }) {
  const fingerprint = JSON.stringify([
    options.method,
    path,
    headers['If-Match'] || null,
    options.body || null,
  ])
  const suppliedKey = headers['Idempotency-Key']
  const idempotencyKey = suppliedKey || retryableMutationKeys.get(fingerprint) || crypto.randomUUID()
  retryableMutationKeys.set(fingerprint, idempotencyKey)
  try {
    const response = await request(path, {
      ...options,
      headers: { ...headers, 'Idempotency-Key': idempotencyKey },
    })
    retryableMutationKeys.delete(fingerprint)
    return response
  } catch (error) {
    if (!(error.retryable || error.status === 0 || error.status >= 500)) {
      retryableMutationKeys.delete(fingerprint)
    }
    throw error
  }
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
  staffAgentCapabilities(token) {
    return request('/api/v1/workbench/agent/capabilities', { token })
  },
  createStaffAgentSession(token, title = 'New Staff Agent session', modelProfileId) {
    return request('/api/v1/workbench/agent/sessions', {
      method: 'POST',
      token,
      body: JSON.stringify({ title, ...(modelProfileId ? { model_profile_id: modelProfileId } : {}) }),
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
  sessionsForTarget(token, claimId, requestedSessionId) {
    return claimSessionsForTarget(token, claimId, requestedSessionId)
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
    return mutationRequest(
      `/api/v1/workbench/claims/${encodeURIComponent(claimId)}/handoffs/${encodeURIComponent(handoffId)}/accept`,
      {
        method: 'POST',
        token,
        headers: {
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
    return mutationRequest(
      `/api/v1/workbench/claims/${encodeURIComponent(claimId)}/collaboration-requests/${encodeURIComponent(requestId)}`,
      {
        method: 'PATCH',
        token,
        headers: {
          'If-Match': String(revision),
        },
        body: JSON.stringify(payload),
      },
    )
  },
  requeue(token, claimId, revision, payload) {
    return ownershipRequest(token, claimId, 'requeue', revision, payload)
  },
  reopenClaim(token, claimId, revision, payload, idempotencyKey = crypto.randomUUID()) {
    return mutationRequest(`/api/v1/workbench/claims/${encodeURIComponent(claimId)}/reopen`, {
      method: 'POST',
      token,
      headers: {
        'Idempotency-Key': idempotencyKey,
        'If-Match': String(revision),
      },
      body: JSON.stringify(payload),
    })
  },
  resolveHandoff(token, claimId, handoffId, revision, payload) {
    return mutationRequest(
      `/api/v1/workbench/claims/${encodeURIComponent(claimId)}/handoffs/${encodeURIComponent(handoffId)}/resolve`,
      {
        method: 'POST',
        token,
        headers: {
          'If-Match': String(revision),
        },
        body: JSON.stringify(payload),
      },
    )
  },
  decideSignal(token, claimId, signalId, revision, payload) {
    return mutationRequest(
      `/api/v1/workbench/claims/${encodeURIComponent(claimId)}/signals/${encodeURIComponent(signalId)}/decisions`,
      {
        method: 'POST',
        token,
        headers: {
          'If-Match': String(revision),
        },
        body: JSON.stringify(payload),
      },
    )
  },
  createStaffAction(token, claimId, revision, payload) {
    return mutationRequest(`/api/v1/workbench/claims/${encodeURIComponent(claimId)}/staff-actions`, {
      method: 'POST',
      token,
      headers: {
        'If-Match': String(revision),
      },
      body: JSON.stringify(payload),
    })
  },
  updateStaffAction(token, claimId, actionId, revision, payload) {
    return mutationRequest(
      `/api/v1/workbench/claims/${encodeURIComponent(claimId)}/staff-actions/${encodeURIComponent(actionId)}`,
      {
        method: 'PATCH',
        token,
        headers: {
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
    const pendingOperation = pendingStaffMessageOperation(
      claimId,
      sessionId,
      message,
      revision,
    )

    try {
      const response = await mutationRequest(
        `/api/v1/workbench/claims/${encodeURIComponent(claimId)}/messages`,
        {
          method: 'POST',
          token,
          headers: {
            'Idempotency-Key': pendingOperation.key,
            'If-Match': String(pendingOperation.revision),
          },
          body: JSON.stringify({ content: { type: 'text', text: message } }),
        },
      )
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
  return mutationRequest(`/api/v1/workbench/claims/${encodeURIComponent(claimId)}/${resource}`, {
    method: 'POST',
    token,
    headers: {
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

async function claimSessionsForTarget(token, claimId, requestedSessionId) {
  const items = []
  const seenCursors = new Set()
  let cursor = null
  let lastResponse

  while (true) {
    const response = await pagedClaimResource(
      token,
      claimId,
      'sessions',
      cursor,
    )

    lastResponse = response || {}
    items.push(...(response?.items || []))

    if (requestedSessionId) {
      const resolvedSession = items.find(
        (item) => item.session_id === requestedSessionId,
      )

      if (resolvedSession) {
        return {
          ...lastResponse,
          items,
          resolved_session: resolvedSession,
        }
      }
    }

    const nextCursor = response?.page?.next_cursor || null

    if (!nextCursor || seenCursors.has(nextCursor)) {
      return {
        ...lastResponse,
        items,
        page: {
          ...(lastResponse.page || {}),
          next_cursor: null,
        },
        resolved_session: requestedSessionId
          ? null
          : items.at(-1) || null,
      }
    }

    seenCursors.add(nextCursor)
    cursor = nextCursor
  }
}

function pagedWorkbenchResource(token, path, cursor, limit) {
  const params = new URLSearchParams({ limit: String(limit) })
  if (cursor) params.set('cursor', cursor)
  return request(`/api/v1/workbench/claims/${path}?${params}`, { token })
}


function pendingStaffMessageOperation(
  claimId,
  sessionId,
  message,
  revision,
) {
  const operations = readStaffMessageOperations()
  const existing = operations[claimId]

  if (existing) {
    if (
      existing.sessionId !== sessionId
      || existing.message !== message
    ) {
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
    revision,
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

function clearStaffMessageOperations() {
  volatileStaffMessageOperations = {}

  try {
    sessionStorage.removeItem(STAFF_MESSAGE_OPERATIONS_KEY)
  } catch {
    // In-memory state is still cleared.
  }
}

function readStaffMessageOperations() {
  try {
    const operations = JSON.parse(
      sessionStorage.getItem(STAFF_MESSAGE_OPERATIONS_KEY) || '{}',
    )

    if (
      operations
      && typeof operations === 'object'
      && !Array.isArray(operations)
    ) {
      volatileStaffMessageOperations = { ...operations }
      return operations
    }
  } catch {
    // Fall through to the in-memory copy.
  }

  return { ...volatileStaffMessageOperations }
}

function writeStaffMessageOperations(operations) {
  volatileStaffMessageOperations = { ...operations }

  try {
    sessionStorage.setItem(
      STAFF_MESSAGE_OPERATIONS_KEY,
      JSON.stringify(operations),
    )
  } catch {
    // In-memory state preserves retry identity for this page lifetime.
  }
}

function ambiguousStaffMessageFailure(error) {
  return Boolean(
    error?.retryable
    || error?.code === 'NETWORK_ERROR'
    || error?.status === 0
    || error?.status === 429
    || error?.status >= 500
  )
}
