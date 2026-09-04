import { act, render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { MemoryRouter, Route, Routes } from 'react-router-dom'
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

describe('WorkbenchPage queue filters', () => {
  beforeEach(() => {
    localStorage.clear()
    vi.restoreAllMocks()
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
})

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
