import { cleanup, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter } from 'react-router-dom'
import { afterEach, beforeEach, expect, it, vi } from 'vitest'
import App from './App.jsx'

const jsonResponse = (payload, status = 200) => new Response(JSON.stringify(payload), { status, headers: { 'Content-Type': 'application/json' } })
const emptyPage = { items: [], page: { next_cursor: null } }

beforeEach(() => sessionStorage.clear())
afterEach(() => {
  cleanup()
  vi.unstubAllGlobals()
})

it('requires an administrator token before rendering the console', () => {
  render(<MemoryRouter initialEntries={['/admin']}><App /></MemoryRouter>)
  expect(screen.getByRole('heading', { name: /sign in to administration/i })).toBeInTheDocument()
})

it('renders server-backed configuration state after administrator sign-in', async () => {
  sessionStorage.setItem('northwind.admin.token', 'synthetic-admin')
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(jsonResponse({
    items: [{ configuration_id: 'cfg_demo', domain: 'model', state: 'published', revision: 2, allowed_actions: [] }],
    page: { next_cursor: null },
  })))

  render(<MemoryRouter initialEntries={['/admin/configurations']}><App /></MemoryRouter>)

  await waitFor(() => expect(screen.getByText('cfg_demo')).toBeInTheDocument())
  expect(screen.getByText('model')).toBeInTheDocument()
  expect(fetch).toHaveBeenCalledWith('/internal/v1/admin/configurations', expect.objectContaining({ headers: expect.any(Headers) }))
})

