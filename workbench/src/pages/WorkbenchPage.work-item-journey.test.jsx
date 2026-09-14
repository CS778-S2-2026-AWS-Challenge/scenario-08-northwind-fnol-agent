import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import WorkbenchPage from './WorkbenchPage.jsx'

const tabs = vi.hoisted(() => ({
  tabs: [], activeId: null, open: vi.fn(), activate: vi.fn(), close: vi.fn(), update: vi.fn(),
}))

vi.mock('../auth/auth-context.js', () => ({
  useAuth: () => ({
    token: 'staff-token',
    profile: { staff_id: 'stf_demo', display_name: 'Demo Staff' },
    logout: vi.fn(),
  }),
}))
vi.mock('../hooks/usePersistentTabs.js', () => ({ usePersistentTabs: () => tabs }))
vi.mock('../components/NavigationRail.jsx', () => ({ default: () => null }))
vi.mock('../components/ClaimTabs.jsx', () => ({ default: () => null }))
vi.mock('../components/StaffAgent.jsx', () => ({ default: () => null }))

const metadata = {
  views: [
    { value: 'all', label: 'All active work', group: 'overview' },
    { value: 'processing', label: 'Processing', group: 'active' },
  ],
  workflow_states: [
    { value: 'professional_review', label: 'Professional review' },
    { value: 'ready_for_next', label: 'Ready for next' },
  ],
  priorities: [{ value: 'standard', label: 'Standard' }],
  tags: [],
  tag_registry_version: '0.3',
}

function jsonResponse(status, payload) {
  return { status, ok: status >= 200 && status < 300, json: vi.fn().mockResolvedValue(payload) }
}

function updateAction(revision) {
  return {
    registry_version: '2026-09-11.1',
    action_code: 'work_item.update',
    target_type: 'work_item',
    target_ref: 'act_review',
    label: 'Update assigned work',
    purpose: 'Progress or complete this exact assigned WorkItem.',
    availability: 'confirmation_required',
    confirmation: {
      level: 'explicit',
      message: 'The selected status and any completion result will be audited.',
    },
    expected_effects: ['work_item.update', 'claim.revision.advance'],
    claimant_visible_effects: ['customer_next_step.update', 'customer_update.append'],
    source_refs: ['pol_fixture'],
    inputs: [
      {
        field_code: 'status',
        label: 'Status',
        control: 'select',
        required: true,
        choices: [
          { value: 'in_progress', label: 'In progress' },
          { value: 'completed', label: 'Completed' },
          { value: 'cancelled', label: 'Cancelled' },
        ],
      },
      {
        field_code: 'result.summary',
        label: 'Result summary',
        control: 'textarea',
        required: false,
        required_when: { field_code: 'status', equals: 'completed' },
        choices: [],
      },
      {
        field_code: 'customer_update.summary',
        label: 'Claimant update',
        control: 'textarea',
        required: false,
        required_when: { field_code: 'status', equals: 'completed' },
        choices: [],
      },
    ],
    payload_defaults: {
      result: {
        outcome: 'professional_review_completed',
        reason_codes: ['POLICY_SECTION_CONFIRMED'],
        source_refs: ['pol_fixture'],
      },
      state_changes: [
        { path: 'claim_state.coverage', to: 'clear' },
        { path: 'claim_state.workflow_state', to: 'ready_for_next' },
      ],
      customer_update: { responsible_party: 'claimant', related_refs: ['act_review'] },
    },
    based_on_revision: revision,
  }
}

function workItem(state) {
  return {
    action_id: 'act_review',
    claim_id: 'clm_work_item',
    action_type: 'coverage_review',
    requested_outcome: 'Review the applicable policy wording for this Claim.',
    status: state.phase,
    assigned_to: 'stf_demo',
    source_refs: ['pol_fixture'],
    created_at: '2026-09-14T02:20:00Z',
    started_at: state.phase === 'open' ? null : '2026-09-14T02:21:00Z',
    completed_at: state.phase === 'completed' ? '2026-09-14T02:22:00Z' : null,
    completed_by: state.phase === 'completed' ? 'stf_demo' : null,
    result: state.result,
  }
}

