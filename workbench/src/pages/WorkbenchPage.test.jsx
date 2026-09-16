import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes, useLocation, useNavigate } from 'react-router-dom'
import WorkbenchPage from './WorkbenchPage.jsx'

const api = vi.hoisted(() => ({
  claimFilterMetadata: vi.fn(),
  claims: vi.fn(),
  claim: vi.fn(),
  sessionsForTarget: vi.fn(),
  messages: vi.fn(),
  pendingMessageDelivery: vi.fn(),
  confirmMessageDelivery: vi.fn(),
  conversations: vi.fn(),
  handoffs: vi.fn(),
  collaborationRequests: vi.fn(),
  externalRequests: vi.fn(),
  evidence: vi.fn(),
  workItems: vi.fn(),
  realtimeEvents: vi.fn(),
  acceptHandoff: vi.fn(),
  acceptExternalTaskReview: vi.fn(),
  reconcileExternalTaskResponse: vi.fn(),
  reopenClaim: vi.fn(),
}))

const tabs = vi.hoisted(() => ({
  tabs: [],
  activeId: null,
  open: vi.fn(),
  activate: vi.fn(),
  close: vi.fn(),
  update: vi.fn(),
}))

const staffAgent = vi.hoisted(() => ({
  onBusinessActionExecuted: null,
}))

const externalActionTracker = vi.hoisted(() => ({
  lastPromise: null,
}))

vi.mock('../api.js', () => ({ workbenchApi: api }))
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
vi.mock('../components/ClaimWorkspace.jsx', () => ({
  default: ({ detail, resources, externalActionNotices = [], onAccept, onReopen, onExternalTaskAction, onRetryExternalActionContext, onRetry }) => <div>
    {detail && <output data-testid="claim-revision">Claim revision {detail.revision}</output>}
    {resources.handoffs?.error && <p>Handoff context unavailable</p>}
    {resources.externalRequests?.error && <p>External context unavailable</p>}
    {externalActionNotices.map((notice) => (
      <div role="alert" key={`${notice.claimId}:${notice.taskId}`}>
        <p>{notice.message}</p>
        <p>{notice.taskId}</p>
        <button type="button" disabled={notice.recovering} onClick={() => onRetryExternalActionContext(notice.taskId)}>
          Retry external readback
        </button>
      </div>
    ))}
    <button type="button" onClick={onRetry}>Test claim refresh</button>
    {detail?.work_summary?.primary_action_code === 'claim.reopen' && <button type="button" onClick={() => onReopen(detail.allowed_actions[0], { reason: 'New material received.' }, 'reopen-route-key').catch(() => {})}>Test projected reopen</button>}
    {detail?.work_summary?.primary_action_code === 'human.accept_handoff' && <button type="button" onClick={() => onAccept({ handoff_id: 'hnd_1' }).catch(() => {})}>Test projected accept</button>}
    {detail?.work_summary?.primary_action_code?.startsWith('external.') && !externalActionNotices.length && <button type="button" onClick={() => {
      const promise = onExternalTaskAction(detail.allowed_actions[0], {})
      externalActionTracker.lastPromise = promise
      promise.catch(() => {})
    }}>Test projected external action</button>}
  </div>,
}))
vi.mock('../components/StaffAgent.jsx', () => ({
  default: ({ open, requestedSessionId, onBusinessActionExecuted }) => {
    staffAgent.onBusinessActionExecuted = onBusinessActionExecuted
    return open && (
      <output data-testid="staff-agent-state">
        {requestedSessionId ? `Restoring ${requestedSessionId}` : 'New session model'}
      </output>
    )
  },
}))

const metadata = {
  views: [
    { value: 'all', label: 'All active work', group: 'overview' },
    { value: 'processing', label: 'Processing', group: 'active' },
    { value: 'waiting_user', label: 'Waiting for claimant', group: 'active' },
    { value: 'waiting_material', label: 'Waiting for material', group: 'active' },
    { value: 'waiting_third_party', label: 'Waiting for third party', group: 'active' },
    { value: 'completed', label: 'Completed', group: 'terminal' },
    { value: 'abandoned', label: 'Abandoned', group: 'terminal' },
    { value: 'closed', label: 'Closed', group: 'terminal' },
    { value: 'urgent', label: 'Urgent', group: 'operational' },
  ],
  workflow_states: [{ value: 'collecting', label: 'Collecting' }],
  priorities: [{ value: 'routine', label: 'Routine' }],
  tags: [],
  tag_registry_version: '0.3',
}

function externalTaskPage(taskId, status, claimId = 'clm_route_1') {
  return {
    items: [{
      task: { task_id: taskId, claim_id: claimId, status },
      lifecycle: {},
    }],
    page: { next_cursor: null },
    status: 'available',
  }
}

function reviewWorkAction(taskId, actionId, revision) {
  return {
    action_code: 'work_item.update',
    target_type: 'staff_action',
    target_ref: actionId,
    availability: 'confirmation_required',
    based_on_revision: revision,
    source_refs: [taskId],
  }
}

const claim = {
  claim_id: 'clm_route_1',
  revision: 1,
  display_reference: 'NW-900',
  claimant: { customer_id: 'cus_demo' },
  incident: { family: 'motor', summary: 'Synthetic routing test.' },
  lifecycle_state: 'waiting_customer',
  workflow_state: 'awaiting_evidence',
  ownership: { state: 'unassigned', current_staff_access: 'read_only' },
  priority_projection: { level: 'routine' },
  work_summary: { queue_key: 'waiting_user', current_work_item: null },
  allowed_actions: [],
  tags: [],
  updated_at: '2026-09-09T12:00:00Z',
}

const agentConversationSummary = {
  conversation_id: 'staff_agent:sas_evidence',
  kind: 'staff_agent',
  session_id: 'sas_evidence',
  status: 'active',
  title: 'Evidence review',
  summary: 'Police report is still pending.',
  updated_at: '2026-09-14T02:00:00Z',
}

const availableCounts = {
  status: 'available',
  items: metadata.views.map((view) => ({ view: view.value, count: 1 })),
  limitation: null,
}

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname}{location.search}</output>
}

function NavigationProbe() {
  const navigate = useNavigate()
  return (
    <>
      <button type="button" onClick={() => navigate('/workbench/claims/clm_route_1')}>Navigate Claim A</button>
      <button type="button" onClick={() => navigate('/workbench/claims/clm_route_2')}>Navigate Claim B</button>
    </>
  )
}

