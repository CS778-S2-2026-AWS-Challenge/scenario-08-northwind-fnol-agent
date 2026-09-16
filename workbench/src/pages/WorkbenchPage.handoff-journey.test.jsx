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

const ACTION_CONFIRMATIONS = {
  'human.accept_handoff': 'Accepting this Claim makes you responsible for the current handoff.',
  'conversation.send_claimant_message': 'This message will be visible to the claimant.',
  'human.resolve_handoff': 'The recorded outcome will update the shared Claim context.',
}

const STANDARD_FAILURE_CODES = ['ACCESS_DENIED', 'REVISION_CONFLICT', 'VALIDATION_ERROR']
const STANDARD_AUDIT_REQUIREMENTS = [
  'action_code',
  'target_ref',
  'actor_id',
  'resulting_revision',
]

function actionBase(actionCode, targetType, targetRef, revision, label, purpose) {
  return {
    registry_version: '2026-09-15.1',
    action_code: actionCode,
    target_type: targetType,
    target_ref: targetRef,
    label,
    purpose,
    availability: 'confirmation_required',
    blocked_reason: null,
    confirmation: { level: 'explicit', message: ACTION_CONFIRMATIONS[actionCode] },
    expected_effects: [],
    claimant_visible_effects: [],
    failure_codes: STANDARD_FAILURE_CODES,
    audit_requirements: STANDARD_AUDIT_REQUIREMENTS,
    source_refs: ['hnd_journey'],
    inputs: [],
    payload_defaults: {},
    result_state: 'awaiting_input',
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
      required_when: null,
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
        required_when: null,
        choices: [],
      },
      {
        field_code: 'customer_update.summary',
        label: 'Claimant update',
        control: 'textarea',
        required: true,
        required_when: null,
        choices: [],
      },
    ],
    payload_defaults: {
      result: {
        outcome: 'support_completed',
        reason_codes: ['SUPPORT_NEED_MET'],
        source_refs: ['msg_claimant_initial'],
      },
      state_changes: [
        { path: 'claim_state.workflow_state', to: 'ready_for_next' },
        { path: 'claim_state.next_action', to: 'PROCEED' },
      ],
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
      summary: 'Incident requiring staff assistance.',
    },
    lifecycle_state: resolved ? 'ready_to_create' : 'staff_support',
    workflow_state: resolved ? 'ready_for_next' : 'professional_review',
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
      workflow_state: resolved ? 'ready_for_next' : 'professional_review',
      next_action: resolved ? 'PROCEED' : 'HANDOFF',
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
      activity: { status: 'available', total: activityEvents(state).length, needs_attention: 0 },
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
      incident_summary: 'Incident requiring staff assistance.',
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
    resume_workflow_state: 'ready_for_next',
    resume_next_action: 'PROCEED',
  }
}

function claimantMessage() {
  return {
    message_id: 'msg_claimant_initial',
    claim_id: 'clm_handoff_journey',
    session_id: 'ses_journey',
    actor: 'claimant',
    visibility: 'shared',
    content: { type: 'text', text: 'Please help me continue this claim.' },
    created_at: '2026-09-14T00:00:00Z',
  }
}

function activityEvents(state) {
  const handoff = handoffProjection(state)
  const events = [
    {
      event_id: 'clm_handoff_journey:created',
      event_type: 'claim.created',
      actor_id: null,
      summary: 'Claim context created.',
      source_refs: ['clm_handoff_journey'],
      created_at: '2026-09-14T00:00:00Z',
      resulting_revision: 1,
    },
    ...state.messages.map((message) => ({
      event_id: message.message_id,
      event_type: 'message.appended',
      actor_id: message.actor,
      summary: `${message.actor === 'staff' ? 'Staff' : 'Claimant'} message recorded.`,
      source_refs: [message.message_id, message.session_id],
      created_at: message.created_at,
      resulting_revision: null,
    })),
    {
      event_id: handoff.handoff_id,
      event_type: `handoff.${handoff.status}`,
      actor_id: handoff.assigned_to,
      summary: handoff.reason,
      source_refs: [handoff.handoff_id],
      created_at: handoff.resolved_at || handoff.accepted_at || handoff.created_at,
      resulting_revision: null,
    },
    ...state.customerUpdates.map((update) => ({
      event_id: update.update_id,
      event_type: 'customer_update.recorded',
      actor_id: update.created_by,
      summary: update.summary,
      source_refs: [update.update_id, ...update.related_refs],
      created_at: update.created_at,
      resulting_revision: null,
    })),
  ]
  return events.sort((left, right) => (
    right.created_at.localeCompare(left.created_at)
    || right.event_id.localeCompare(left.event_id)
  ))
}

