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
    { value: 'all', label: 'All active work', group: 'overview' },
    { value: 'processing', label: 'Processing', group: 'active' },
    { value: 'waiting_user', label: 'Waiting for claimant', group: 'active' },
    { value: 'waiting_material', label: 'Waiting for material', group: 'active' },
    { value: 'waiting_third_party', label: 'Waiting for third party', group: 'active' },
    { value: 'completed', label: 'Completed', group: 'terminal' },
    { value: 'abandoned', label: 'Abandoned', group: 'terminal' },
    { value: 'closed', label: 'Closed', group: 'terminal' },
    { value: 'urgent', label: 'Urgent', group: 'operational' },
    { value: 'incomplete_claims', label: 'Incomplete claims', group: 'operational' },
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
  tag_registry_version: '0.3',
}

const viewCounts = {
  status: 'available',
  items: filterMetadata.views.map((option) => ({
    view: option.value,
    count: option.value === 'all' || option.value === 'processing' ? 1 : 0,
  })),
  limitation: null,
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
  work_summary: { queue_key: 'processing', current_work_item: null },
  updated_at: '2026-09-03T01:00:00Z',
  tags: [tag],
}

function renderQueue(overrides = {}) {
  const props = {
    claims: [claim],
    loading: false,
    error: '',
    onRetry: vi.fn(),
    selectedId: null,
    filterMetadata,
    viewCounts,
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
    additionalFiltersActive: false,
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

    expect(screen.getByRole('option', { name: 'Incomplete claims (0)' })).toHaveValue('incomplete_claims')
    expect(onView).toHaveBeenCalledWith('incomplete_claims')
  })

  it('renders server-published queue groups and authoritative counts', () => {
    renderQueue()

    expect(screen.getByRole('group', { name: 'Active' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Terminal' })).toBeInTheDocument()
    expect(screen.getByRole('group', { name: 'Operational' })).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Processing (1)' })).toHaveValue('processing')
    expect(screen.getByRole('option', { name: 'Waiting for third party (0)' })).toHaveValue(
      'waiting_third_party',
    )
    expect(screen.getByText('1 total')).toBeInTheDocument()
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

  it('hides irrelevant filters only when the authoritative all count is zero', () => {
    renderQueue({
      claims: [],
      viewCounts: {
        status: 'available',
        items: viewCounts.items.map((item) => ({ ...item, count: 0 })),
        limitation: null,
      },
    })

    expect(screen.getByText('No claims currently need active work.')).toBeInTheDocument()
    expect(screen.queryByLabelText('Current work')).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Search claims')).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Filters' })).not.toBeInTheDocument()
    expect(screen.queryByLabelText('Claim status')).not.toBeInTheDocument()
  })

  it('keeps controls visible when non-view filters produce an empty all count', () => {
    renderQueue({
      claims: [],
      search: 'NW-4040',
      viewCounts: {
        status: 'available',
        items: viewCounts.items.map((item) => ({ ...item, count: 0 })),
        limitation: null,
      },
    })

    expect(screen.getByText('No claims match the current filters.')).toBeInTheDocument()
    expect(screen.getByLabelText('Current work')).toBeInTheDocument()
    expect(screen.getByLabelText('Search claims')).toBeInTheDocument()
  })

  it('keeps terminal queues reachable when no active Claims remain', () => {
    renderQueue({
      claims: [],
      viewCounts: {
        status: 'available',
        items: viewCounts.items.map((item) => ({
          ...item,
          count: item.view === 'completed' ? 1 : 0,
        })),
        limitation: null,
      },
    })

    expect(screen.getByText('No claims are currently in this queue.')).toBeInTheDocument()
    expect(screen.getByLabelText('Current work')).toBeInTheDocument()
    expect(screen.getByRole('option', { name: 'Completed (1)' })).toHaveValue('completed')
  })

  it('distinguishes terminal disposition from the retained workflow state in a queue row', () => {
    renderQueue({
      claims: [{
        ...claim,
        terminal_disposition: { value: 'closed' },
        workflow_state: 'collecting',
        work_summary: { ...claim.work_summary, queue_key: 'closed' },
      }],
      view: 'closed',
    })

    expect(screen.getByText('Motor · Terminal: Closed · Retained status: Collecting')).toBeInTheDocument()
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

  it('never substitutes the loaded page size for the authoritative total', () => {
    renderQueue({ priority: 'high', nextCursor: 'cursor-2' })

    expect(screen.getByText('1 total')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Load more Claims' })).toBeInTheDocument()
  })

  it('labels unavailable totals without replacing them with zero', async () => {
    const onRetry = vi.fn()
    const user = userEvent.setup()
    renderQueue({
      onRetry,
      viewCounts: {
        status: 'unavailable',
        items: [],
        limitation: 'Queue totals are temporarily unavailable.',
      },
    })

    expect(screen.getByText('Total unavailable')).toBeInTheDocument()
    expect(screen.queryByText('0 total')).not.toBeInTheDocument()
    expect(screen.getByText('NW-1042')).toBeInTheDocument()
    expect(screen.getByText('Queue totals unavailable.')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Refresh totals' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('retains and labels the last successful queue snapshot after refresh failure', async () => {
    const onRetry = vi.fn()
    const user = userEvent.setup()
    renderQueue({
      onRetry,
      error: Object.assign(new Error('Queue service timed out.'), { requestId: 'req_queue_1' }),
    })

    expect(screen.getByRole('alert')).toHaveTextContent('Claims below are from the last successful load')
    expect(screen.getByRole('alert')).toHaveTextContent('Request reference: req_queue_1')
    expect(screen.getByRole('button', { name: /NW-1042/ })).toHaveClass('is-stale')
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    expect(onRetry).toHaveBeenCalledOnce()
  })

  it('shows loading instead of an empty-state conclusion before the first response', () => {
    renderQueue({ claims: [], loading: true })

    expect(screen.getByText('Loading current work...')).toBeInTheDocument()
    expect(screen.queryByText(/No claims/)).not.toBeInTheDocument()
  })
})
