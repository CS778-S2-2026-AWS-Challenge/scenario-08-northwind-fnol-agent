import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import WorkbenchPage from './WorkbenchPage.jsx'

const api = vi.hoisted(() => ({
  claimFilterMetadata: vi.fn(),
  claims: vi.fn(),
  claim: vi.fn(),
  handoffs: vi.fn(),
  collaborationRequests: vi.fn(),
  acceptHandoff: vi.fn(),
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
  default: ({ detail, resources, onAccept, onReopen }) => <div>
    {detail && <output data-testid="claim-revision">Claim revision {detail.revision}</output>}
    {resources.handoffs?.error && <p>Handoff context unavailable</p>}
    {detail?.work_summary?.primary_action_code === 'claim.reopen' && <button type="button" onClick={() => onReopen(detail.allowed_actions[0], { reason: 'New material received.' }, 'reopen-route-key').catch(() => {})}>Test projected reopen</button>}
    {detail?.work_summary?.primary_action_code === 'human.accept_handoff' && <button type="button" onClick={() => onAccept({ handoff_id: 'hnd_1' }).catch(() => {})}>Test projected accept</button>}
  </div>,
}))
vi.mock('../components/StaffAgent.jsx', () => ({ default: () => null }))

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

const availableCounts = {
  status: 'available',
  items: metadata.views.map((view) => ({ view: view.value, count: 1 })),
  limitation: null,
}

function LocationProbe() {
  const location = useLocation()
  return <output data-testid="location">{location.pathname}{location.search}</output>
}

function renderPage(initialEntry) {
  const page = <><WorkbenchPage /><LocationProbe /></>
  return render(
    <MemoryRouter initialEntries={[initialEntry]}>
      <Routes>
        <Route path="/workbench" element={page} />
        <Route path="/workbench/claims/:claimId" element={page} />
        <Route path="/workbench/claims/:claimId/:section" element={page} />
      </Routes>
    </MemoryRouter>,
  )
}

describe('WorkbenchPage queue routing', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.claimFilterMetadata.mockResolvedValue(metadata)
    api.claims.mockResolvedValue({
      items: [claim],
      page: { next_cursor: null },
      view_counts: availableCounts,
    })
    api.claim.mockResolvedValue(claim)
    api.handoffs.mockResolvedValue({ items: [], page: { next_cursor: null } })
    api.collaborationRequests.mockResolvedValue({ items: [], page: { next_cursor: null } })
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

  it('discards a late background refresh after a controlled action loads a newer revision', async () => {
    const user = userEvent.setup()
    const interval = vi.spyOn(window, 'setInterval').mockReturnValue(20)
    const clearInterval = vi.spyOn(window, 'clearInterval').mockImplementation(() => {})
    let resolveBackgroundRefresh
    const delayedBackgroundRefresh = new Promise((resolve) => {
      resolveBackgroundRefresh = resolve
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
      .mockReturnValueOnce(delayedBackgroundRefresh)
      .mockResolvedValueOnce(latest)
    api.acceptHandoff.mockResolvedValue({})

    renderPage('/workbench/claims/clm_route_1')
    await screen.findByRole('button', { name: 'Test projected accept' })
    await waitFor(() => expect(interval).toHaveBeenCalledWith(expect.any(Function), 20000))
    const runBackgroundRefresh = interval.mock.calls.find(([, delay]) => delay === 20000)[0]
    let backgroundRequest
    await act(async () => {
      backgroundRequest = runBackgroundRefresh()
      await Promise.resolve()
    })
    await waitFor(() => expect(api.claim).toHaveBeenCalledTimes(2))

    await user.click(screen.getByRole('button', { name: 'Test projected accept' }))
    await waitFor(() => expect(screen.getByTestId('claim-revision')).toHaveTextContent('Claim revision 2'))
    expect(screen.queryByRole('button', { name: 'Test projected accept' })).not.toBeInTheDocument()

    await act(async () => {
      resolveBackgroundRefresh(actionable)
      await backgroundRequest
    })

    expect(screen.getByTestId('claim-revision')).toHaveTextContent('Claim revision 2')
    expect(screen.queryByRole('button', { name: 'Test projected accept' })).not.toBeInTheDocument()
    interval.mockRestore()
    clearInterval.mockRestore()
  })

  it('discards a late action-failure recovery projection after a newer background refresh', async () => {
    const user = userEvent.setup()
    const interval = vi.spyOn(window, 'setInterval').mockReturnValue(20)
    const clearInterval = vi.spyOn(window, 'clearInterval').mockImplementation(() => {})
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
    await waitFor(() => expect(interval).toHaveBeenCalledWith(expect.any(Function), 20000))
    const runBackgroundRefresh = interval.mock.calls.find(([, delay]) => delay === 20000)[0]

    await user.click(screen.getByRole('button', { name: 'Test projected accept' }))
    await waitFor(() => expect(api.claim).toHaveBeenCalledTimes(2))

    await act(async () => {
      await runBackgroundRefresh()
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
    interval.mockRestore()
    clearInterval.mockRestore()
  })
})