it('uses the projected revision and idempotency key for a configuration action', async () => {
  const user = userEvent.setup()
  sessionStorage.setItem('northwind.admin.token', 'synthetic-admin')
  const record = { configuration_id: 'cfg_feature', domain: 'feature', state: 'draft', revision: 3, values: { feature_version: 'v1', model_assisted_turns: true, knowledge_retrieval: true }, secret_references: {}, allowed_actions: [{ action_code: 'admin.configuration.patch', availability: 'available', expected_revision: 3, reason: null }] }
  let currentRecord = record
  const fetchMock = vi.fn(async (path, options = {}) => {
    if (path === '/internal/v1/admin/configurations' && options.method === 'PATCH') {
      currentRecord = { ...record, revision: 4 }
      return jsonResponse(currentRecord)
    }
    if (path === '/internal/v1/admin/configurations') {
      return jsonResponse({ items: [currentRecord], page: { next_cursor: null } })
    }
    throw new Error(`Unexpected request: ${options.method || 'GET'} ${path}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  render(<MemoryRouter initialEntries={['/admin/configurations']}><App /></MemoryRouter>)

  await user.click((await screen.findByText('cfg_feature')).closest('button'))
  await user.selectOptions(screen.getByLabelText('Action'), 'admin.configuration.patch')
  await user.click(screen.getByRole('button', { name: /apply action/i }))

  await waitFor(() => expect(fetchMock.mock.calls.some(([, options]) => options.method === 'PATCH')).toBe(true))
  const [, options] = fetchMock.mock.calls.find(([, requestOptions]) => requestOptions.method === 'PATCH')
  expect(options.method).toBe('PATCH')
  expect(options.headers.get('If-Match')).toBe('"3"')
  expect(options.headers.get('Idempotency-Key')).toBeTruthy()
})

it('resolves a Runtime Snapshot using explicit environment and profile inputs', async () => {
  const user = userEvent.setup()
  sessionStorage.setItem('northwind.admin.token', 'synthetic-admin')
  const fetchMock = vi.fn().mockResolvedValue(jsonResponse({ release_set_id: 'rel_active', environment: 'test', runtime_profile: 'fixture', loaded_at: '2026-09-07T00:00:00Z', configurations: {}, integrations: {}, knowledge: {} }))
  vi.stubGlobal('fetch', fetchMock)
  render(<MemoryRouter initialEntries={['/admin/runtime']}><App /></MemoryRouter>)

  await user.click(screen.getByRole('button', { name: /resolve snapshot/i }))

  await waitFor(() => expect(screen.getByRole('heading', { name: 'rel_active' })).toBeInTheDocument())
  expect(fetchMock.mock.calls[0][0]).toContain('environment=test')
  expect(fetchMock.mock.calls[0][0]).toContain('runtime_profile=fixture')
})

it('runs only the server-projected integration health action', async () => {
  const user = userEvent.setup()
  sessionStorage.setItem('northwind.admin.token', 'synthetic-admin')
  const integration = { integration_id: 'assessor_service', label: 'Assessor service', capability: 'assessor_routing', health: 'using_fixture', implementation: 'Fixture', source: 'fixture', configuration_ids: [], latency_ms: 1, failure_code: null, allowed_actions: [{ action_code: 'admin.integration.health_check', availability: 'available', expected_revision: null, reason: null }] }
  const fetchMock = vi.fn(async (path, options = {}) => {
    if (path === '/internal/v1/admin/integrations/assessor_service/health-check' && options.method === 'POST') {
      return jsonResponse({ check_id: 'ihc_1', integration_id: 'assessor_service', health: 'using_fixture' })
    }
    if (path === '/internal/v1/admin/integrations/assessor_service/health-checks') {
      return jsonResponse(emptyPage)
    }
    if (path === '/internal/v1/admin/integrations') {
      return jsonResponse({ items: [integration], page: { next_cursor: null } })
    }
    throw new Error(`Unexpected request: ${options.method || 'GET'} ${path}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  render(<MemoryRouter initialEntries={['/admin/integrations']}><App /></MemoryRouter>)

  await user.click((await screen.findByText('assessor_service')).closest('button'))
  await user.selectOptions(screen.getByLabelText('Action'), 'admin.integration.health_check')
  await user.click(screen.getByRole('button', { name: /run health check/i }))

  await waitFor(() => expect(fetchMock.mock.calls.some(([path, options]) => path.endsWith('/health-check') && options.method === 'POST')).toBe(true))
  const [, options] = fetchMock.mock.calls.find(([path, requestOptions]) => path.endsWith('/health-check') && requestOptions.method === 'POST')
  expect(options.headers.get('Idempotency-Key')).toBeTruthy()
})

it('does not submit customer deactivation without explicit confirmation', async () => {
  const user = userEvent.setup()
  sessionStorage.setItem('northwind.admin.token', 'synthetic-admin')
  const customer = { customer_id: 'cus_demo', email: 'claimant@example.invalid', display_name: 'Demo', phone: '', active: true, revision: 1, updated_at: '2026-09-07T00:00:00Z', communication_preferences: { email: true, sms: false }, allowed_actions: [{ action_code: 'admin.customer_account.update', availability: 'available', expected_revision: 1, reason: null }] }
  const fetchMock = vi.fn(async (path, options = {}) => {
    if (path === '/internal/v1/admin/accounts/customers' && !options.method) {
      return jsonResponse({ items: [customer], page: { next_cursor: null } })
    }
    if (path === '/internal/v1/admin/accounts/customers/cus_demo/sessions') return jsonResponse(emptyPage)
    throw new Error(`Unexpected request: ${options.method || 'GET'} ${path}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  render(<MemoryRouter initialEntries={['/admin/customers']}><App /></MemoryRouter>)

  await user.click((await screen.findByText('cus_demo')).closest('button'))
  await user.selectOptions(screen.getByLabelText('Action'), 'admin.customer_account.update')
  await user.click(screen.getByLabelText('Account is active'))

  expect(screen.getByRole('button', { name: /save account/i })).toBeDisabled()
  expect(fetchMock.mock.calls.every(([, options]) => !options.method)).toBe(true)
})

it('revokes only a server-projected identity session with revision and idempotency', async () => {
  const user = userEvent.setup()
  sessionStorage.setItem('northwind.admin.token', 'synthetic-admin')
  const customer = { customer_id: 'cus_demo', email: 'claimant@example.invalid', display_name: 'Demo', phone: '', active: true, revision: 1, updated_at: '2026-09-07T00:00:00Z', communication_preferences: { email: true, sms: false }, allowed_actions: [{ action_code: 'admin.customer_account.update', availability: 'available', expected_revision: 1, reason: null }] }
  const session = { session_id: 'ias_demo', state: 'active', revision: 2, created_at: '2026-09-07T00:00:00Z', expires_at: '2026-09-08T00:00:00Z', revoked_at: null, updated_at: '2026-09-07T00:00:00Z', allowed_actions: [{ action_code: 'admin.account_session.revoke', availability: 'confirmation_required', expected_revision: 2, reason: null }] }
  let sessions = [session]
  const fetchMock = vi.fn(async (path, options = {}) => {
    if (path.endsWith('/ias_demo/revoke') && options.method === 'POST') {
      sessions = [{ ...session, state: 'revoked', revision: 3, revoked_at: '2026-09-07T01:00:00Z', allowed_actions: [] }]
      return jsonResponse(sessions[0])
    }
    if (path === '/internal/v1/admin/accounts/customers/cus_demo/sessions') return jsonResponse({ items: sessions, page: { next_cursor: null } })
    if (path === '/internal/v1/admin/accounts/customers') return jsonResponse({ items: [customer], page: { next_cursor: null } })
    throw new Error(`Unexpected request: ${options.method || 'GET'} ${path}`)
  })
  vi.stubGlobal('fetch', fetchMock)
  render(<MemoryRouter initialEntries={['/admin/customers']}><App /></MemoryRouter>)

  await user.click((await screen.findByText('cus_demo')).closest('button'))
  await user.click(await screen.findByRole('button', { name: /^revoke session$/i }))
  await user.click(screen.getByLabelText(/confirm revocation/i))
  await user.click(screen.getByRole('button', { name: /confirm revocation/i }))

  await waitFor(() => expect(fetchMock.mock.calls.some(([path]) => path.endsWith('/ias_demo/revoke'))).toBe(true))
  const [, options] = fetchMock.mock.calls.find(([path]) => path.endsWith('/ias_demo/revoke'))
  expect(options.headers.get('If-Match')).toBe('"2"')
  expect(options.headers.get('Idempotency-Key')).toBeTruthy()
})

it('renders persisted model usage, configured cost, rate-limit state, and alerts', async () => {
  sessionStorage.setItem('northwind.admin.token', 'synthetic-admin')
  const metrics = {
    total: 2,
    by_state: { succeeded: 1, failed: 1 },
    by_kind: { model_invocation: 2 },
    usage: { calls: 2, reported_calls: 2, input_tokens: 100, output_tokens: 20, total_tokens: 120 },
    cost: { status: 'configured', currency: 'USD', estimated_microunits: 140, priced_calls: 2, unpriced_calls: 0, configuration_id: 'cfg_operations', configuration_revision: 1 },
    rate_limit: { status: 'limited', events_in_window: 1, window_seconds: 3600, latest_event_at: '2026-09-07T01:00:00Z' },
    alerts: [
      { alert_code: 'operations.total_tokens', metric: 'total_tokens', status: 'triggered', observed: 120, threshold: 100 },
    ],
    source: 'control_plane_operation_repository',
  }
  const fetchMock = vi.fn(async (path) => {
    if (path === '/internal/v1/admin/operations/metrics') return jsonResponse(metrics)
    if (path === '/internal/v1/admin/operations') return jsonResponse(emptyPage)
    throw new Error(`Unexpected request: GET ${path}`)
  })
  vi.stubGlobal('fetch', fetchMock)

  render(<MemoryRouter initialEntries={['/admin/operations']}><App /></MemoryRouter>)

  expect(await screen.findByText('120')).toBeInTheDocument()
  expect(screen.getByText('USD 0.00014')).toBeInTheDocument()
  expect(screen.getByText('rate limits in 3600s')).toBeInTheDocument()
  expect(screen.getByRole('heading', { name: 'Configured alerts' })).toBeInTheDocument()
  expect(screen.getByText('triggered')).toBeInTheDocument()
})

it('keeps operation records usable when operational metrics cannot be loaded', async () => {
  sessionStorage.setItem('northwind.admin.token', 'synthetic-admin')
  const fetchMock = vi.fn(async (path) => {
    if (path === '/internal/v1/admin/operations/metrics') throw new Error('metrics unavailable')
    if (path === '/internal/v1/admin/operations') return jsonResponse(emptyPage)
    throw new Error(`Unexpected request: GET ${path}`)
  })
  vi.stubGlobal('fetch', fetchMock)

  render(<MemoryRouter initialEntries={['/admin/operations']}><App /></MemoryRouter>)

  expect(await screen.findByRole('alert')).toHaveTextContent('Operational metrics could not be loaded')
  expect(screen.getByText('No records are available.')).toBeInTheDocument()
})