function claimProjection(state) {
  const completed = state.phase === 'completed'
  const action = completed ? null : updateAction(state.revision)
  const workflow = completed ? 'ready_for_next' : 'professional_review'
  return {
    claim_id: 'clm_work_item',
    display_reference: 'NW-WORKITEM',
    revision: state.revision,
    claimant: { customer_id: 'cus_work', display_name: 'WorkItem Journey Claimant' },
    incident: { family: 'motor', summary: 'Coverage wording requires staff review.' },
    lifecycle_state: 'staff_support',
    workflow_state: workflow,
    created_at: '2026-09-14T02:19:00Z',
    updated_at: `2026-09-14T02:2${state.revision}:00Z`,
    active_session_id: null,
    claim_state: {
      severity: 'unassessed',
      coverage: completed ? 'clear' : 'requires_review',
      evidence: 'not_started',
      fraud_signal: 'none',
      customer_support: 'none',
      urgency: 'normal',
      workflow_state: workflow,
      next_action: 'PROCEED',
    },
    ownership: {
      state: 'assigned',
      current_staff_access: 'primary',
      primary_assignee: { staff_id: 'stf_demo', display_name: 'Demo Staff' },
    },
    priority_projection: {
      level: 'standard', rank: 0, reasons: [], due_at: null, is_overdue: false,
      computed_at: '2026-09-14T02:19:00Z',
    },
    work_summary: {
      queue_key: 'processing',
      current_work_item: completed ? null : {
        action_id: 'act_review',
        action_type: 'coverage_review',
        requested_outcome: 'Review the applicable policy wording for this Claim.',
        status: state.phase,
      },
      primary_action_code: action?.action_code || null,
      primary_action_target_ref: action?.target_ref || null,
      missing_information: [],
      risk_signals: [],
    },
    allowed_actions: action ? [action] : [],
    integration_summary: {
      claim_creation_status: null, assessor_routing_status: null, waiting_external_services: [],
    },
    customer_next_step: {
      status: completed ? 'staff_update' : 'professional_review',
      responsible_party: completed ? 'claimant' : 'claims_professional',
      summary: completed
        ? state.customerUpdates.at(-1).summary
        : 'A claims professional is reviewing the applicable policy wording.',
      can_resume: true,
      required_items: [],
    },
    source_summary: { status: 'empty', items: [], limitation: null },
    section_summaries: {
      fields: { status: 'available', total: 0, needs_attention: 0 },
      conversation: { status: 'available', total: 0, needs_attention: 0 },
      evidence: { status: 'available', total: 0, needs_attention: 0 },
      reference_checks: { status: 'available', total: 0, needs_attention: 0 },
      external_services: { status: 'available', total: 0, needs_attention: 0 },
      activity: { status: 'available', total: 1 + state.events.length, needs_attention: 0 },
    },
    tags: [],
  }
}

function queueProjection(state) {
  const detail = claimProjection(state)
  return {
    claim_id: detail.claim_id,
    display_reference: detail.display_reference,
    claimant: detail.claimant,
    incident: detail.incident,
    lifecycle_state: detail.lifecycle_state,
    workflow_state: detail.workflow_state,
    terminal_disposition: null,
    ownership: detail.ownership,
    priority_projection: detail.priority_projection,
    work_summary: { ...detail.work_summary, unread_claimant_messages: 0, external_wait_count: 0 },
    integration_summary: detail.integration_summary,
    tags: [],
    revision: detail.revision,
    created_at: detail.created_at,
    updated_at: detail.updated_at,
  }
}