function createHandoffJourneyService(family) {
  const state = {
    family,
    revision: 1,
    phase: 'queued',
    messages: [claimantMessage()],
    customerUpdates: [],
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
      state.claimReads.push({
        revision: detail.revision,
        phase: state.phase,
        family: detail.incident.family,
        lifecycle_state: detail.lifecycle_state,
        workflow_state: detail.workflow_state,
        next_action: detail.claim_state.next_action,
      })
      return jsonResponse(200, detail)
    }

    if (
      method === 'GET'
      && path.startsWith('/api/v1/workbench/claims/clm_handoff_journey/handoffs?')
    ) {
      const handoff = handoffProjection(state)
      state.handoffReads.push({
        status: handoff.status,
        revision: state.revision,
        resume_workflow_state: handoff.resume_workflow_state,
        resume_next_action: handoff.resume_next_action,
      })
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
        claim_id: 'clm_handoff_journey',
        session_id: 'ses_journey',
        actor: 'staff',
        visibility: 'shared',
        content: request.payload.content,
        created_at: '2026-09-14T00:03:00Z',
      }
      state.messages.push(message)
      state.phase = 'in_progress'
      state.revision = 3
      return jsonResponse(200, {
        claim_id: 'clm_handoff_journey',
        session_id: 'ses_journey',
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
      const events = activityEvents(state)
      state.eventReads.push({
        revision: state.revision,
        items: events.map((item) => ({
          event_type: item.event_type,
          summary: item.summary,
          source_refs: item.source_refs,
        })),
      })
      return jsonResponse(200, {
        items: events,
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
    'opens, accepts, communicates, resolves, and restores the %s authoritative staff journey',
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
      expect(state.acceptRequests[0].revision).toBe('1')
      expect(state.acceptRequests[0].payload).toEqual({})
      expect(screen.getByText('Revision 2')).toBeVisible()
    })
    expect(state.acceptRequests[0].idempotencyKey).toBeTruthy()
    expect(state.handoffReads.some((read) => read.status === 'accepted')).toBe(true)

    await user.click(await screen.findByRole('button', { name: 'Open conversation' }))
    expect(await screen.findByText('Please help me continue this claim.')).toBeVisible()
    expect(screen.queryByRole('heading', { name: 'Journey Claimant' })).not.toBeInTheDocument()
    expect(screen.getByLabelText('Message to claimant')).toHaveValue(
      'We have accepted your handoff and are continuing the review.',
    )

    await user.click(screen.getByRole('button', { name: 'Send message' }))

    await waitFor(() => {
      expect(state.messageRequests).toHaveLength(1)
      expect(state.messageRequests[0].revision).toBe('2')
      expect(state.messageRequests[0].payload).toEqual({
        content: {
          type: 'text',
          text: 'We have accepted your handoff and are continuing the review.',
        },
      })
    })
    expect(state.messageRequests[0].idempotencyKey).toBeTruthy()
    expect(await screen.findByText(
      'We have accepted your handoff and are continuing the review.',
    )).toBeVisible()
    expect(screen.queryByText('Revision 3')).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Overview' }))
    await waitFor(() => expect(screen.getByText('Revision 3')).toBeVisible())
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
      expect(state.resolveRequests[0].revision).toBe('3')
      expect(state.resolveRequests[0].payload).toEqual({
        result: {
          outcome: 'support_completed',
          reason_codes: ['SUPPORT_NEED_MET'],
          source_refs: ['msg_claimant_initial'],
          summary: 'Staff support completed after reviewing the claimant context.',
        },
        state_changes: [
          { path: 'claim_state.workflow_state', to: 'ready_for_next' },
          { path: 'claim_state.next_action', to: 'PROCEED' },
        ],
        customer_update: {
          responsible_party: 'claims_professional',
          related_refs: ['hnd_journey'],
          summary: 'Your staff handoff is resolved and your claim can continue.',
        },
      })
      expect(screen.getByText('Revision 4')).toBeVisible()
    })
    expect(state.resolveRequests[0].idempotencyKey).toBeTruthy()

    const claimantUpdateCopies = await screen.findAllByText(
      'Your staff handoff is resolved and your claim can continue.',
    )
    expect(claimantUpdateCopies.length).toBeGreaterThanOrEqual(2)
    claimantUpdateCopies.forEach((copy) => expect(copy).toBeVisible())
    await waitFor(() => {
      expect(state.handoffReads.at(-1)).toEqual({
        status: 'resolved',
        revision: 4,
        resume_workflow_state: 'ready_for_next',
        resume_next_action: 'PROCEED',
      })
      expect(state.queueReads.at(-1)).toMatchObject({
        revision: 4,
        workflow_state: 'ready_for_next',
        phase: 'resolved',
      })
      expect(state.customerUpdateReads.at(-1).summaries).toContain(
        'Your staff handoff is resolved and your claim can continue.',
      )
      expect(state.eventReads.at(-1).items).toContainEqual({
        event_type: 'handoff.resolved',
        summary: 'Claimant requested staff support.',
        source_refs: ['hnd_journey'],
      })
      expect(state.eventReads.at(-1).items).toContainEqual({
        event_type: 'customer_update.recorded',
        summary: 'Your staff handoff is resolved and your claim can continue.',
        source_refs: ['upd_resolved', 'hnd_journey'],
      })
      expect(state.claimReads.at(-1)).toMatchObject({
        revision: 4,
        phase: 'resolved',
        family,
        lifecycle_state: 'ready_to_create',
        workflow_state: 'ready_for_next',
        next_action: 'PROCEED',
      })
      expect(state.claimReads).toContainEqual(expect.objectContaining({
        family,
        lifecycle_state: 'staff_support',
        workflow_state: 'professional_review',
        next_action: 'HANDOFF',
      }))
    })
    },
  )
})
