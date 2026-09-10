import { render, screen, waitFor } from '@testing-library/react'
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
vi.mock('../components/ClaimWorkspace.jsx', () => ({ default: () => null }))
vi.mock('../components/StaffAgent.jsx', () => ({ default: () => null }))

const metadata = {
  views: [
    { value: 'all', label: 'All active work', group: 'overview' },
    { value: 'processing', label: 'Processing', group: 'active' },
    { value: 'waiting_user', label: 'Waiting for claimant', group: 'active' },
    { value: 'waiting_material', label: 'Waiting for material', group: 'active' },
    { value: 'waiting_third_party', label: 'Waiting for third party', group: 'active' },
    { value: 'urgent', label: 'Urgent', group: 'operational' },
  ],
  workflow_states: [{ value: 'collecting', label: 'Collecting' }],
  priorities: [{ value: 'routine', label: 'Routine' }],
  tags: [],
  tag_registry_version: '0.3',
}

const claim = {
  claim_id: 'clm_route_1',
  display_reference: 'NW-900',
  claimant: { customer_id: 'cus_demo' },
  incident: { family: 'motor', summary: 'Synthetic routing test.' },
  lifecycle_state: 'waiting_customer',
  workflow_state: 'awaiting_evidence',
  ownership: { state: 'unassigned', current_staff_access: 'read_only' },
  priority_projection: { level: 'routine' },
  work_summary: { queue_key: 'waiting_user', current_work_item: null },
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
})
