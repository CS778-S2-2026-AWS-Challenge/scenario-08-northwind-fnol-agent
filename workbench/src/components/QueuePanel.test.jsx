import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import QueuePanel from './QueuePanel.jsx'

const tag = {
  tag_instance_id: 'clm_1:impact.vehicle_not_drivable',
  code: 'impact.vehicle_not_drivable',
  label: 'Vehicle not drivable',
  category: 'impact',
  basis: 'reported',
  source_refs: ['field:vehicle.drivable'],
}

const claim = {
  claim_id: 'clm_1',
  display_reference: 'NW-1042',
  claimant: { customer_id: 'cus_1', display_name: 'Alex Morgan' },
  incident: { family: 'motor', summary: 'Review the reported vehicle damage.' },
  lifecycle_state: 'draft_active',
  workflow_state: 'collecting',
  ownership: { state: 'unassigned', current_staff_access: 'read_only' },
  priority_projection: { level: 'standard' },
  work_summary: { queue_key: 'incomplete', current_work_item: null },
  updated_at: '2026-09-03T01:00:00Z',
  tags: [tag],
}

function renderQueue(overrides = {}) {
  const props = {
    claims: [claim],
    loading: false,
    selectedId: null,
    view: 'all',
    onView: vi.fn(),
    workflowState: '',
    onWorkflowState: vi.fn(),
    priority: '',
    onPriority: vi.fn(),
    tagFilter: '',
    tags: [tag],
    onTag: vi.fn(),
    nextCursor: null,
    onLoadMore: vi.fn(),
    onOpen: vi.fn(),
    ...overrides,
  }
  render(<QueuePanel {...props} />)
  return props
}

describe('QueuePanel', () => {
  it('uses backend tag codes for filtering while displaying staff labels', async () => {
    const onTag = vi.fn()
    const user = userEvent.setup()
    renderQueue({ onTag })

    expect(screen.getAllByText('Vehicle not drivable')).toHaveLength(2)
    await user.selectOptions(screen.getByLabelText('Staff tag'), tag.code)
    expect(onTag).toHaveBeenCalledWith(tag.code)
  })

  it('exposes supported status and priority filters and visible queue values', async () => {
    const onWorkflowState = vi.fn()
    const onPriority = vi.fn()
    const user = userEvent.setup()
    renderQueue({ onWorkflowState, onPriority })

    expect(screen.getByText('Priority: Standard')).toBeInTheDocument()
    expect(screen.getByText('Motor · Status: Collecting')).toBeInTheDocument()

    await user.selectOptions(screen.getByLabelText('Claim status'), 'professional_review')
    await user.selectOptions(screen.getByLabelText('Claim priority'), 'high')

    expect(onWorkflowState).toHaveBeenCalledWith('professional_review')
    expect(onPriority).toHaveBeenCalledWith('high')
  })

  it('distinguishes filtered no-results and clears the current filter state', async () => {
    const onView = vi.fn()
    const onWorkflowState = vi.fn()
    const onPriority = vi.fn()
    const onTag = vi.fn()
    const user = userEvent.setup()
    renderQueue({
      claims: [],
      view: 'urgent',
      workflowState: 'professional_review',
      priority: 'urgent',
      tagFilter: tag.code,
      onView,
      onWorkflowState,
      onPriority,
      onTag,
    })

    expect(screen.getByText('No claims match the current filters.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Clear filters' }))

    expect(onView).toHaveBeenCalledWith('all')
    expect(onWorkflowState).toHaveBeenCalledWith('')
    expect(onPriority).toHaveBeenCalledWith('')
    expect(onTag).toHaveBeenCalledWith('')
  })

  it('hides filters when the unfiltered queue has no claims', () => {
    renderQueue({ claims: [], tags: [] })

    expect(screen.getByText('No claims are currently in this queue.')).toBeInTheDocument()
    expect(screen.queryByLabelText('Claim status')).not.toBeInTheDocument()
  })

  it('loads the next backend page only when a cursor is available', async () => {
    const onLoadMore = vi.fn()
    const user = userEvent.setup()
    renderQueue({ nextCursor: 'cursor-2', onLoadMore })

    await user.click(screen.getByRole('button', { name: 'Load more Claims' }))
    expect(onLoadMore).toHaveBeenCalledOnce()
  })
})
