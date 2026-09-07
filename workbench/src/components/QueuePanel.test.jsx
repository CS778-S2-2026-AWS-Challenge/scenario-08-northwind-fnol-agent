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

const filterMetadata = {
  views: [
    { value: 'all', label: 'All active work' },
    { value: 'urgent', label: 'Urgent' },
    { value: 'incomplete_claims', label: 'Incomplete claims' },
  ],
  workflow_states: [
    { value: 'collecting', label: 'Collecting' },
    { value: 'professional_review', label: 'Professional review' },
  ],
  priorities: [
    { value: 'standard', label: 'Standard' },
    { value: 'high', label: 'High' },
  ],
  tags: [{ value: tag.code, label: tag.label, category: tag.category }],
  tag_registry_version: '0.2',
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
    filterMetadata,
    view: 'all',
    onView: vi.fn(),
    workflowState: '',
    onWorkflowState: vi.fn(),
    priority: '',
    onPriority: vi.fn(),
    tagFilter: '',
    onTag: vi.fn(),
    search: '',
    onSearch: vi.fn(),
    onClearFilters: vi.fn(),
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

    await user.click(screen.getByRole('button', { name: 'Filters' }))
    expect(screen.getAllByText('Vehicle not drivable')).toHaveLength(2)
    await user.selectOptions(screen.getByLabelText('Staff tag'), tag.code)
    expect(onTag).toHaveBeenCalledWith(tag.code)
  })

  it('uses the backend incomplete-claims value and label', async () => {
    const onView = vi.fn()
    const user = userEvent.setup()
    renderQueue({ onView })

    await user.selectOptions(screen.getByLabelText('Current work'), 'incomplete_claims')

    expect(screen.getByRole('option', { name: 'Incomplete claims' })).toHaveValue('incomplete_claims')
    expect(onView).toHaveBeenCalledWith('incomplete_claims')
  })

  it('exposes supported status and priority filters and visible queue values', async () => {
    const onWorkflowState = vi.fn()
    const onPriority = vi.fn()
    const user = userEvent.setup()
    renderQueue({ onWorkflowState, onPriority })

    expect(screen.getByText('Priority: Standard')).toBeInTheDocument()
    expect(screen.getByText('Motor · Status: Collecting')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Filters' }))
    await user.selectOptions(screen.getByLabelText('Claim status'), 'professional_review')
    await user.selectOptions(screen.getByLabelText('Claim priority'), 'high')

    expect(onWorkflowState).toHaveBeenCalledWith('professional_review')
    expect(onPriority).toHaveBeenCalledWith('high')
  })

  it('distinguishes filtered no-results and clears the current filter state', async () => {
    const onClearFilters = vi.fn()
    const user = userEvent.setup()
    renderQueue({
      claims: [],
      view: 'urgent',
      workflowState: 'professional_review',
      priority: 'urgent',
      tagFilter: tag.code,
      search: 'NW-4040',
      onClearFilters,
    })

    expect(screen.getByText('No claims match the current filters.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Clear filters' }))

    expect(onClearFilters).toHaveBeenCalledOnce()
  })

  it('keeps queue navigation available when the current view has no claims', () => {
    renderQueue({ claims: [] })

    expect(screen.getByText('No claims are currently in this queue.')).toBeInTheDocument()
    expect(screen.getByLabelText('Current work')).toBeInTheDocument()
    expect(screen.getByLabelText('Search claims')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Filters' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Claim status')).not.toBeInTheDocument()
  })

  it('uses an accessible disclosure for secondary filters', async () => {
    const user = userEvent.setup()
    renderQueue()

    const toggle = screen.getByRole('button', { name: 'Filters' })
    expect(toggle).toHaveAttribute('aria-expanded', 'false')
    expect(toggle).toHaveAttribute('aria-controls', 'queue-secondary-filters')
    await user.click(toggle)
    expect(toggle).toHaveAttribute('aria-expanded', 'true')
    expect(screen.getByLabelText('Claim status')).toBeInTheDocument()
  })

  it('loads the next backend page only when a cursor is available', async () => {
    const onLoadMore = vi.fn()
    const user = userEvent.setup()
    renderQueue({ nextCursor: 'cursor-2', onLoadMore })

    await user.click(screen.getByRole('button', { name: 'Load more Claims' }))
    expect(onLoadMore).toHaveBeenCalledOnce()
  })
})