function createService() {
  const state = {
    revision: 2,
    phase: 'open',
    result: null,
    customerUpdates: [],
    events: [],
    mutations: [],
    workItemReads: [],
    customerUpdateReads: [],
    eventReads: [],
  }
  const page = (items) => ({ items, page: { next_cursor: null } })

  const fetchMock = vi.fn(async (url, options = {}) => {
    const path = String(url)
    const method = options.method || 'GET'

    if (path === '/api/v1/workbench/claims/filter-metadata') return jsonResponse(200, metadata)
    if (method === 'GET' && (path === '/api/v1/workbench/claims' || path.startsWith('/api/v1/workbench/claims?'))) {
      return jsonResponse(200, {
        ...page([queueProjection(state)]),
        view_counts: {
          status: 'available',
          items: [{ view: 'all', count: 1 }, { view: 'processing', count: 1 }],
          limitation: null,
        },
      })
    }
    if (method === 'GET' && path === '/api/v1/workbench/claims/clm_work_item') {
      return jsonResponse(200, claimProjection(state))
    }
    if (method === 'GET' && (
      path.startsWith('/api/v1/workbench/claims/clm_work_item/handoffs?')
      || path.startsWith('/api/v1/workbench/claims/clm_work_item/collaboration-requests?')
    )) return jsonResponse(200, page([]))
    if (method === 'GET' && path.startsWith('/api/v1/workbench/claims/clm_work_item/work-items?')) {
      state.workItemReads.push({ revision: state.revision, status: state.phase })
      return jsonResponse(200, page([workItem(state)]))
    }
    if (method === 'GET' && path.startsWith('/api/v1/workbench/claims/clm_work_item/customer-updates?')) {
      state.customerUpdateReads.push({
        revision: state.revision,
        summaries: state.customerUpdates.map((item) => item.summary),
      })
      return jsonResponse(200, page(state.customerUpdates.map((item) => ({ ...item }))))
    }
    if (method === 'GET' && path.startsWith('/api/v1/workbench/claims/clm_work_item/events?')) {
      state.eventReads.push({
        revision: state.revision,
        summaries: state.events.map((item) => item.summary),
      })
      return jsonResponse(200, page(state.events.map((item) => ({ ...item }))))
    }
    if (method === 'PATCH' && path === '/api/v1/workbench/claims/clm_work_item/staff-actions/act_review') {
      const request = {
        revision: options.headers['If-Match'],
        idempotencyKey: options.headers['Idempotency-Key'],
        payload: JSON.parse(options.body),
      }
      state.mutations.push(request)
      const expected = state.phase === 'open' ? '2' : '3'
      if (request.revision !== expected) {
        return jsonResponse(409, {
          error: { code: 'REVISION_CONFLICT', message: 'The Claim changed after this page was loaded.' },
        })
      }
      if (request.payload.status === 'in_progress' && state.phase === 'open') {
        state.phase = 'in_progress'
        state.revision = 3
        state.events.push({
          event_id: 'evt_work_started',
          event_type: 'work_item.updated',
          actor_id: 'stf_demo',
          summary: 'Coverage review moved to in progress.',
          source_refs: ['act_review'],
          created_at: '2026-09-14T02:21:00Z',
          resulting_revision: 3,
        })
        return jsonResponse(200, { action: workItem(state), revision: state.revision })
      }
      if (request.payload.status === 'completed' && state.phase === 'in_progress') {
        state.phase = 'completed'
        state.revision = 4
        state.result = request.payload.result
        state.customerUpdates.push({
          update_id: 'upd_work_complete',
          claim_id: 'clm_work_item',
          created_by: 'stf_demo',
          responsible_party: request.payload.customer_update.responsible_party,
          summary: request.payload.customer_update.summary,
          related_refs: ['act_review'],
          created_at: '2026-09-14T02:22:00Z',
        })
        state.events.push({
          event_id: 'evt_work_complete',
          event_type: 'work_item.completed',
          actor_id: 'stf_demo',
          summary: 'Coverage review completed and the Claim returned to ready for next.',
          source_refs: ['act_review', 'upd_work_complete'],
          created_at: '2026-09-14T02:22:00Z',
          resulting_revision: 4,
        })
        return jsonResponse(200, {
          action: workItem(state),
          revision: state.revision,
          customer_update: state.customerUpdates.at(-1),
        })
      }
      return jsonResponse(409, {
        error: { code: 'INVALID_STATE_TRANSITION', message: 'Invalid WorkItem transition.' },
      })
    }
    throw new Error(`Unexpected Workbench request: ${method} ${path}`)
  })
  return { fetchMock, state }
}