function renderPage(initialEntry) {
  const page = <><WorkbenchPage /><LocationProbe /><NavigationProbe /></>
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/workbench" element={page} />
        <Route path="/workbench/conversations" element={page} />
        <Route path="/workbench/agent/sessions/:agentSessionId" element={page} />
        <Route path="/workbench/claims/:claimId" element={page} />
        <Route path="/workbench/claims/:claimId/:section" element={page} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('WorkbenchPage queue routing', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    tabs.tabs = []
    tabs.activeId = null
    staffAgent.onBusinessActionExecuted = null
    externalActionTracker.lastPromise = null
    api.claimFilterMetadata.mockResolvedValue(metadata)
    api.claims.mockResolvedValue({
      items: [claim],
      page: { next_cursor: null },
      view_counts: availableCounts,
    })
    api.claim.mockResolvedValue(claim)
    api.sessionsForTarget.mockResolvedValue({
      items: [{ session_id: 'ses_saved' }],
      page: { next_cursor: null },
      resolved_session: { session_id: 'ses_saved' },
    })
    api.messages.mockResolvedValue({ items: [], page: { next_cursor: null } })
    api.pendingMessageDelivery.mockReturnValue(null)
    api.confirmMessageDelivery.mockReturnValue(null)
    api.conversations.mockResolvedValue({ items: [], page: { next_cursor: null } })
    api.sessionsForTarget.mockResolvedValue({
      items: [],
      resolved_session: null,
      page: { next_cursor: null },
    })
    api.messages.mockResolvedValue({ items: [], page: { next_cursor: null } })
    api.handoffs.mockResolvedValue({ items: [], page: { next_cursor: null } })
    api.collaborationRequests.mockResolvedValue({ items: [], page: { next_cursor: null } })
    api.externalRequests.mockResolvedValue({ items: [], page: { next_cursor: null }, status: 'available' })
    api.evidence.mockResolvedValue({ items: [], page: { next_cursor: null }, status: 'available' })
    api.workItems.mockResolvedValue({ items: [], page: { next_cursor: null }, status: 'available' })
    api.realtimeEvents.mockImplementation((_token, { signal }) => (
      new Promise((resolve) => {
        signal.addEventListener('abort', resolve, { once: true })
      })
    ))
  })

  it('restores the persisted active Claim section and claimant session from the Workbench root', async () => {
    tabs.tabs = [{
      claimId: 'clm_route_1',
      label: 'NW-900',
      section: 'conversation',
      sessionId: 'ses_saved',
      draft: 'Saved claimant reply',
      expandedRecords: [],
      pendingAction: null,
    }]
    tabs.activeId = 'clm_route_1'

    renderPage('/workbench?view=waiting_user&search=NW-900')

    await waitFor(() => {
      const location = screen.getByTestId('location').textContent
      expect(location).toContain('/workbench/claims/clm_route_1/conversation?')
      expect(location).toContain('view=waiting_user')
      expect(location).toContain('search=NW-900')
      expect(location).toContain('session=ses_saved')
    })
    await waitFor(() => expect(api.claim).toHaveBeenCalledWith('staff-token', 'clm_route_1'))
    await waitFor(() => expect(api.sessionsForTarget).toHaveBeenCalledWith(
      'staff-token',
      'clm_route_1',
      'ses_saved',
    ))
  })

  it('keeps the bare Workbench queue when no persisted active Claim exists', async () => {
    renderPage('/workbench')

    expect(await screen.findByText('NW-900')).toBeInTheDocument()
    expect(screen.getByTestId('location')).toHaveTextContent('/workbench')
    expect(api.claim).not.toHaveBeenCalled()
  })

  it('does not override an explicit Claim route with a different persisted active tab', async () => {
    tabs.tabs = [{
      claimId: 'clm_old',
      label: 'NW-OLD',
      section: 'conversation',
      sessionId: 'ses_old',
      draft: '',
      expandedRecords: [],
      pendingAction: null,
    }]
    tabs.activeId = 'clm_old'

    renderPage('/workbench/claims/clm_route_1')

    await waitFor(() => expect(api.claim).toHaveBeenCalledWith('staff-token', 'clm_route_1'))
    expect(screen.getByTestId('location')).toHaveTextContent('/workbench/claims/clm_route_1')
    expect(screen.getByTestId('location')).not.toHaveTextContent('clm_old')
  })

  it('preserves an unpublished URL view and does not issue a guessed queue request', async () => {
    const user = userEvent.setup()
    renderPage('/workbench?view=retired_queue&assignee_id=unassigned&next_action=ASK')

    expect(await screen.findByText('This queue view is no longer available')).toBeInTheDocument()
    expect(api.claims).not.toHaveBeenCalled()
    expect(screen.getByTestId('location')).toHaveTextContent(
      '/workbench?view=retired_queue&assignee_id=unassigned&next_action=ASK',
    )

    await user.click(screen.getByRole('button', { name: 'Open all active work' }))

    await waitFor(() => expect(api.claims).toHaveBeenCalledOnce())
    expect(api.claims).toHaveBeenCalledWith(
      'staff-token',
      expect.objectContaining({ assignee_id: 'unassigned', next_action: 'ASK' }),
    )
    expect(screen.getByTestId('location')).toHaveTextContent(
      '/workbench?assignee_id=unassigned&next_action=ASK',
    )
  })

  it('preserves the published queue and every non-view filter on Claim navigation', async () => {
    const user = userEvent.setup()
    renderPage(
      '/workbench?view=waiting_user&workflow_state=collecting&priority=routine&assignee_id=unassigned&next_action=ASK&search=NW-900&updated_before=2026-09-10T00%3A00%3A00Z&updated_after=2026-09-09T00%3A00%3A00Z',
    )

    await user.click(await screen.findByText('NW-900'))

    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent('/workbench/claims/clm_route_1?')
    })
    const location = screen.getByTestId('location').textContent
    expect(location).toContain('view=waiting_user')
    expect(location).toContain('workflow_state=collecting')
    expect(location).toContain('priority=routine')
    expect(location).toContain('assignee_id=unassigned')
    expect(location).toContain('next_action=ASK')
    expect(location).toContain('search=NW-900')
    expect(location).toContain('updated_before=2026-09-10T00%3A00%3A00Z')
    expect(location).toContain('updated_after=2026-09-09T00%3A00%3A00Z')
  })

  it('preserves queue filters when an unknown Claim section is corrected', async () => {
    renderPage('/workbench/claims/clm_route_1/retired-section?view=waiting_user&assignee_id=unassigned')

    await waitFor(() => {
      expect(screen.getByTestId('location')).toHaveTextContent(
        '/workbench/claims/clm_route_1?view=waiting_user&assignee_id=unassigned',
      )
    })
  })

  it('returns a reopened Claim to the exact server-projected queue and reports its revision', async () => {
    const user = userEvent.setup()
    const terminal = {
      ...claim,
      revision: 7,
      terminal_disposition: {
        value: 'closed', reason_code: 'AUTHORISED_CLOSURE', source_refs: ['evt_closed_1'], recorded_at: '2026-09-09T12:00:00Z', recorded_revision: 7,
      },
      work_summary: {
        queue_key: 'closed',
        primary_action_code: 'claim.reopen',
        primary_action_target_ref: 'clm_route_1',
      },
      allowed_actions: [{
        action_code: 'claim.reopen', target_type: 'claim', target_ref: 'clm_route_1', availability: 'confirmation_required', based_on_revision: 7,
      }],
    }
    const reopened = {
      ...terminal,
      revision: 8,
      terminal_disposition: null,
      work_summary: { queue_key: 'processing', primary_action_code: null, primary_action_target_ref: null },
      allowed_actions: [],
    }
    api.claim.mockResolvedValueOnce(terminal).mockResolvedValue(reopened)
    api.reopenClaim.mockResolvedValue(reopened)
    api.claims.mockImplementation((token, filters) => Promise.resolve({
      items: filters.view === 'closed' ? [terminal] : [reopened],
      page: { next_cursor: null },
      view_counts: availableCounts,
    }))

    renderPage('/workbench/claims/clm_route_1?view=closed')
    await user.click(await screen.findByRole('button', { name: 'Test projected reopen' }))

    await waitFor(() => expect(api.reopenClaim).toHaveBeenCalledWith(
      'staff-token',
      'clm_route_1',
      7,
      { reason: 'New material received.' },
      'reopen-route-key',
    ))
    expect(api.claim).toHaveBeenCalledTimes(2)
    expect(await screen.findByText(/reopened at revision 8.*moved to Processing/i)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(
      '/workbench/claims/clm_route_1?view=processing',
    ))
    expect(api.claims).toHaveBeenLastCalledWith(
      'staff-token',
      expect.objectContaining({ view: 'processing' }),
    )
  })

  it('reloads and explains the latest projection after a stale reopen is rejected', async () => {
    const user = userEvent.setup()
    const terminal = {
      ...claim,
      revision: 7,
      terminal_disposition: { value: 'closed', reason_code: 'AUTHORISED_CLOSURE', source_refs: ['evt_closed_1'], recorded_at: '2026-09-09T12:00:00Z', recorded_revision: 7 },
      work_summary: { queue_key: 'closed', primary_action_code: 'claim.reopen', primary_action_target_ref: 'clm_route_1' },
      allowed_actions: [{ action_code: 'claim.reopen', target_type: 'claim', target_ref: 'clm_route_1', availability: 'confirmation_required', based_on_revision: 7 }],
    }
    const latest = {
      ...terminal,
      revision: 8,
      allowed_actions: [{ ...terminal.allowed_actions[0], based_on_revision: 8 }],
    }
    api.claim.mockResolvedValueOnce(terminal).mockResolvedValue(latest)
    api.reopenClaim.mockRejectedValue(Object.assign(new Error('Revision mismatch.'), { code: 'REVISION_CONFLICT' }))

    renderPage('/workbench/claims/clm_route_1?view=closed')
    await user.click(await screen.findByRole('button', { name: 'Test projected reopen' }))

    const alert = await screen.findByRole('alert')
    expect(alert).toHaveTextContent(/was not reopened.*loaded revision was stale/i)
    expect(alert).toHaveTextContent(/revision 8.*review it and try again/i)
    expect(api.claim).toHaveBeenCalledTimes(2)
  })

  it('keeps the core Claim readable when optional action context is unavailable', async () => {
    api.handoffs.mockRejectedValueOnce(Object.assign(
      new Error('Handoff source timed out.'),
      { requestId: 'req_handoff_1' },
    ))

    renderPage('/workbench/claims/clm_route_1')

    expect(await screen.findByTestId('claim-revision')).toHaveTextContent('Claim revision 1')
    expect(await screen.findByText('Handoff context unavailable')).toBeInTheDocument()
  })

  it('keeps the existing Staff Agent open and resume route for a history selection', async () => {
    const user = userEvent.setup()
    api.conversations.mockResolvedValue({
      items: [agentConversationSummary],
      page: { next_cursor: null },
    })
    renderPage('/workbench/conversations')

    await user.click(await screen.findByRole('button', { name: /Evidence review/ }))

    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(
      '/workbench/agent/sessions/sas_evidence',
    ))
    expect(screen.getByTestId('staff-agent-state')).toHaveTextContent('Restoring sas_evidence')
  })

  it('takes over a waiting assistance request with its exact projected target and revision', async () => {
    const user = userEvent.setup()
    let accepted = false
    const acceptAction = {
      action_code: 'human.accept_handoff',
      target_type: 'handoff',
      target_ref: 'hnd_help',
      availability: 'confirmation_required',
      based_on_revision: 4,
      confirmation: { message: 'Accepting this Claim makes you responsible for the current handoff.' },
    }
    const waitingClaim = {
      ...claim,
      claim_id: 'clm_help',
      revision: 4,
      display_reference: 'clm_help',
      incident: { family: 'motor', summary: 'Vehicle was hit while parked.' },
      lifecycle_state: 'staff_support',
      ownership: { state: 'unassigned', current_staff_access: 'read_only' },
      work_summary: {
        queue_key: 'processing',
        primary_action_code: 'human.accept_handoff',
        primary_action_target_ref: 'hnd_help',
        unread_claimant_messages: 0,
      },
      integration_summary: { claim_creation_status: null },
    }
    const waitingDetail = {
      ...waitingClaim,
      active_session_id: 'ses_help',
      customer_next_step: { responsible_party: 'claims_professional' },
      allowed_actions: [acceptAction],
    }
    const acceptedDetail = {
      ...waitingDetail,
      revision: 5,
      ownership: {
        state: 'assigned',
        current_staff_access: 'primary',
        primary_assignee: { staff_id: 'stf_demo' },
      },
      work_summary: {
        ...waitingDetail.work_summary,
        primary_action_code: 'conversation.send_claimant_message',
        primary_action_target_ref: 'ses_help',
      },
      allowed_actions: [],
    }
    const waitingHandoff = {
      handoff_id: 'hnd_help',
      support_need: 'human_requested',
      status: 'queued',
      reason: 'Customer requested staff assistance.',
      requested_action: 'Help the customer continue.',
      packet: { incident_summary: 'Parked vehicle damage.' },
      created_at: '2026-09-14T02:00:00Z',
    }
    const acceptedHandoff = {
      ...waitingHandoff,
      status: 'accepted',
      assigned_to: 'stf_demo',
      accepted_at: '2026-09-14T02:02:00Z',
    }
    api.claims.mockImplementation((token, filters = {}) => Promise.resolve({
      items: filters.view === 'human_requests' && !accepted ? [waitingClaim] : [],
      page: { next_cursor: null },
      view_counts: availableCounts,
    }))
    api.conversations.mockImplementation(() => Promise.resolve({
      items: accepted ? [{
        conversation_id: 'claim:ses_help',
        kind: 'claim',
        claim_id: 'clm_help',
        display_reference: 'clm_help',
        session_id: 'ses_help',
        title: 'Claim clm_help',
        summary: 'Parked vehicle damage.',
        status: 'active',
      }] : [],
      page: { next_cursor: null },
    }))
    api.claim.mockImplementation(() => Promise.resolve(accepted ? acceptedDetail : waitingDetail))
    api.handoffs.mockImplementation(() => Promise.resolve({
      items: [accepted ? acceptedHandoff : waitingHandoff],
      page: { next_cursor: null },
    }))
    api.acceptHandoff.mockImplementation(() => {
      accepted = true
      return Promise.resolve({ revision: 5, handoff: acceptedHandoff })
    })
    api.sessionsForTarget.mockResolvedValue({
      items: [{ session_id: 'ses_help' }],
      resolved_session: { session_id: 'ses_help' },
      page: { next_cursor: null },
    })

    renderPage('/workbench/conversations')
    await user.click(await screen.findByRole('button', { name: 'Take over' }))
    await user.click(screen.getByRole('button', { name: 'Confirm take over' }))

    await waitFor(() => expect(api.acceptHandoff).toHaveBeenCalledWith(
      'staff-token',
      'clm_help',
      'hnd_help',
      4,
    ))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent(
      '/workbench/claims/clm_help/conversation?session=ses_help',
    ))
  })

  it('removes the previous queue rows while a changed filter fails to load', async () => {
    const user = userEvent.setup()
    renderPage('/workbench')
    expect(await screen.findByText('NW-900')).toBeInTheDocument()
    api.claims.mockRejectedValueOnce(Object.assign(
      new Error('Filtered queue timed out.'),
      { requestId: 'req_filtered_1' },
    ))

    await user.selectOptions(screen.getByLabelText('Current work'), 'processing')

    expect(await screen.findByRole('alert')).toHaveTextContent('req_filtered_1')
    expect(screen.queryByText('NW-900')).not.toBeInTheDocument()
  })

  it('reloads the authoritative Claim after a controlled action conflict', async () => {
    const user = userEvent.setup()
    const acceptAction = {
      action_code: 'human.accept_handoff', target_type: 'handoff', target_ref: 'hnd_1', availability: 'confirmation_required', based_on_revision: 1,
    }
    const actionable = {
      ...claim,
      work_summary: { ...claim.work_summary, primary_action_code: acceptAction.action_code, primary_action_target_ref: acceptAction.target_ref },
      allowed_actions: [acceptAction],
    }
    const latest = {
      ...actionable,
      revision: 2,
      allowed_actions: [{ ...acceptAction, based_on_revision: 2 }],
    }
    api.claim.mockResolvedValueOnce(actionable).mockResolvedValue(latest)
    api.acceptHandoff.mockRejectedValue(Object.assign(
      new Error('Revision mismatch.'),
      { status: 409, code: 'REVISION_CONFLICT', requestId: 'req_accept_1' },
    ))

    renderPage('/workbench/claims/clm_route_1')
    await user.click(await screen.findByRole('button', { name: 'Test projected accept' }))

    await waitFor(() => expect(api.acceptHandoff).toHaveBeenCalledWith(
      'staff-token',
      'clm_route_1',
      'hnd_1',
      1,
    ))
    await waitFor(() => expect(screen.getByTestId('claim-revision')).toHaveTextContent('Claim revision 2'))
    expect(api.claim).toHaveBeenCalledTimes(2)
  })

  it('executes an exact projected external review and reads back Claim and external-service state before settling', async () => {
    const user = userEvent.setup()
    const externalAction = {
      action_code: 'external.accept_review',
      target_type: 'external_task',
      target_ref: 'tsk_assessor_1',
      label: 'Accept external-service review',
      availability: 'confirmation_required',
      based_on_revision: 4,
      inputs: [],
    }
    const actionable = {
      ...claim,
      revision: 4,
      work_summary: {
        ...claim.work_summary,
        primary_action_code: externalAction.action_code,
        primary_action_target_ref: externalAction.target_ref,
      },
      allowed_actions: [externalAction],
    }
    const workAction = reviewWorkAction('tsk_assessor_1', 'act_external_review_1', 5)
    const latest = {
      ...actionable,
      revision: 5,
      work_summary: {
        ...actionable.work_summary,
        primary_action_code: workAction.action_code,
        primary_action_target_ref: workAction.target_ref,
      },
      allowed_actions: [workAction],
    }
    api.claim.mockResolvedValueOnce(actionable).mockResolvedValue(latest)
    api.acceptExternalTaskReview.mockResolvedValue({
      revision: 5,
      action: {
        action_id: 'act_external_review_1',
        source_refs: ['tsk_assessor_1'],
      },
    })
    api.externalRequests.mockResolvedValue(
      externalTaskPage('tsk_assessor_1', 'terminal_failure'),
    )

    renderPage('/workbench/claims/clm_route_1')
    await user.click(await screen.findByRole('button', { name: 'Test projected external action' }))

    await waitFor(() => expect(api.acceptExternalTaskReview).toHaveBeenCalledWith(
      'staff-token',
      'clm_route_1',
      'tsk_assessor_1',
      4,
      {},
    ))
    await waitFor(() => expect(screen.getByTestId('claim-revision')).toHaveTextContent('Claim revision 5'))
    await waitFor(() => expect(api.externalRequests).toHaveBeenCalledWith('staff-token', 'clm_route_1'))
    await expect(externalActionTracker.lastPromise).resolves.toBeUndefined()
    expect(api.claim).toHaveBeenCalledTimes(2)
  })

  it('keeps a successful external mutation unsettled when Claim readback returns an older HTTP 200 projection', async () => {
    const user = userEvent.setup()
    const externalAction = {
      action_code: 'external.accept_review',
      target_type: 'external_task',
      target_ref: 'tsk_assessor_old_claim',
      label: 'Accept external-service review',
      availability: 'confirmation_required',
      based_on_revision: 4,
      inputs: [],
    }
    const actionable = {
      ...claim,
      revision: 4,
      work_summary: {
        ...claim.work_summary,
        primary_action_code: externalAction.action_code,
        primary_action_target_ref: externalAction.target_ref,
      },
      allowed_actions: [externalAction],
    }
    api.claim.mockResolvedValue(actionable)
    api.acceptExternalTaskReview.mockResolvedValue({
      revision: 5,
      action: {
        action_id: 'act_external_review_old_claim',
        source_refs: ['tsk_assessor_old_claim'],
      },
    })
    api.externalRequests.mockResolvedValue(
      externalTaskPage('tsk_assessor_old_claim', 'terminal_failure'),
    )

    renderPage('/workbench/claims/clm_route_1')
    await user.click(await screen.findByRole('button', { name: 'Test projected external action' }))

    await expect(externalActionTracker.lastPromise).rejects.toThrow(
      /authoritative readback did not complete.*outcome is not confirmed/i,
    )
    expect(api.acceptExternalTaskReview).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('claim-revision')).toHaveTextContent('Claim revision 4')
    expect(await screen.findByRole('alert')).toHaveTextContent('tsk_assessor_old_claim')
  })

  it('keeps accept-review unknown when a successful External Services HTTP 200 omits the target task', async () => {
    const user = userEvent.setup()
    const externalAction = {
      action_code: 'external.accept_review',
      target_type: 'external_task',
      target_ref: 'tsk_assessor_missing',
      label: 'Accept external-service review',
      availability: 'confirmation_required',
      based_on_revision: 4,
      inputs: [],
    }
    const actionable = {
      ...claim,
      revision: 4,
      work_summary: {
        ...claim.work_summary,
        primary_action_code: externalAction.action_code,
        primary_action_target_ref: externalAction.target_ref,
      },
      allowed_actions: [externalAction],
    }
    const workAction = reviewWorkAction(
      'tsk_assessor_missing',
      'act_external_review_missing',
      5,
    )
    const latest = {
      ...actionable,
      revision: 5,
      work_summary: {
        ...actionable.work_summary,
        primary_action_code: workAction.action_code,
        primary_action_target_ref: workAction.target_ref,
      },
      allowed_actions: [workAction],
    }
    api.claim.mockResolvedValueOnce(actionable).mockResolvedValue(latest)
    api.acceptExternalTaskReview.mockResolvedValue({
      revision: 5,
      action: {
        action_id: 'act_external_review_missing',
        source_refs: ['tsk_assessor_missing'],
      },
    })
    api.externalRequests.mockResolvedValue(
      externalTaskPage('tsk_some_other_task', 'terminal_failure'),
    )

    renderPage('/workbench/claims/clm_route_1')
    await user.click(await screen.findByRole('button', { name: 'Test projected external action' }))

    await expect(externalActionTracker.lastPromise).rejects.toThrow(
      /authoritative readback did not complete.*outcome is not confirmed/i,
    )
    expect(api.acceptExternalTaskReview).toHaveBeenCalledTimes(1)
    expect(await screen.findByRole('alert')).toHaveTextContent('tsk_assessor_missing')
  })

  it('keeps reconciliation unknown when a stale External Services HTTP 200 still reports unknown_outcome', async () => {
    const user = userEvent.setup()
    const externalAction = {
      action_code: 'external.reconcile_response',
      target_type: 'external_task',
      target_ref: 'tsk_assessor_stale_reconcile',
      label: 'Reconcile external outcome',
      availability: 'confirmation_required',
      based_on_revision: 4,
      inputs: [],
    }
    const actionable = {
      ...claim,
      revision: 4,
      work_summary: {
        ...claim.work_summary,
        primary_action_code: externalAction.action_code,
        primary_action_target_ref: externalAction.target_ref,
      },
      allowed_actions: [externalAction],
    }
    const latest = {
      ...actionable,
      revision: 5,
      work_summary: {
        ...actionable.work_summary,
        primary_action_code: null,
        primary_action_target_ref: null,
      },
      allowed_actions: [],
    }
    api.claim.mockResolvedValueOnce(actionable).mockResolvedValue(latest)
    api.reconcileExternalTaskResponse.mockResolvedValue({
      claim_id: 'clm_route_1',
      task_id: 'tsk_assessor_stale_reconcile',
      revision: 5,
      staff_action: {
        action_id: 'act_external_reconcile',
        status: 'completed',
      },
    })
    api.externalRequests.mockResolvedValue(
      externalTaskPage('tsk_assessor_stale_reconcile', 'unknown_outcome'),
    )

    renderPage('/workbench/claims/clm_route_1')
    await user.click(await screen.findByRole('button', { name: 'Test projected external action' }))

    await expect(externalActionTracker.lastPromise).rejects.toThrow(
      /authoritative readback did not complete.*outcome is not confirmed/i,
    )
    expect(api.reconcileExternalTaskResponse).toHaveBeenCalledTimes(1)
    expect(await screen.findByRole('alert')).toHaveTextContent('tsk_assessor_stale_reconcile')
  })

  it('keeps a successful external mutation unsettled when Claim readback fails', async () => {
    const user = userEvent.setup()
    const externalAction = {
      action_code: 'external.accept_review',
      target_type: 'external_task',
      target_ref: 'tsk_assessor_1',
      label: 'Accept external-service review',
      availability: 'confirmation_required',
      based_on_revision: 4,
      inputs: [],
    }
    const actionable = {
      ...claim,
      revision: 4,
      work_summary: {
        ...claim.work_summary,
        primary_action_code: externalAction.action_code,
        primary_action_target_ref: externalAction.target_ref,
      },
      allowed_actions: [externalAction],
    }
    api.claim
      .mockResolvedValueOnce(actionable)
      .mockRejectedValueOnce(Object.assign(
        new Error('Claim readback is unavailable.'),
        { status: 503, code: 'DEPENDENCY_UNAVAILABLE' },
      ))
    api.acceptExternalTaskReview.mockResolvedValue({
      revision: 5,
      action: {
        action_id: 'act_external_review_1',
        source_refs: ['tsk_assessor_1'],
      },
    })
    api.externalRequests.mockResolvedValue(
      externalTaskPage('tsk_assessor_1', 'terminal_failure'),
    )

    renderPage('/workbench/claims/clm_route_1')
    await user.click(await screen.findByRole('button', { name: 'Test projected external action' }))

    await waitFor(() => expect(externalActionTracker.lastPromise).not.toBeNull())
    await expect(externalActionTracker.lastPromise).rejects.toThrow(
      /authoritative readback did not complete.*outcome is not confirmed/i,
    )
    expect(api.acceptExternalTaskReview).toHaveBeenCalledTimes(1)
    expect(screen.getByTestId('claim-revision')).toHaveTextContent('Claim revision 4')
    expect(await screen.findByRole('alert')).toHaveTextContent(/tsk_assessor_1.*may have completed.*outcome is not confirmed/i)
  })

  it('keeps a successful external mutation unsettled when External Services readback fails', async () => {
    const user = userEvent.setup()
    const externalAction = {
      action_code: 'external.accept_review',
      target_type: 'external_task',
      target_ref: 'tsk_assessor_1',
      label: 'Accept external-service review',
      availability: 'confirmation_required',
      based_on_revision: 4,
      inputs: [],
    }
    const actionable = {
      ...claim,
      revision: 4,
      work_summary: {
        ...claim.work_summary,
        primary_action_code: externalAction.action_code,
        primary_action_target_ref: externalAction.target_ref,
      },
      allowed_actions: [externalAction],
    }
    const workAction = reviewWorkAction('tsk_assessor_1', 'act_external_review_1', 5)
    const latest = {
      ...actionable,
      revision: 5,
      work_summary: {
        ...actionable.work_summary,
        primary_action_code: workAction.action_code,
        primary_action_target_ref: workAction.target_ref,
      },
      allowed_actions: [workAction],
    }
    api.claim.mockResolvedValueOnce(actionable).mockResolvedValue(latest)
    api.acceptExternalTaskReview.mockResolvedValue({
      revision: 5,
      action: {
        action_id: 'act_external_review_1',
        source_refs: ['tsk_assessor_1'],
      },
    })
    api.externalRequests.mockRejectedValueOnce(Object.assign(
      new Error('External Services readback is unavailable.'),
      { status: 503, code: 'DEPENDENCY_UNAVAILABLE' },
    ))

    renderPage('/workbench/claims/clm_route_1')
    await user.click(await screen.findByRole('button', { name: 'Test projected external action' }))

    await waitFor(() => expect(externalActionTracker.lastPromise).not.toBeNull())
    await expect(externalActionTracker.lastPromise).rejects.toThrow(
      /authoritative readback did not complete.*outcome is not confirmed/i,
    )
    expect(api.acceptExternalTaskReview).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(screen.getByTestId('claim-revision')).toHaveTextContent('Claim revision 5'))
    await waitFor(() => expect(screen.getByText('External context unavailable')).toBeInTheDocument())
    expect(await screen.findByRole('alert')).toHaveTextContent(/tsk_assessor_1.*may have completed.*outcome is not confirmed/i)
  })

  it('keeps the recovery guard when an authoritative retry is superseded', async () => {
    const user = userEvent.setup()
    const externalAction = {
      action_code: 'external.accept_review',
      target_type: 'external_task',
      target_ref: 'tsk_assessor_superseded',
      label: 'Accept external-service review',
      availability: 'confirmation_required',
      based_on_revision: 4,
      inputs: [],
    }
    const actionable = {
      ...claim,
      revision: 4,
      work_summary: {
        ...claim.work_summary,
        primary_action_code: externalAction.action_code,
        primary_action_target_ref: externalAction.target_ref,
      },
      allowed_actions: [externalAction],
    }
    const staleLatest = {
      ...actionable,
      revision: 5,
      allowed_actions: [{ ...externalAction, based_on_revision: 5 }],
    }
    const recoveredWorkAction = reviewWorkAction(
      'tsk_assessor_superseded',
      'act_external_review_superseded',
      5,
    )
    const settledLatest = {
      ...actionable,
      revision: 5,
      work_summary: {
        ...actionable.work_summary,
        primary_action_code: recoveredWorkAction.action_code,
        primary_action_target_ref: recoveredWorkAction.target_ref,
      },
      allowed_actions: [recoveredWorkAction],
    }

    let resolveRecoveryClaim
    let resolveRecoveryExternal
    const delayedRecoveryClaim = new Promise((resolve) => { resolveRecoveryClaim = resolve })
    const delayedRecoveryExternal = new Promise((resolve) => { resolveRecoveryExternal = resolve })

    api.claim
      .mockResolvedValueOnce(actionable)
      .mockRejectedValueOnce(Object.assign(
        new Error('Claim readback is unavailable.'),
        { status: 503, code: 'DEPENDENCY_UNAVAILABLE' },
      ))
      .mockReturnValueOnce(delayedRecoveryClaim)
      .mockResolvedValueOnce(staleLatest)
      .mockResolvedValueOnce(settledLatest)
    api.externalRequests
      .mockResolvedValueOnce(externalTaskPage('tsk_assessor_superseded', 'terminal_failure'))
      .mockReturnValueOnce(delayedRecoveryExternal)
      .mockResolvedValueOnce(externalTaskPage('tsk_assessor_superseded', 'terminal_failure'))
    api.acceptExternalTaskReview.mockResolvedValue({
      revision: 5,
      action: {
        action_id: 'act_external_review_superseded',
        source_refs: ['tsk_assessor_superseded'],
      },
    })

    renderPage('/workbench/claims/clm_route_1')
    await user.click(await screen.findByRole('button', { name: 'Test projected external action' }))
    await expect(externalActionTracker.lastPromise).rejects.toThrow(/authoritative readback did not complete/i)

    const warning = await screen.findByRole('alert')
    expect(warning).toHaveTextContent('tsk_assessor_superseded')
    expect(screen.queryByRole('button', { name: 'Test projected external action' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Retry external readback' }))
    expect(screen.getByRole('button', { name: 'Retry external readback' })).toBeDisabled()

    await user.click(screen.getByRole('button', { name: 'Test claim refresh' }))
    await waitFor(() => expect(screen.getByTestId('claim-revision')).toHaveTextContent('Claim revision 5'))

    await act(async () => {
      resolveRecoveryClaim(staleLatest)
      resolveRecoveryExternal(externalTaskPage('tsk_assessor_superseded', 'terminal_failure'))
      await Promise.resolve()
    })

    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('tsk_assessor_superseded'))
    expect(screen.queryByRole('button', { name: 'Test projected external action' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Retry external readback' }))
    await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument())
  })

  it('preserves independent unconfirmed external-action guards across Claim tabs', async () => {
    const user = userEvent.setup()
    const actionA = {
      action_code: 'external.accept_review',
      target_type: 'external_task',
      target_ref: 'tsk_claim_a',
      label: 'Accept external-service review A',
      availability: 'confirmation_required',
      based_on_revision: 4,
      inputs: [],
    }
    const actionB = {
      ...actionA,
      target_ref: 'tsk_claim_b',
      label: 'Accept external-service review B',
      based_on_revision: 6,
    }
    const claimA = {
      ...claim,
      claim_id: 'clm_route_1',
      revision: 4,
      display_reference: 'NW-A',
      work_summary: {
        ...claim.work_summary,
        primary_action_code: actionA.action_code,
        primary_action_target_ref: actionA.target_ref,
      },
      allowed_actions: [actionA],
    }
    const claimB = {
      ...claim,
      claim_id: 'clm_route_2',
      revision: 6,
      display_reference: 'NW-B',
      work_summary: {
        ...claim.work_summary,
        primary_action_code: actionB.action_code,
        primary_action_target_ref: actionB.target_ref,
      },
      allowed_actions: [actionB],
    }
    const calls = { clm_route_1: 0, clm_route_2: 0 }
    api.claim.mockImplementation((token, id) => {
      calls[id] += 1
      if (calls[id] === 2) {
        return Promise.reject(Object.assign(
          new Error(`Claim ${id} readback is unavailable.`),
          { status: 503, code: 'DEPENDENCY_UNAVAILABLE' },
        ))
      }
      return Promise.resolve(id === 'clm_route_1' ? claimA : claimB)
    })
    api.acceptExternalTaskReview.mockImplementation((token, id) => Promise.resolve({
      revision: id === 'clm_route_1' ? 5 : 7,
      action: {
        action_id: id === 'clm_route_1' ? 'act_claim_a' : 'act_claim_b',
        source_refs: [id === 'clm_route_1' ? 'tsk_claim_a' : 'tsk_claim_b'],
      },
    }))

    renderPage('/workbench/claims/clm_route_1')
    await user.click(await screen.findByRole('button', { name: 'Test projected external action' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('tsk_claim_a'))

    await user.click(screen.getByRole('button', { name: 'Navigate Claim B' }))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/workbench/claims/clm_route_2'))
    await user.click(await screen.findByRole('button', { name: 'Test projected external action' }))
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('tsk_claim_b'))

    await user.click(screen.getByRole('button', { name: 'Navigate Claim A' }))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/workbench/claims/clm_route_1'))
    expect(await screen.findByRole('alert')).toHaveTextContent('tsk_claim_a')
    expect(screen.getByRole('alert')).not.toHaveTextContent('tsk_claim_b')
    expect(screen.queryByRole('button', { name: 'Test projected external action' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Navigate Claim B' }))
    await waitFor(() => expect(screen.getByTestId('location')).toHaveTextContent('/workbench/claims/clm_route_2'))
    expect(await screen.findByRole('alert')).toHaveTextContent('tsk_claim_b')
    expect(screen.queryByRole('button', { name: 'Test projected external action' })).not.toBeInTheDocument()
  })

  it('reads back external-service state after a stale external action conflict', async () => {
    const user = userEvent.setup()
    const externalAction = {
      action_code: 'external.accept_review',
      target_type: 'external_task',
      target_ref: 'tsk_assessor_1',
      label: 'Accept external-service review',
      availability: 'confirmation_required',
      based_on_revision: 4,
      inputs: [],
    }
    const actionable = {
      ...claim,
      revision: 4,
      work_summary: {
        ...claim.work_summary,
        primary_action_code: externalAction.action_code,
        primary_action_target_ref: externalAction.target_ref,
      },
      allowed_actions: [externalAction],
    }
    const latest = {
      ...actionable,
      revision: 5,
      work_summary: {
        ...actionable.work_summary,
        primary_action_code: null,
        primary_action_target_ref: null,
      },
      allowed_actions: [],
    }
    api.claim.mockResolvedValueOnce(actionable).mockResolvedValue(latest)
    api.acceptExternalTaskReview.mockRejectedValue(Object.assign(
      new Error('Revision mismatch.'),
      { status: 409, code: 'REVISION_CONFLICT', requestId: 'req_external_1' },
    ))

    renderPage('/workbench/claims/clm_route_1')
    await user.click(await screen.findByRole('button', { name: 'Test projected external action' }))

    await waitFor(() => expect(screen.getByTestId('claim-revision')).toHaveTextContent('Claim revision 5'))
    await waitFor(() => expect(api.externalRequests).toHaveBeenCalledWith('staff-token', 'clm_route_1'))
    expect(api.acceptExternalTaskReview).toHaveBeenCalledTimes(1)
  })

  it('performs authoritative readback after an ambiguous external reconciliation outcome without blind resubmission', async () => {
    const user = userEvent.setup()
    const externalAction = {
      action_code: 'external.reconcile_response',
      target_type: 'external_task',
      target_ref: 'tsk_assessor_2',
      label: 'Reconcile external outcome',
      availability: 'confirmation_required',
      based_on_revision: 4,
      inputs: [],
    }
    const actionable = {
      ...claim,
      revision: 4,
      work_summary: {
        ...claim.work_summary,
        primary_action_code: externalAction.action_code,
        primary_action_target_ref: externalAction.target_ref,
      },
      allowed_actions: [externalAction],
    }
    const latest = {
      ...actionable,
      revision: 5,
      work_summary: {
        ...actionable.work_summary,
        primary_action_code: null,
        primary_action_target_ref: null,
      },
      allowed_actions: [],
    }
    api.claim.mockResolvedValueOnce(actionable).mockResolvedValue(latest)
    api.reconcileExternalTaskResponse.mockRejectedValue(Object.assign(
      new Error('The Workbench service could not be reached.'),
      { status: 0, code: 'NETWORK_ERROR', retryable: true },
    ))

    renderPage('/workbench/claims/clm_route_1')
    await user.click(await screen.findByRole('button', { name: 'Test projected external action' }))

    await waitFor(() => expect(screen.getByTestId('claim-revision')).toHaveTextContent('Claim revision 5'))
    await waitFor(() => expect(api.externalRequests).toHaveBeenCalledWith('staff-token', 'clm_route_1'))
    expect(api.reconcileExternalTaskResponse).toHaveBeenCalledWith(
      'staff-token',
      'clm_route_1',
      'tsk_assessor_2',
      4,
    )
    expect(api.reconcileExternalTaskResponse).toHaveBeenCalledTimes(1)
  })

  it('discards a late realtime Claim refresh after a controlled action loads a newer revision', async () => {
    const user = userEvent.setup()
    let pushRealtime
    let resolveRealtimeRefresh
    const delayedRealtimeRefresh = new Promise((resolve) => {
      resolveRealtimeRefresh = resolve
    })
    api.realtimeEvents.mockImplementation((_token, { onEvent, signal }) => {
      pushRealtime = onEvent
      return new Promise((resolve) => {
        signal.addEventListener('abort', resolve, { once: true })
      })
    })
    const acceptAction = {
      action_code: 'human.accept_handoff', target_type: 'handoff', target_ref: 'hnd_1', availability: 'confirmation_required', based_on_revision: 1,
    }
    const actionable = {
      ...claim,
      work_summary: { ...claim.work_summary, primary_action_code: acceptAction.action_code, primary_action_target_ref: acceptAction.target_ref },
      allowed_actions: [acceptAction],
    }
    const latest = {
      ...actionable,
      revision: 2,
      work_summary: { ...actionable.work_summary, primary_action_code: null, primary_action_target_ref: null },
      allowed_actions: [],
    }
    api.claim
      .mockResolvedValueOnce(actionable)
      .mockReturnValueOnce(delayedRealtimeRefresh)
      .mockResolvedValueOnce(latest)
    api.acceptHandoff.mockResolvedValue({})

    renderPage('/workbench/claims/clm_route_1')
    await screen.findByRole('button', { name: 'Test projected accept' })
    await waitFor(() => expect(pushRealtime).toBeTypeOf('function'))

    let realtimeRefresh
    await act(async () => {
      realtimeRefresh = pushRealtime({
        type: 'resources.changed',
        cursor: 'evt-late-claim',
        data: {
          event_id: 'evt-late-claim',
          claim_id: 'clm_route_1',
          claim_revision: 1,
          resources: ['claim'],
        },
      })
      await Promise.resolve()
    })
    await waitFor(() => expect(api.claim).toHaveBeenCalledTimes(2))

    await user.click(screen.getByRole('button', { name: 'Test projected accept' }))
    await waitFor(() => expect(screen.getByTestId('claim-revision')).toHaveTextContent('Claim revision 2'))
    expect(screen.queryByRole('button', { name: 'Test projected accept' })).not.toBeInTheDocument()

    await act(async () => {
      resolveRealtimeRefresh(actionable)
      await realtimeRefresh
    })

    expect(screen.getByTestId('claim-revision')).toHaveTextContent('Claim revision 2')
    expect(screen.queryByRole('button', { name: 'Test projected accept' })).not.toBeInTheDocument()
  })

  it('discards a late action-failure recovery projection after a newer realtime refresh', async () => {
    const user = userEvent.setup()
    let pushRealtime
    api.realtimeEvents.mockImplementation((_token, { onEvent, signal }) => {
      pushRealtime = onEvent
      return new Promise((resolve) => {
        signal.addEventListener('abort', resolve, { once: true })
      })
    })
    let resolveRecovery
    const delayedRecovery = new Promise((resolve) => {
      resolveRecovery = resolve
    })
    const acceptAction = {
      action_code: 'human.accept_handoff', target_type: 'handoff', target_ref: 'hnd_1', availability: 'confirmation_required', based_on_revision: 1,
    }
    const actionable = {
      ...claim,
      work_summary: { ...claim.work_summary, primary_action_code: acceptAction.action_code, primary_action_target_ref: acceptAction.target_ref },
      allowed_actions: [acceptAction],
    }
    const recovered = {
      ...actionable,
      revision: 2,
      allowed_actions: [{ ...acceptAction, based_on_revision: 2 }],
    }
    const newest = {
      ...recovered,
      revision: 3,
      work_summary: { ...recovered.work_summary, primary_action_code: null, primary_action_target_ref: null },
      allowed_actions: [],
    }
    const actionError = Object.assign(new Error('The action outcome is unknown.'), {
      code: 'DEPENDENCY_UNAVAILABLE',
      requestId: 'req_accept_inverse_1',
    })
    api.claim
      .mockResolvedValueOnce(actionable)
      .mockReturnValueOnce(delayedRecovery)
      .mockResolvedValueOnce(newest)
    api.acceptHandoff.mockRejectedValue(actionError)

    renderPage('/workbench/claims/clm_route_1')
    await screen.findByRole('button', { name: 'Test projected accept' })
    await waitFor(() => expect(pushRealtime).toBeTypeOf('function'))

    await user.click(screen.getByRole('button', { name: 'Test projected accept' }))
    await waitFor(() => expect(api.claim).toHaveBeenCalledTimes(2))

    await act(async () => {
      await pushRealtime({
        type: 'resources.changed',
        cursor: 'evt-newest-claim',
        data: {
          event_id: 'evt-newest-claim',
          claim_id: 'clm_route_1',
          claim_revision: 3,
          resources: ['claim'],
        },
      })
    })
    await waitFor(() => expect(screen.getByTestId('claim-revision')).toHaveTextContent('Claim revision 3'))
    expect(screen.queryByRole('button', { name: 'Test projected accept' })).not.toBeInTheDocument()

    await act(async () => {
      resolveRecovery(recovered)
      await delayedRecovery
    })
    await waitFor(() => expect(actionError.latestRevision).toBe(3))

    expect(screen.getByTestId('claim-revision')).toHaveTextContent('Claim revision 3')
    expect(screen.queryByRole('button', { name: 'Test projected accept' })).not.toBeInTheDocument()
  })

  it('keeps one multiplexed Workbench stream while navigating between Claims', async () => {
    const user = userEvent.setup()
    api.claim.mockImplementation((_token, id) => Promise.resolve({
      ...claim,
      claim_id: id,
      display_reference: id === 'clm_route_1' ? 'NW-900' : 'NW-901',
    }))

    renderPage('/workbench/claims/clm_route_1')
    await waitFor(() => expect(api.realtimeEvents).toHaveBeenCalledTimes(1))
    await user.click(screen.getByRole('button', { name: 'Navigate Claim B' }))
    await waitFor(() => expect(api.claim).toHaveBeenCalledWith('staff-token', 'clm_route_2'))

    expect(api.realtimeEvents).toHaveBeenCalledTimes(1)
  })

  it('refreshes only the named Evidence resource for an active Claim event', async () => {
    let pushRealtime
    api.realtimeEvents.mockImplementation((_token, { onEvent, signal }) => {
      pushRealtime = onEvent
      return new Promise((resolve) => {
        signal.addEventListener('abort', resolve, { once: true })
      })
    })

    renderPage('/workbench/claims/clm_route_1/evidence')
    await waitFor(() => expect(api.evidence).toHaveBeenCalled())
    await waitFor(() => expect(pushRealtime).toBeTypeOf('function'))

    const evidenceCalls = api.evidence.mock.calls.length
    const claimCalls = api.claim.mock.calls.length
    const handoffCalls = api.handoffs.mock.calls.length

    await act(async () => {
      await pushRealtime({
        type: 'resources.changed',
        cursor: 'evt-evidence',
        data: {
          event_id: 'evt-evidence',
          claim_id: 'clm_route_1',
          claim_revision: 2,
          resources: ['evidence'],
        },
      })
    })

    expect(api.evidence).toHaveBeenCalledTimes(evidenceCalls + 1)
    expect(api.claim).toHaveBeenCalledTimes(claimCalls)
    expect(api.handoffs).toHaveBeenCalledTimes(handoffCalls)
  })

  it('uses one visible authoritative snapshot as degraded fallback when the stream fails', async () => {
    let rejectStream
    api.realtimeEvents
      .mockImplementationOnce((_token, { signal }) => new Promise((resolve, reject) => {
        rejectStream = reject
        signal.addEventListener('abort', resolve, { once: true })
      }))
      .mockImplementation((_token, { signal }) => new Promise((resolve) => {
        signal.addEventListener('abort', resolve, { once: true })
      }))

    const view = renderPage('/workbench/claims/clm_route_1')
    await waitFor(() => expect(api.claims).toHaveBeenCalled())
    await waitFor(() => expect(api.claim).toHaveBeenCalled())
    await waitFor(() => expect(rejectStream).toBeTypeOf('function'))
    const queueCalls = api.claims.mock.calls.length
    const claimCalls = api.claim.mock.calls.length

    await act(async () => {
      rejectStream(Object.assign(new Error('stream unavailable'), { code: 'NETWORK_ERROR' }))
    })

    await waitFor(() => expect(api.claims.mock.calls.length).toBeGreaterThan(queueCalls))
    await waitFor(() => expect(api.claim.mock.calls.length).toBeGreaterThan(claimCalls))
    view.unmount()
  })

  it('aborts the Workbench realtime stream when the page unmounts', async () => {
    let streamSignal
    api.realtimeEvents.mockImplementation((_token, { signal }) => {
      streamSignal = signal
      return new Promise((resolve) => {
        signal.addEventListener('abort', resolve, { once: true })
      })
    })

    const view = renderPage('/workbench')
    await waitFor(() => expect(streamSignal).toBeInstanceOf(AbortSignal))
    view.unmount()

    expect(streamSignal.aborted).toBe(true)
  })

  it('propagates failed queue and open-Claim refreshes after an executed Staff Agent action', async () => {
    renderPage('/workbench/claims/clm_route_1')

    expect(await screen.findByTestId('claim-revision')).toHaveTextContent('Claim revision 1')
    await waitFor(() => expect(staffAgent.onBusinessActionExecuted).toEqual(expect.any(Function)))

    const queueFailure = Object.assign(new Error('Queue refresh failed.'), { requestId: 'req-queue-refresh' })
    const claimFailure = new Error('Claim refresh failed.')
    api.claims.mockRejectedValueOnce(queueFailure)
    api.claim.mockRejectedValueOnce(claimFailure)

    await expect(
      staffAgent.onBusinessActionExecuted({
        claim_id: 'clm_route_1',
        action_code: 'work_item.update',
        runtime_execution: { resulting_revision: 2 },
      }),
    ).rejects.toMatchObject({
      message: expect.stringContaining('Claim queue, open Claim'),
      requestId: 'req-queue-refresh',
    })
  })

  it('propagates failed queue and conversations refreshes after an executed Staff Agent action', async () => {
    renderPage('/workbench/conversations')

    await waitFor(() => expect(api.conversations).toHaveBeenCalled())
    await waitFor(() => expect(staffAgent.onBusinessActionExecuted).toEqual(expect.any(Function)))

    api.claims.mockRejectedValueOnce(new Error('Queue refresh failed.'))
    const conversationFailure = Object.assign(
      new Error('Conversation refresh failed.'),
      { requestId: 'req-conversation-refresh' },
    )
    api.conversations.mockRejectedValueOnce(conversationFailure)

    await expect(
      staffAgent.onBusinessActionExecuted({
        claim_id: 'clm_route_1',
        action_code: 'work_item.update',
        runtime_execution: { resulting_revision: 2 },
      }),
    ).rejects.toMatchObject({
      message: expect.stringContaining('Claim queue, conversations'),
      requestId: 'req-conversation-refresh',
    })
  })

})
