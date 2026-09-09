export async function adminFetch(path, { token, ...options } = {}) {
  const headers = new Headers(options.headers || {})
  headers.set('Accept', 'application/json')
  if (token) headers.set('Authorization', `Bearer ${token}`)
  const response = await fetch(path, { ...options, headers })
  const payload = await response.json().catch(() => ({}))
  if (!response.ok) {
    const error = new Error(payload?.error?.message || `Request failed (${response.status})`)
    error.status = response.status
    error.code = payload?.error?.code
    error.requestId = payload?.error?.request_id
    error.details = payload?.error?.details || []
    error.retryable = payload?.error?.retryable || false
    error.currentRevision = payload?.error?.current_revision
    throw error
  }
  return payload
}

export function idempotencyKey(prefix = 'admin') {
  const suffix = globalThis.crypto?.randomUUID?.() || `${Date.now()}-${Math.random()}`
  return `${prefix}-${suffix}`
}

export function adminMutation(path, { token, method = 'POST', body, revision, key } = {}) {
  const headers = new Headers()
  headers.set('Content-Type', 'application/json')
  if (method !== 'GET') headers.set('Idempotency-Key', key || idempotencyKey())
  if (revision !== undefined && revision !== null) headers.set('If-Match', `"${revision}"`)
  return adminFetch(path, {
    token,
    method,
    headers,
    body: body === undefined ? undefined : JSON.stringify(body),
  })
}

export function withQuery(path, values) {
  const query = new URLSearchParams()
  Object.entries(values).forEach(([key, value]) => {
    if (value !== '' && value !== null && value !== undefined) query.set(key, value)
  })
  const suffix = query.toString()
  return suffix ? `${path}?${suffix}` : path
}

export function getToken() {
  return sessionStorage.getItem('northwind.admin.token') || ''
}

export function setToken(value) {
  if (value) sessionStorage.setItem('northwind.admin.token', value)
  else sessionStorage.removeItem('northwind.admin.token')
}
