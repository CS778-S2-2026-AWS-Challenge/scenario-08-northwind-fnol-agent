import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { workbenchApi } from '../api.js'
import WorkbenchPage from './WorkbenchPage.jsx'

vi.mock('../auth/auth-context.js', () => ({
  useAuth: () => ({
    token: 'staff-token',
    profile: { display_name: 'Claims Professional', roles: ['claims_professional'] },
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