function renderJourney() {
  return render(
    <MemoryRouter initialEntries={['/workbench']}>
      <Routes>
        <Route path="/workbench" element={<WorkbenchPage />} />
        <Route path="/workbench/claims/:claimId" element={<WorkbenchPage />} />
        <Route path="/workbench/claims/:claimId/:section" element={<WorkbenchPage />} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('WorkbenchPage WorkItem browser/API journey', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    sessionStorage.clear()
    tabs.tabs = [{
      claimId: 'clm_work_item',
      displayReference: 'NW-WORKITEM',
      section: 'summary',
      sessionId: null,
      draft: '',
    }]
    tabs.activeId = null
    tabs.open.mockImplementation((claim) => { tabs.activeId = claim.claim_id })
    tabs.activate.mockImplementation((claimId) => { tabs.activeId = claimId })
    tabs.update.mockImplementation((claimId, patch) => {
      const tab = tabs.tabs.find((item) => item.claimId === claimId)
      if (tab) Object.assign(tab, patch)
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it('progresses and completes the exact projected WorkItem with authoritative readback', async () => {
    const { fetchMock, state } = createService()
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    renderJourney()

    await user.click(await screen.findByText('NW-WORKITEM'))
    expect(await screen.findByRole('heading', { name: 'WorkItem Journey Claimant' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Update assigned work' })).toBeVisible()

    await user.click(screen.getByRole('button', { name: 'Open work activity' }))
    await user.click(await screen.findByText('Coverage Review'))
    await user.selectOptions(screen.getByLabelText('Status'), 'in_progress')
    await user.click(screen.getByRole('button', { name: 'Update action' }))

    await waitFor(() => {
      expect(state.mutations).toHaveLength(1)
      expect(state.mutations[0]).toMatchObject({
        revision: '2',
        payload: { status: 'in_progress', result: null, state_changes: [], customer_update: null },
      })
      expect(screen.getByText('Revision 3')).toBeVisible()
      expect(screen.getByText('In Progress')).toBeVisible()
    })
    expect(state.mutations[0].idempotencyKey).toBeTruthy()
    expect(state.workItemReads.some((read) => (
      read.revision === 3 && read.status === 'in_progress'
    ))).toBe(true)

    await user.click(screen.getByText('Coverage Review'))
    await user.selectOptions(screen.getByLabelText('Status'), 'completed')
    await user.type(
      screen.getByLabelText('Result summary'),
      'The applicable policy wording was reviewed.',
    )
    await user.type(
      screen.getByLabelText('Claimant update'),
      'The policy review is complete and your report can continue.',
    )
    await user.click(screen.getByRole('button', { name: 'Update action' }))

    await waitFor(() => {
      expect(state.mutations).toHaveLength(2)
      expect(state.mutations[1]).toMatchObject({
        revision: '3',
        payload: {
          status: 'completed',
          result: {
            outcome: 'professional_review_completed',
            reason_codes: ['POLICY_SECTION_CONFIRMED'],
            source_refs: ['pol_fixture'],
            summary: 'The applicable policy wording was reviewed.',
          },
          state_changes: [
            { path: 'claim_state.coverage', to: 'clear' },
            { path: 'claim_state.workflow_state', to: 'ready_for_next' },
          ],
          customer_update: {
            responsible_party: 'claimant',
            related_refs: ['act_review'],
            summary: 'The policy review is complete and your report can continue.',
          },
        },
      })
      expect(screen.getByText('Revision 4')).toBeVisible()
    })
    expect(state.mutations[1].idempotencyKey).toBeTruthy()

    expect(await screen.findByText('Completed')).toBeVisible()
    expect(await screen.findByText(
      'The policy review is complete and your report can continue.',
    )).toBeVisible()
    expect(await screen.findByText(
      'Coverage review completed and the Claim returned to ready for next.',
    )).toBeVisible()

    await waitFor(() => {
      expect(state.workItemReads.at(-1)).toEqual({ revision: 4, status: 'completed' })
      expect(state.customerUpdateReads.at(-1).summaries).toContain(
        'The policy review is complete and your report can continue.',
      )
      expect(state.eventReads.at(-1).summaries).toContain(
        'Coverage review completed and the Claim returned to ready for next.',
      )
    })
  })
})
