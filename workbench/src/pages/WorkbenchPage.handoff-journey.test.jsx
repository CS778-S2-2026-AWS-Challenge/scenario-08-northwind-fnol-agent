import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
import WorkbenchPage from './WorkbenchPage.jsx'

const tabs = vi.hoisted(() => ({
  tabs: [],
  activeId: null,
  open: vi.fn(),
  activate: vi.fn(),
  close: vi.fn(),
  update: vi.fn(),
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
    { value: 'ready_for_next', label: 'Ready for next' },
  ],
  priorities: [{ value: 'standard', label: 'Standard' }],
  tags: [],
  tag_registry_version: '0.3',
}

function jsonResponse(status, payload) {
  return {
    status,
    ok: status >= 200 && status < 300,
    json: vi.fn().mockResolvedValue(payload),
  }
}

function actionBase(actionCode, targetType, targetRef, revision, label, purpose) {
  return {
    registry_version: '2026-09-11.1',
    action_code: actionCode,
    target_type: targetType,
    target_ref: targetRef,
    label,
    purpose,
    availability: 'confirmation_required',
    confirmation: { level: 'explicit', message: `Confirm ${label.toLowerCase()}.` },
    expected_effects: [],
    claimant_visible_effects: [],
    source_refs: ['hnd_journey'],
    inputs: [],
    based_on_revision: revision,
  }
}

function acceptAction(revision) {
  return {
    ...actionBase(
      'human.accept_handoff',
      'handoff',
      'hnd_journey',
      revision,
      'Accept Claim',
      'Take responsibility for the requested staff work.',
    ),
    expected_effects: ['handoff.accept', 'ownership.assign'],
    result_state: 'pending_confirmation',
  }
}

function sendAction(revision) {
  return {
    ...actionBase(
      'conversation.send_claimant_message',
      'session',
      'ses_journey',
      revision,
      'Reply to claimant',
      'Continue the accepted claimant conversation.',
    ),
    expected_effects: ['message.append', 'handoff.mark_in_progress'],
    claimant_visible_effects: ['message.append'],
    inputs: [{
      field_code: 'content.text',
      label: 'Claimant-visible message',
      control: 'textarea',
      required: true,
      choices: [],
    }],
  }
}

function resolveAction(revision) {
  return {
    ...actionBase(
      'human.resolve_handoff',
      'handoff',
      'hnd_journey',
      revision,
      'Resolve handoff',
      'Record the outcome and the claimant-safe next step.',
    ),
    expected_effects: [
      'handoff.resolve',
      'work_item.complete',
      'claim.update',
      'customer_update.append',
    ],
    claimant_visible_effects: [
      'customer_next_step.update',
      'customer_update.append',
    ],
    inputs: [
      {
        field_code: 'result.summary',
        label: 'Internal result summary',
        control: 'textarea',
        required: true,
        choices: [],
      },
      {
        field_code: 'customer_update.summary',
        label: 'Claimant update',
        control: 'textarea',
        required: true,
        choices: [],
      },
    ],
    payload_defaults: {
      result: {
        outcome: 'support_completed',
        reason_codes: ['SUPPORT_NEED_MET'],
        source_refs: ['msg_claimant_initial'],
      },
      state_changes: [],
      customer_update: {
        responsible_party: 'claims_professional',
        related_refs: ['hnd_journey'],
      },
    },
  }
}

function claimProjection(state) {
  const accepted = state.phase !== 'queued'
  const sent = ['in_progress', 'resolved'].includes(state.phase)
  const resolved = state.phase === 'resolved'
  const primaryAction = resolved
    ? null
    : state.phase === 'queued'
      ? acceptAction(state.revision)
      : sent
        ? resolveAction(state.revision)
        : sendAction(state.revision)
  const allowedActions = resolved
    ? []
    : state.phase === 'queued'
      ? [primaryAction]
      : [sendAction(state.revision), resolveAction(state.revision)]

  return {
    claim_id: 'clm_handoff_journey',
    display_reference: 'NW-HANDOFF',
    revision: state.revision,
    claimant: {
      customer_id: 'cus_journey',
      display_name: 'Journey Claimant',
    },
    incident: {
      family: state.family,
      summary: 'Minor collision requiring staff assistance.',
    },
    lifecycle_state: resolved ? 'ready_to_create' : 'staff_support',
    workflow_state: 'ready_for_next',
    created_at: '2026-09-14T00:00:00Z',
    updated_at: `2026-09-14T00:0${state.revision}:00Z`,
    active_session_id: 'ses_journey',
    claim_state: {
      severity: 'unassessed',
      coverage: 'not_assessed',
      evidence: 'not_started',
      fraud_signal: 'none',
      customer_support: 'human_requested',
      urgency: 'normal',
      workflow_state: 'ready_for_next',
      next_action: 'PROCEED',
    },
    ownership: accepted
      ? {
          state: 'assigned',
          current_staff_access: 'primary',
          primary_assignee: {
            staff_id: 'stf_demo',
            display_name: 'Demo Staff',
          },
        }
      : {
          state: 'unassigned',
          current_staff_access: 'read_only',
        },
    priority_projection: {
      level: 'standard',
      rank: 0,
      reasons: [],
      due_at: null,
      is_overdue: false,
      computed_at: '2026-09-14T00:00:00Z',
    },
    work_summary: {
      queue_key: 'processing',
      primary_action_code: primaryAction?.action_code || null,
      primary_action_target_ref: primaryAction?.target_ref || null,
      missing_information: [],
      risk_signals: [],
    },
    allowed_actions: allowedActions,
    integration_summary: {
      claim_creation_status: null,
      assessor_routing_status: null,
      waiting_external_services: [],
    },
    customer_next_step: {
      status: resolved ? 'staff_update' : 'human_support_in_progress',
      responsible_party: 'claims_professional',
      summary: resolved
        ? state.customerUpdates.at(-1).summary
        : 'A claims professional is helping with this Claim.',
      can_resume: true,
      required_items: [],
    },
    source_summary: { status: 'empty', items: [], limitation: null },
    section_summaries: {
      fields: { status: 'available', total: 0, needs_attention: 0 },
      conversation: { status: 'available', total: 1, needs_attention: 0 },
      evidence: { status: 'available', total: 0, needs_attention: 0 },
      reference_checks: { status: 'available', total: 0, needs_attention: 0 },
      external_services: { status: 'available', total: 0, needs_attention: 0 },
      activity: { status: 'available', total: state.events.length, needs_attention: 0 },
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
    work_summary: {
      queue_key: detail.work_summary.queue_key,
      current_work_item: null,
      primary_action_code: detail.work_summary.primary_action_code,
      primary_action_target_ref: detail.work_summary.primary_action_target_ref,
      missing_information: [],
      risk_signals: [],
      unread_claimant_messages: 0,
      external_wait_count: 0,
    },
    integration_summary: detail.integration_summary,
    tags: [],
    revision: detail.revision,
    created_at: detail.created_at,
    updated_at: detail.updated_at,
  }
}

function handoffProjection(state) {
  return {
    handoff_id: 'hnd_journey',
    claim_id: 'clm_handoff_journey',
    type: 'human_support',
    status: state.phase === 'queued'
      ? 'queued'
      : state.phase === 'accepted'
        ? 'accepted'
        : state.phase === 'in_progress'
          ? 'in_progress'
          : 'resolved',
    priority: 'standard',
    queue: 'claimant_support',
    support_need: 'human_requested',
    trigger: 'claimant_support_request',
    preferred_channel: 'in_app',
    reason_codes: ['CLAIMANT_SUPPORT_REQUESTED'],
    reason: 'Claimant requested staff support.',
    requested_action: 'Help the claimant continue the report.',
    applied_rule: 'claimant_support_request',
    packet: {
      incident_summary: 'Minor collision requiring staff assistance.',
      form_revision: 1,
      form_snapshot: {},
      evidence_refs: [],
      evidence: [],
      missing_items: [],
      pending_items: [],
      conflicts: [],
      low_confidence_items: [],
      policy_citation_refs: [],
      history_evidence_refs: [],
      source_refs: ['msg_claimant_initial'],
      prior_customer_updates: [],
      promised_next_step: 'A claims professional will review the Claim.',
    },
    source_message_id: 'msg_claimant_initial',
    assigned_to: state.phase === 'queued' ? null : 'stf_demo',
    created_at: '2026-09-14T00:00:00Z',
    accepted_at: state.phase === 'queued' ? null : '2026-09-14T00:02:00Z',
    resolved_at: state.phase === 'resolved' ? '2026-09-14T00:04:00Z' : null,
  }
}

function claimantMessage() {
  return {
    message_id: 'msg_claimant_initial',
    session_id: 'ses_journey',
    actor: 'claimant',
    visibility: 'shared',
    content: { type: 'text', text: 'Please help me continue this claim.' },
    created_at: '2026-09-14T00:00:00Z',
  }
}

function createHandoffJourneyService(family) {
  const state = {
    family,
    revision: 1,
    phase: 'queued',
    messages: [claimantMessage()],
    customerUpdates: [],
    events: [],
    acceptRequests: [],
    messageRequests: [],
    resolveRequests: [],
    queueReads: [],
    claimReads: [],
    handoffReads: [],
    customerUpdateReads: [],
    eventReads: [],
  }

  const fetchMock = vi.fn(async (url, options = {}) => {
    const path = String(url)
    const method = options.method || 'GET'

    if (path === '/api/v1/workbench/claims/filter-metadata') {
      return jsonResponse(200, metadata)
    }

    if (
      method === 'GET'
      && (path === '/api/v1/workbench/claims' || path.startsWith('/api/v1/workbench/claims?'))
    ) {
      const item = queueProjection(state)
      state.queueReads.push({
        revision: item.revision,
        workflow_state: item.workflow_state,
        phase: state.phase,
      })
      return jsonResponse(200, {
        items: [item],
        page: { next_cursor: null },
        view_counts: {
          status: 'available',
          items: [
            { view: 'all', count: 1 },
            { view: 'processing', count: 1 },
          ],
          limitation: null,
        },
      })
    }

    if (method === 'GET' && path === '/api/v1/workbench/claims/clm_handoff_journey') {
      const detail = claimProjection(state)
      state.claimReads.push({ revision: detail.revision, phase: state.phase })
      return jsonResponse(200, detail)
    }

    if (
      method === 'GET'
      && path.startsWith('/api/v1/workbench/claims/clm_handoff_journey/handoffs?')
    ) {
      const handoff = handoffProjection(state)
      state.handoffReads.push({ status: handoff.status, revision: state.revision })
      return jsonResponse(200, {
        items: [handoff],
        page: { next_cursor: null },
      })
    }

    if (
      method === 'GET'
      && path.startsWith('/api/v1/workbench/claims/clm_handoff_journey/collaboration-requests?')
    ) {
      return jsonResponse(200, { items: [], page: { next_cursor: null } })
    }

    if (
      method === 'POST'
      && path === '/api/v1/workbench/claims/clm_handoff_journey/handoffs/hnd_journey/accept'
    ) {
      const request = {
        revision: options.headers['If-Match'],
        idempotencyKey: options.headers['Idempotency-Key'],
        payload: JSON.parse(options.body),
      }
      state.acceptRequests.push(request)
      if (request.revision !== '1' || state.phase !== 'queued') {
        return jsonResponse(409, {
          error: {
            code: 'REVISION_CONFLICT',
            message: 'The Claim changed after this page was loaded.',
          },
        })
      }
      state.phase = 'accepted'
      state.revision = 2
      state.events.push({
        event_id: 'evt_accept',
        event_type: 'handoff.accepted',
        actor_id: 'stf_demo',
        summary: 'Staff accepted the handoff.',
        source_refs: ['hnd_journey'],
        created_at: '2026-09-14T00:02:00Z',
        resulting_revision: 2,
      })
      return jsonResponse(200, {
        handoff: handoffProjection(state),
        revision: state.revision,
      })
    }

    if (
      method === 'GET'
      && path.startsWith('/api/v1/workbench/claims/clm_handoff_journey/sessions?')
    ) {
      return jsonResponse(200, {
        items: [{
          session_id: 'ses_journey',
          claim_id: 'clm_handoff_journey',
          status: 'active',
          summary: 'Synthetic claimant conversation for the handoff journey.',
          unresolved_questions: [],
          pending_items: [],
          prior_commitments: [],
          context_revision: state.revision,
          question_budget: 9,
          question_turn_count: 0,
          requested_fact_count: 0,
          repeated_question_count: 0,
          remaining_question_budget: 9,
          post_session_follow_up_required: false,
          question_history: [],
          started_at: '2026-09-14T00:00:00Z',
          last_active_at: `2026-09-14T00:0${state.revision}:00Z`,
          closed_at: null,
        }],
        page: { next_cursor: null },
      })
    }

    if (
      method === 'GET'
      && path.startsWith(
        '/api/v1/workbench/claims/clm_handoff_journey/sessions/ses_journey/messages?',
      )
    ) {
      return jsonResponse(200, {
        items: state.messages.map((message) => ({ ...message })),
        page: { next_cursor: null },
      })
    }

    if (
      method === 'POST'
      && path === '/api/v1/workbench/claims/clm_handoff_journey/messages'
    ) {
      const request = {
        revision: options.headers['If-Match'],
        idempotencyKey: options.headers['Idempotency-Key'],
        payload: JSON.parse(options.body),
      }
      state.messageRequests.push(request)
      if (request.revision !== '2' || state.phase !== 'accepted') {
        return jsonResponse(409, {
          error: {
            code: 'REVISION_CONFLICT',
            message: 'The Claim changed after this page was loaded.',
          },
        })
      }
      const message = {
        message_id: 'msg_staff_journey',
        session_id: 'ses_journey',
        actor: 'staff',
        visibility: 'shared',
        content: request.payload.content,
        created_at: '2026-09-14T00:03:00Z',
      }
      state.messages.push(message)
      state.phase = 'in_progress'
      state.revision = 3
      state.events.push({
        event_id: 'evt_message',
        event_type: 'message.appended',
        actor_id: 'stf_demo',
        summary: 'Staff sent a claimant-visible update.',
        source_refs: ['msg_staff_journey'],
        created_at: '2026-09-14T00:03:00Z',
        resulting_revision: 3,
      })
      return jsonResponse(200, {
        message,
        claim_revision: state.revision,
      })
    }

    if (
      method === 'GET'
      && path.startsWith('/api/v1/workbench/claims/clm_handoff_journey/work-items?')
    ) {
      return jsonResponse(200, { items: [], page: { next_cursor: null } })
    }

    if (
      method === 'GET'
      && path.startsWith('/api/v1/workbench/claims/clm_handoff_journey/customer-updates?')
    ) {
      state.customerUpdateReads.push({
        revision: state.revision,
        summaries: state.customerUpdates.map((item) => item.summary),
      })
      return jsonResponse(200, {
        items: state.customerUpdates.map((item) => ({ ...item })),
        page: { next_cursor: null },
      })
    }

    if (
      method === 'GET'
      && path.startsWith('/api/v1/workbench/claims/clm_handoff_journey/events?')
    ) {
      state.eventReads.push({
        revision: state.revision,
        summaries: state.events.map((item) => item.summary),
      })
      return jsonResponse(200, {
        items: state.events.map((item) => ({ ...item })),
        page: { next_cursor: null },
      })
    }

    if (
      method === 'POST'
      && path === '/api/v1/workbench/claims/clm_handoff_journey/handoffs/hnd_journey/resolve'
    ) {
      const request = {
        revision: options.headers['If-Match'],
        idempotencyKey: options.headers['Idempotency-Key'],
        payload: JSON.parse(options.body),
      }
      state.resolveRequests.push(request)
      if (request.revision !== '3' || state.phase !== 'in_progress') {
        return jsonResponse(409, {
          error: {
            code: 'REVISION_CONFLICT',
            message: 'The Claim changed after this page was loaded.',
          },
        })
      }
      state.phase = 'resolved'
      state.revision = 4
      state.customerUpdates.push({
        update_id: 'upd_resolved',
        claim_id: 'clm_handoff_journey',
        created_by: 'stf_demo',
        responsible_party: 'claims_professional',
        summary: request.payload.customer_update.summary,
        related_refs: ['hnd_journey'],
        created_at: '2026-09-14T00:04:00Z',
      })
      state.events.push({
        event_id: 'evt_resolved',
        event_type: 'handoff.resolved',
        actor_id: 'stf_demo',
        summary: 'Staff handoff resolved and Claim returned to the authoritative workflow.',
        source_refs: ['hnd_journey', 'upd_resolved'],
        created_at: '2026-09-14T00:04:00Z',
        resulting_revision: 4,
      })
      return jsonResponse(200, {
        handoff: handoffProjection(state),
        revision: state.revision,
        customer_update: state.customerUpdates.at(-1),
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

describe('WorkbenchPage complete handoff browser/API journey', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    localStorage.clear()
    sessionStorage.clear()
    tabs.tabs = [{
      claimId: 'clm_handoff_journey',
      displayReference: 'NW-HANDOFF',
      section: 'summary',
      sessionId: null,
      draft: 'We have accepted your handoff and are continuing the review.',
    }]
    tabs.activeId = null
    tabs.open.mockImplementation((claim) => {
      tabs.activeId = claim.claim_id
    })
    tabs.activate.mockImplementation((claimId) => {
      tabs.activeId = claimId
    })
    tabs.update.mockImplementation((claimId, patch) => {
      const tab = tabs.tabs.find((item) => item.claimId === claimId)
      if (tab) Object.assign(tab, patch)
    })
  })

  afterEach(() => {
    vi.unstubAllGlobals()
    vi.restoreAllMocks()
  })

  it.each(['motor', 'home', 'contents'])(
    'opens, accepts, communicates, and resolves the %s support handoff',
    async (family) => {
    const { fetchMock, state } = createHandoffJourneyService(family)
    vi.stubGlobal('fetch', fetchMock)
    const user = userEvent.setup()
    renderJourney()

    await user.click(await screen.findByText('NW-HANDOFF'))
    expect(await screen.findByRole('heading', { name: 'Journey Claimant' })).toBeVisible()
    expect(screen.getByRole('heading', { name: 'Accept Claim' })).toBeVisible()

    await user.click(screen.getByRole('button', { name: 'Review acceptance' }))
    await user.click(screen.getByRole('button', { name: 'Confirm Accept Claim' }))

    await waitFor(() => {
      expect(state.acceptRequests).toHaveLength(1)
      expect(state.acceptRequests[0]).toMatchObject({
        revision: '1',
        payload: {},
      })
      expect(screen.getByText('Revision 2')).toBeVisible()
    })
    expect(state.acceptRequests[0].idempotencyKey).toBeTruthy()
    expect(state.handoffReads.some((read) => read.status === 'accepted')).toBe(true)

    await user.click(await screen.findByRole('button', { name: 'Open conversation' }))
    expect(await screen.findByText('Please help me continue this claim.')).toBeVisible()
    expect(screen.getByLabelText('Reply to claimant')).toHaveValue(
      'We have accepted your handoff and are continuing the review.',
    )

    await user.click(screen.getByRole('button', { name: 'Send message' }))

    await waitFor(() => {
      expect(state.messageRequests).toHaveLength(1)
      expect(state.messageRequests[0]).toMatchObject({
        revision: '2',
        payload: {
          content: {
            type: 'text',
            text: 'We have accepted your handoff and are continuing the review.',
          },
        },
      })
    })
    expect(state.messageRequests[0].idempotencyKey).toBeTruthy()
    expect(await screen.findByText(
      'We have accepted your handoff and are continuing the review.',
    )).toBeVisible()
    await waitFor(() => expect(screen.getByText('Revision 3')).toBeVisible())

    await user.click(screen.getByRole('tab', { name: 'Overview' }))
    await user.click(await screen.findByRole('button', { name: 'Open work activity' }))
    await user.click(await screen.findByRole('button', { name: 'Record resolution' }))

    await user.type(
      screen.getByLabelText('Internal result summary'),
      'Staff support completed after reviewing the claimant context.',
    )
    await user.type(
      screen.getByLabelText('Claimant update'),
      'Your staff handoff is resolved and your claim can continue.',
    )
    await user.click(screen.getByRole('button', { name: 'Resolve handoff' }))

    await waitFor(() => {
      expect(state.resolveRequests).toHaveLength(1)
      expect(state.resolveRequests[0]).toMatchObject({
        revision: '3',
        payload: {
          result: {
            outcome: 'support_completed',
            reason_codes: ['SUPPORT_NEED_MET'],
            source_refs: ['msg_claimant_initial'],
            summary: 'Staff support completed after reviewing the claimant context.',
          },
          state_changes: [],
          customer_update: {
            responsible_party: 'claims_professional',
            related_refs: ['hnd_journey'],
            summary: 'Your staff handoff is resolved and your claim can continue.',
          },
        },
      })
      expect(screen.getByText('Revision 4')).toBeVisible()
    })
    expect(state.resolveRequests[0].idempotencyKey).toBeTruthy()

    expect(await screen.findByText(
      'Your staff handoff is resolved and your claim can continue.',
    )).toBeVisible()
    expect(await screen.findByText(
      'Staff handoff resolved and Claim returned to the authoritative workflow.',
    )).toBeVisible()

    await waitFor(() => {
      expect(state.handoffReads.at(-1)).toMatchObject({
        status: 'resolved',
        revision: 4,
      })
      expect(state.queueReads.at(-1)).toMatchObject({
        revision: 4,
        workflow_state: 'ready_for_next',
        phase: 'resolved',
      })
      expect(state.customerUpdateReads.at(-1).summaries).toContain(
        'Your staff handoff is resolved and your claim can continue.',
      )
      expect(state.eventReads.at(-1).summaries).toContain(
        'Staff handoff resolved and Claim returned to the authoritative workflow.',
      )
    })
  },
  )
})
