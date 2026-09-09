import { act, render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { workbenchApi } from '../api.js'
import WorkbenchPage from './WorkbenchPage.jsx'

vi.mock('../auth/auth-context.js', () => ({
  useAuth: () => ({
    token: 'staff-token',
    profile: { staff_id: 'stf_418', display_name: 'Claims Professional', roles: ['claims_professional'] },
    logout: vi.fn(),
  }),
}))

const claims = [
  queueClaim('clm_ready', 'NW-1001', 'ready_for_next', 'standard'),
  queueClaim('clm_urgent', 'NW-1002', 'professional_review', 'urgent'),
  queueClaim('clm_high', 'NW-1003', 'professional_review', 'high'),
]

const filterMetadata = {
  views: [
    { value: 'all', label: 'All active work' },
    { value: 'urgent', label: 'Urgent' },
    { value: 'incomplete_claims', label: 'Incomplete claims' },
  ],
  workflow_states: [
    { value: 'ready_for_next', label: 'Ready for next' },
    { value: 'professional_review', label: 'Professional review' },
  ],
  priorities: [
    { value: 'routine', label: 'Routine' },
    { value: 'standard', label: 'Standard' },
    { value: 'high', label: 'High' },
    { value: 'urgent', label: 'Urgent' },
  ],
  tags: [{ value: 'impact.vehicle_not_drivable', label: 'Vehicle not drivable', category: 'impact' }],
  tag_registry_version: '0.2',
}

describe('WorkbenchPage queue filters', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
    vi.spyOn(workbenchApi, 'claimFilterMetadata').mockResolvedValue(filterMetadata)
    vi.spyOn(workbenchApi, 'claims').mockImplementation(async (_token, filters) => ({
      items: claims.filter((claim) => (
        (!filters.workflow_state || claim.workflow_state === filters.workflow_state)
        && (!filters.priority || claim.priority_projection.level === filters.priority)
      )),
      page: { next_cursor: null },
    }))
  })

  it('keeps status and priority filters combined when rendering the queue', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/workbench']}>
        <Routes>
          <Route path="/workbench/*" element={<WorkbenchPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('NW-1001')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Filters' }))
    await user.selectOptions(screen.getByLabelText('Claim status'), 'professional_review')
    await waitFor(() => expect(screen.queryByText('NW-1001')).not.toBeInTheDocument())
    expect(screen.getByText('NW-1002')).toBeInTheDocument()
    expect(screen.getByText('NW-1003')).toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('Claim priority'), 'urgent')
    await waitFor(() => expect(screen.queryByText('NW-1003')).not.toBeInTheDocument())
    expect(screen.getByText('NW-1002')).toBeInTheDocument()
    expect(workbenchApi.claims).toHaveBeenLastCalledWith('staff-token', {
      workflow_state: 'professional_review',
      priority: 'urgent',
      limit: 25,
    })
  })

  it('does not render an older response after the current filters change', async () => {
    let resolveStatusRequest
    workbenchApi.claims.mockImplementation((_token, filters) => {
      if (filters.workflow_state && !filters.priority) {
        return new Promise((resolve) => { resolveStatusRequest = resolve })
      }
      return Promise.resolve({
        items: claims.filter((claim) => (
          (!filters.workflow_state || claim.workflow_state === filters.workflow_state)
          && (!filters.priority || claim.priority_projection.level === filters.priority)
        )),
        page: { next_cursor: null },
      })
    })
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/workbench']}>
        <Routes>
          <Route path="/workbench/*" element={<WorkbenchPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('NW-1001')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Filters' }))
    await user.selectOptions(screen.getByLabelText('Claim status'), 'professional_review')
    await waitFor(() => expect(resolveStatusRequest).toBeTypeOf('function'))
    await user.selectOptions(screen.getByLabelText('Claim priority'), 'urgent')
    expect(await screen.findByText('NW-1002')).toBeInTheDocument()

    await act(async () => resolveStatusRequest({
      items: claims.filter((claim) => claim.workflow_state === 'professional_review'),
      page: { next_cursor: null },
    }))

    expect(screen.queryByText('NW-1003')).not.toBeInTheDocument()
  })

  it('restores normalized queue filters from the route and discards a stale cursor', async () => {
    render(
      <MemoryRouter initialEntries={['/workbench?view=urgent&workflow_state=professional_review&priority=urgent&tag=impact.vehicle_not_drivable&search=NW-1002&cursor=stale']}>
        <LocationProbe />
        <Routes>
          <Route path="/workbench/*" element={<WorkbenchPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(workbenchApi.claims).toHaveBeenCalledWith('staff-token', {
      view: 'urgent',
      workflow_state: 'professional_review',
      priority: 'urgent',
      tag: 'impact.vehicle_not_drivable',
      search: 'NW-1002',
      limit: 25,
    }))
    expect(screen.getByTestId('location-search')).toHaveTextContent('view=urgent')
    await waitFor(() => expect(screen.getByTestId('location-search')).not.toHaveTextContent('cursor='))
    expect(screen.getByLabelText('Search claims')).toHaveValue('NW-1002')
  })

  it('removes unknown route filters using backend metadata', async () => {
    render(
      <MemoryRouter initialEntries={['/workbench?view=obsolete&priority=extreme&search=%20%20']}>
        <LocationProbe />
        <Routes>
          <Route path="/workbench/*" element={<WorkbenchPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await waitFor(() => expect(screen.getByTestId('location-search')).toBeEmptyDOMElement())
    await waitFor(() => expect(workbenchApi.claims).toHaveBeenCalledWith('staff-token', {
      limit: 25,
    }))
  })

  it('recovers an invalid backend cursor from the first ranked page', async () => {
    workbenchApi.claims.mockImplementation(async (_token, filters) => {
      if (filters.cursor) {
        const error = new Error('The pagination cursor is invalid.')
        error.code = 'VALIDATION_ERROR'
        throw error
      }
      return { items: claims, page: { next_cursor: 'stale-cursor' } }
    })
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/workbench']}>
        <Routes>
          <Route path="/workbench/*" element={<WorkbenchPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: 'Load more Claims' }))
    expect(await screen.findByText(/invalid or stale/)).toBeInTheDocument()
    expect(workbenchApi.claims).toHaveBeenLastCalledWith('staff-token', { limit: 25 })
  })

  it('keeps an open Claim workspace usable when filter metadata fails and retries the queue', async () => {
    const user = userEvent.setup()
    workbenchApi.claimFilterMetadata
      .mockRejectedValueOnce(new Error('Queue filter metadata could not be loaded.'))
      .mockResolvedValueOnce(filterMetadata)
    vi.spyOn(workbenchApi, 'claim').mockResolvedValue(claimDetail())
    vi.spyOn(workbenchApi, 'handoffs').mockResolvedValue({ items: [], page: { next_cursor: null } })
    vi.spyOn(workbenchApi, 'collaborationRequests').mockResolvedValue({ items: [], page: { next_cursor: null } })

    render(
      <MemoryRouter initialEntries={['/workbench/claims/clm_ready']}>
        <Routes>
          <Route path="/workbench/claims/:claimId/*" element={<WorkbenchPage />} />
        </Routes>
      </MemoryRouter>,
    )

    const queueAlert = await screen.findByRole('alert')
    expect(queueAlert).toHaveTextContent('Claim queue unavailable')
    expect(queueAlert).toHaveTextContent('Queue filter metadata could not be loaded.')
    expect(screen.getByRole('heading', { name: 'Claim queue' })).toBeInTheDocument()
    expect(await screen.findByRole('heading', { name: 'Synthetic claimant' })).toBeInTheDocument()
    expect(workbenchApi.claims).not.toHaveBeenCalled()

    await user.click(screen.getByRole('button', { name: 'Retry' }))

    await waitFor(() => expect(workbenchApi.claimFilterMetadata).toHaveBeenCalledTimes(2))
    expect(await screen.findAllByText('NW-1001')).not.toHaveLength(0)
    expect(screen.getByRole('heading', { name: 'Synthetic claimant' })).toBeInTheDocument()
  })

  it('renders an unavailable queue instead of an empty queue when the initial query fails', async () => {
    workbenchApi.claims.mockRejectedValue(new Error('The queue projection service timed out.'))

    render(
      <MemoryRouter initialEntries={['/workbench']}>
        <Routes>
          <Route path="/workbench/*" element={<WorkbenchPage />} />
        </Routes>
      </MemoryRouter>,
    )

    const queueAlert = await screen.findByRole('alert')
    expect(queueAlert).toHaveTextContent('Claim queue unavailable')
    expect(queueAlert).toHaveTextContent('The queue projection service timed out.')
    expect(screen.queryByText('No claims are currently in this queue.')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Retry' })).toBeInTheDocument()
  })

  it('preserves the last successful list when a filtered refresh fails', async () => {
    workbenchApi.claims.mockImplementation(async (_token, filters) => {
      if (filters.priority === 'urgent') {
        throw new Error('The filtered queue could not be refreshed.')
      }
      return { items: claims, page: { next_cursor: null } }
    })
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/workbench']}>
        <Routes>
          <Route path="/workbench/*" element={<WorkbenchPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('NW-1001')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Filters' }))
    await user.selectOptions(screen.getByLabelText('Claim priority'), 'urgent')

    const queueAlert = await screen.findByRole('alert')
    expect(queueAlert).toHaveTextContent('The Claims below are from the last successful load.')
    expect(screen.getByText('NW-1001')).toBeInTheDocument()
    expect(screen.queryByText('No claims match the current filters.')).not.toBeInTheDocument()
  })

  it('retries a failed queue query with the current URL filters', async () => {
    workbenchApi.claims
      .mockRejectedValueOnce(new Error('The queue is temporarily unavailable.'))
      .mockResolvedValueOnce({ items: [claims[1]], page: { next_cursor: null } })
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/workbench?priority=urgent']}>
        <Routes>
          <Route path="/workbench/*" element={<WorkbenchPage />} />
        </Routes>
      </MemoryRouter>,
    )

    await user.click(await screen.findByRole('button', { name: 'Retry' }))

    expect(await screen.findByText('NW-1002')).toBeInTheDocument()
    expect(workbenchApi.claims).toHaveBeenLastCalledWith('staff-token', {
      priority: 'urgent',
      limit: 25,
    })
  })

  it('debounces search requests and reloads the unfiltered queue when search is cleared', async () => {
    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/workbench']}>
        <Routes>
          <Route path="/workbench/*" element={<WorkbenchPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByText('NW-1001')).toBeInTheDocument()
    const searchInput = screen.getByLabelText('Search claims')
    await user.type(searchInput, 'motor')

    expect(workbenchApi.claims).toHaveBeenCalledTimes(1)
    await waitFor(() => expect(workbenchApi.claims).toHaveBeenLastCalledWith('staff-token', {
      search: 'motor',
      limit: 25,
    }))
    expect(workbenchApi.claims.mock.calls.filter(([, filters]) => filters.search)).toEqual([
      ['staff-token', { search: 'motor', limit: 25 }],
    ])

    await user.clear(screen.getByLabelText('Search claims'))
    await waitFor(() => expect(workbenchApi.claims).toHaveBeenLastCalledWith('staff-token', {
      limit: 25,
    }))
  })
})

describe('WorkbenchPage staff takeover and write-back journey', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
  })

  it('renders each authoritative revision from handoff acceptance through claimant-safe WorkItem write-back', async () => {
    let revision = 7
    let messageAttempts = 0
    let workItemCompleted = false
    const claimantQuestion = 'Could you confirm where the vehicle is stored now?'
    const internalResult = 'Storage location confirmed against the source conversation.'
    const claimantUpdate = 'Thanks, we have the location and your report can continue.'
    const messages = []

    vi.spyOn(workbenchApi, 'claimFilterMetadata').mockResolvedValue(filterMetadata)
    vi.spyOn(workbenchApi, 'claims').mockImplementation(async () => ({
      items: [staffJourneyQueueClaim(revision)],
      page: { next_cursor: null },
    }))
    vi.spyOn(workbenchApi, 'claim').mockImplementation(async () => staffJourneyDetail(revision))
    vi.spyOn(workbenchApi, 'handoffs').mockImplementation(async () => ({
      items: [staffJourneyHandoff(revision)],
      page: { next_cursor: null },
    }))
    vi.spyOn(workbenchApi, 'collaborationRequests').mockResolvedValue({ items: [], page: { next_cursor: null } })
    vi.spyOn(workbenchApi, 'sessions').mockResolvedValue({
      items: [{ session_id: 'ses_418', claim_id: 'clm_418', status: 'active' }],
      page: { next_cursor: null },
    })
    vi.spyOn(workbenchApi, 'messages').mockImplementation(async () => ({
      items: [...messages],
      page: { next_cursor: null },
    }))
    vi.spyOn(workbenchApi, 'workItems').mockImplementation(async () => ({
      items: staffJourneyWorkItems(workItemCompleted, internalResult),
      page: { next_cursor: null },
    }))
    vi.spyOn(workbenchApi, 'customerUpdates').mockImplementation(async () => ({
      items: workItemCompleted ? [{
        update_id: 'upd_418',
        summary: claimantUpdate,
        responsible_party: 'claimant',
        related_refs: ['act_418'],
        created_at: '2026-09-08T03:10:00Z',
      }] : [],
      page: { next_cursor: null },
    }))
    vi.spyOn(workbenchApi, 'events').mockResolvedValue({ items: [], page: { next_cursor: null } })
    vi.spyOn(workbenchApi, 'acceptHandoff').mockImplementation(async () => {
      revision = 8
      return { claim_revision: revision }
    })
    vi.spyOn(workbenchApi, 'sendMessage').mockImplementation(async () => {
      messageAttempts += 1
      if (messageAttempts === 1) throw new Error('The message was not sent because the Claim changed. Review the latest version and try again.')
      revision = 9
      messages.push({
        message_id: 'msg_418',
        claim_id: 'clm_418',
        session_id: 'ses_418',
        actor: 'staff',
        visibility: 'shared',
        content: { type: 'text', text: claimantQuestion },
        evidence_refs: [],
        created_at: '2026-09-08T03:05:00Z',
      })
      return { claim_revision: revision }
    })
    vi.spyOn(workbenchApi, 'updateStaffAction').mockImplementation(async () => {
      revision = 10
      workItemCompleted = true
      return { claim_revision: revision }
    })

    const user = userEvent.setup()
    render(
      <MemoryRouter initialEntries={['/workbench/claims/clm_418']}>
        <Routes>
          <Route path="/workbench/claims/:claimId/*" element={<WorkbenchPage />} />
        </Routes>
      </MemoryRouter>,
    )

    expect(await screen.findByRole('heading', { name: 'Accept handoff' })).toBeVisible()
    expect(screen.queryByText('Accept stale handoff')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Review acceptance' }))
    await user.click(screen.getByRole('button', { name: 'Confirm Accept handoff' }))

    await waitFor(() => expect(workbenchApi.acceptHandoff).toHaveBeenCalledWith(
      'staff-token', 'clm_418', 'hnd_418', 7,
    ))
    expect(await screen.findByRole('heading', { name: 'Ask claimant for location' })).toBeVisible()
    expect(screen.getByText('Assigned to you')).toBeVisible()
    expect(screen.getByText('Revision 8')).toBeVisible()

    await user.click(screen.getByRole('button', { name: 'Open conversation' }))
    const reply = await screen.findByLabelText('Reply to claimant')
    await user.type(reply, claimantQuestion)
    await user.click(screen.getByRole('button', { name: 'Send message' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('The message was not sent because the Claim changed.')
    expect(reply).toHaveValue(claimantQuestion)
    expect(workbenchApi.sendMessage).toHaveBeenLastCalledWith('staff-token', 'clm_418', {
      message: claimantQuestion,
      sessionId: 'ses_418',
    }, 8)

    await user.click(screen.getByRole('button', { name: 'Send message' }))
    await waitFor(() => expect(reply).toHaveValue(''))
    expect(workbenchApi.sendMessage).toHaveBeenLastCalledWith('staff-token', 'clm_418', {
      message: claimantQuestion,
      sessionId: 'ses_418',
    }, 8)
    expect(await screen.findByText(claimantQuestion)).toBeVisible()
    expect(screen.getByText('Revision 9')).toBeVisible()
    expect(screen.queryByText('Internal handoff reason: possible coverage concern.')).not.toBeInTheDocument()

    await user.click(screen.getByRole('tab', { name: 'Overview' }))
    expect(await screen.findByRole('heading', { name: 'Complete claimant support' })).toBeVisible()
    await user.click(screen.getByRole('button', { name: 'Open work activity' }))

    const staleRecord = (await screen.findByText('Handoff Support')).closest('details')
    await user.click(within(staleRecord).getByText('Handoff Support'))
    expect(within(staleRecord).queryByRole('button', { name: 'Update action' })).not.toBeInTheDocument()
    expect(within(staleRecord).getByText(/no work-item update action is projected/i)).toBeVisible()

    const blockedRecord = screen.getByText('Coverage Review').closest('details')
    await user.click(within(blockedRecord).getByText('Coverage Review'))
    expect(within(blockedRecord).queryByRole('button', { name: 'Update action' })).not.toBeInTheDocument()
    expect(within(blockedRecord).getByText('This WorkItem belongs to another professional.')).toBeVisible()

    const currentRecord = screen.getByText('Claimant Support').closest('details')
    await user.click(within(currentRecord).getByText('Claimant Support'))
    await user.selectOptions(within(currentRecord).getByLabelText('Status'), 'completed')
    await user.type(within(currentRecord).getByLabelText('Internal result summary'), internalResult)
    await user.type(within(currentRecord).getByLabelText('Claimant update'), claimantUpdate)
    await user.click(within(currentRecord).getByRole('button', { name: 'Update action' }))

    expect(workbenchApi.updateStaffAction).toHaveBeenCalledWith('staff-token', 'clm_418', 'act_418', 9, {
      status: 'completed',
      result: {
        outcome: 'staff_work_completed',
        reason_codes: ['SUPPORT_NEED_MET'],
        source_refs: ['msg_418'],
        summary: internalResult,
      },
      state_changes: [],
      customer_update: {
        responsible_party: 'claimant',
        related_refs: ['act_418'],
        summary: claimantUpdate,
      },
    })

    await screen.findByText(internalResult)
    await user.click(screen.getByText('Claimant Support'))
    expect(screen.getByText(internalResult)).toBeVisible()
    const customerUpdateSurface = screen.getByRole('heading', { name: 'Customer updates' }).closest('section')
    expect(within(customerUpdateSurface).getByText(claimantUpdate)).toBeVisible()
    expect(within(customerUpdateSurface).queryByText(internalResult)).not.toBeInTheDocument()
    expect(screen.getByText('Revision 10')).toBeVisible()
  })
})

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location-search">{location.search}</output>
}

function queueClaim(claimId, displayReference, workflowState, priority) {
  return {
    claim_id: claimId,
    display_reference: displayReference,
    claimant: { customer_id: `cus_${claimId}` },
    incident: { family: 'motor', summary: 'Synthetic claim for queue filtering.' },
    lifecycle_state: workflowState === 'professional_review' ? 'professional_review' : 'draft_active',
    workflow_state: workflowState,
    ownership: { state: 'unassigned', current_staff_access: 'read_only' },
    priority_projection: { level: priority },
    work_summary: { queue_key: workflowState, current_work_item: null },
    updated_at: '2026-09-03T01:00:00Z',
    tags: [],
  }
}

function claimDetail() {
  return {
    ...queueClaim('clm_ready', 'NW-1001', 'ready_for_next', 'standard'),
    revision: 1,
    claimant: { customer_id: 'cus_clm_ready', display_name: 'Synthetic claimant' },
    ownership: { state: 'unassigned', current_staff_access: 'read_only', coworkers: [] },
    work_summary: {
      queue_key: 'ready_for_next',
      current_work_item: null,
      primary_action_code: null,
      primary_action_target_ref: null,
      missing_information: [],
      risk_signals: [],
    },
    section_summaries: {},
    customer_next_step: { summary: 'Continue reviewing this Claim.' },
    allowed_actions: [],
  }
}

function staffJourneyQueueClaim(revision) {
  return {
    ...queueClaim('clm_418', 'NW-418', revision >= 9 ? 'ready_for_next' : 'professional_review', 'high'),
    revision,
  }
}

function staffJourneyDetail(revision) {
  const base = {
    ...staffJourneyQueueClaim(revision),
    active_session_id: 'ses_418',
    claimant: { customer_id: 'cus_418', display_name: 'Jordan Lee' },
    incident: { family: 'motor', summary: 'Vehicle storage location requires claimant confirmation.' },
    lifecycle_state: revision === 7 ? 'staff_support' : 'draft_active',
    ownership: revision === 7
      ? { state: 'unassigned', current_staff_access: 'read_only', coworkers: [] }
      : { state: 'assigned', current_staff_access: 'primary', primary_assignee: { staff_id: 'stf_418', display_name: 'Claims Professional' }, coworkers: [] },
    priority_projection: { level: 'high' },
    section_summaries: {},
    source_summary: { status: 'available', items: [], limitation: null },
    customer_next_step: {
      summary: revision >= 10 ? 'Your report can continue.' : 'A claims professional is reviewing your report.',
      responsible_party: revision >= 10 ? 'claimant' : 'claims_professional',
    },
    created_at: '2026-09-08T02:00:00Z',
    updated_at: `2026-09-08T03:${String(revision).padStart(2, '0')}:00Z`,
  }

  if (revision === 7) {
    return {
      ...base,
      work_summary: staffJourneyWorkSummary('human.accept_handoff', 'hnd_418'),
      allowed_actions: [
        projectedAcceptAction('hnd_418', 'Accept handoff', 7),
        projectedAcceptAction('hnd_stale', 'Accept stale handoff', 6),
      ],
    }
  }
  if (revision === 8) {
    return {
      ...base,
      work_summary: staffJourneyWorkSummary('conversation.send_claimant_message', 'ses_418'),
      allowed_actions: [
        projectedMessageAction('ses_previous', 'Reply to prior session', 7),
        projectedMessageAction('ses_418', 'Ask claimant for location', 8),
      ],
    }
  }
  if (revision === 9) {
    return {
      ...base,
      work_summary: staffJourneyWorkSummary('work_item.update', 'act_418'),
      allowed_actions: [
        projectedWorkItemAction('act_previous_revision', 'confirmation_required', 8),
        projectedWorkItemAction('act_blocked', 'blocked', 9),
        projectedWorkItemAction('act_418', 'confirmation_required', 9),
      ],
    }
  }
  return {
    ...base,
    work_summary: staffJourneyWorkSummary(null, null),
    allowed_actions: [],
  }
}

function staffJourneyWorkSummary(actionCode, targetRef) {
  return {
    queue_key: 'claimant_support',
    primary_action_code: actionCode,
    primary_action_target_ref: targetRef,
    missing_information: [],
    risk_signals: [],
  }
}

function staffJourneyHandoff(revision) {
  return {
    handoff_id: 'hnd_418',
    claim_id: 'clm_418',
    status: revision === 7 ? 'queued' : revision === 8 ? 'accepted' : 'in_progress',
    assigned_to: revision === 7 ? null : 'stf_418',
    requested_action: 'Ask the claimant to confirm the vehicle storage location.',
    reason: 'Internal handoff reason: possible coverage concern.',
    priority: 'high',
    packet: {
      incident_summary: 'Vehicle storage location is not confirmed.',
      missing_items: ['vehicle.storage_location'],
      pending_items: [],
      conflicts: [],
      promised_next_step: 'A claims professional will ask one focused question.',
    },
  }
}

function projectedAcceptAction(targetRef, label, basedOnRevision) {
  return {
    action_code: 'human.accept_handoff',
    target_ref: targetRef,
    label,
    purpose: 'Take responsibility for the queued handoff.',
    availability: 'confirmation_required',
    based_on_revision: basedOnRevision,
    confirmation: { message: 'Accepting changes Claim ownership.' },
    expected_effects: ['handoff.accept'],
    inputs: [],
  }
}

function projectedMessageAction(targetRef, label = 'Reply to claimant', basedOnRevision = 8) {
  return {
    action_code: 'conversation.send_claimant_message',
    target_ref: targetRef,
    label,
    purpose: 'Ask one claimant-visible question.',
    availability: 'available',
    based_on_revision: basedOnRevision,
    expected_effects: ['message.create'],
    inputs: [],
  }
}

function projectedWorkItemAction(targetRef, availability = 'confirmation_required', basedOnRevision = 9) {
  return {
    action_code: 'work_item.update',
    target_ref: targetRef,
    label: 'Complete claimant support',
    purpose: 'Record the source-linked result and separate claimant update.',
    availability,
    based_on_revision: basedOnRevision,
    blocked_reason: availability === 'blocked' ? 'This WorkItem belongs to another professional.' : null,
    confirmation: { message: 'Completion writes the registered audited result.' },
    inputs: [
      {
        field_code: 'status',
        label: 'Status',
        control: 'select',
        required: true,
        choices: [
          { value: 'in_progress', label: 'In progress' },
          { value: 'completed', label: 'Completed' },
        ],
      },
      { field_code: 'result.summary', label: 'Internal result summary', control: 'textarea', required: false, required_when: { field_code: 'status', equals: 'completed' }, choices: [] },
      { field_code: 'customer_update.summary', label: 'Claimant update', control: 'textarea', required: false, required_when: { field_code: 'status', equals: 'completed' }, choices: [] },
    ],
    payload_defaults: {
      result: { outcome: 'staff_work_completed', reason_codes: ['SUPPORT_NEED_MET'], source_refs: ['msg_418'] },
      state_changes: [],
      customer_update: { responsible_party: 'claimant', related_refs: ['act_418'] },
    },
  }
}

function staffJourneyWorkItems(completed, internalResult) {
  return [
    {
      action_id: 'act_418', action_type: 'claimant_support', requested_outcome: 'Confirm the vehicle storage location.',
      status: completed ? 'completed' : 'in_progress', assigned_to: 'stf_418', source_refs: ['msg_418'],
      result: completed ? { outcome: 'staff_work_completed', summary: internalResult, reason_codes: ['SUPPORT_NEED_MET'], source_refs: ['msg_418'] } : null,
      created_at: '2026-09-08T02:30:00Z', completed_at: completed ? '2026-09-08T03:10:00Z' : null,
    },
    {
      action_id: 'act_stale_record', action_type: 'handoff_support', requested_outcome: 'Old projected work.',
      status: 'open', assigned_to: 'stf_418', source_refs: [], created_at: '2026-09-08T02:31:00Z',
    },
    {
      action_id: 'act_blocked', action_type: 'coverage_review', requested_outcome: 'Owned by another professional.',
      status: 'open', assigned_to: 'stf_other', source_refs: [], created_at: '2026-09-08T02:32:00Z',
    },
  ]
}
