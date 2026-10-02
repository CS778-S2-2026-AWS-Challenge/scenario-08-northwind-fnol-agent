import { render, screen, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { formatDateTime, formatQueueDateTime } from '../format.js'
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
    { value: 'active_claims', label: 'Active claims', group: 'operational' },
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
  active_claim_statuses: [
    { value: 'urgent', label: 'Urgent' },
    { value: 'human_assistance', label: 'Human assistance' },
    { value: 'professional_review', label: 'Professional review' },
    { value: 'pending_creation', label: 'Pending creation' },
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

const activeClaimCounts = {
  status: 'available',
  total: 1,
  navigation_total: 1,
  items: filterMetadata.active_claim_statuses.map((option) => ({
    status: option.value,
    count: option.value === 'urgent' ? 1 : 0,
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
    activeClaimCounts,
    view: 'all',
    onView: vi.fn(),
    activeStatus: '',
    onActiveStatus: vi.fn(),
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
  it('shows Active claims status, customer, owner, update time, and status filtering', async () => {
    const onActiveStatus = vi.fn()
    const onOpen = vi.fn()
    const user = userEvent.setup()
    const activeClaim = {
      ...claim,
      active_claim: { status: 'urgent', entered_at: '2026-09-02T01:00:00Z' },
      ownership: { state: 'assigned', primary_assignee: { staff_id: 'stf_2', display_name: 'Jordan Lee' } },
    }
    renderQueue({
      queueKind: 'active',
      view: 'active_claims',
      claims: [activeClaim],
      onActiveStatus,
      onOpen,
    })

    expect(screen.getByRole('heading', { name: 'Active claims' })).toBeVisible()
    expect(screen.getByText('Claims needing continued attention or staff action.')).toBeVisible()
    expect(screen.getByText('Urgent')).toHaveClass('active-claim-status--urgent')
    expect(screen.getByText('Alex Morgan · Jordan Lee')).toBeVisible()
    expect(screen.getByText('NW-1042')).toBeVisible()
    expect(screen.getByText(formatQueueDateTime(claim.updated_at)))
      .toHaveAccessibleName(`Updated ${formatDateTime(claim.updated_at)}`)

    await user.click(screen.getByRole('button', { name: 'Filters' }))
    await user.selectOptions(screen.getByLabelText('Claim status'), 'human_assistance')
    expect(onActiveStatus).toHaveBeenCalledWith('human_assistance')
    await user.click(screen.getByRole('button', { name: /NW-1042/ }))
    expect(onOpen).toHaveBeenCalledWith(activeClaim)
  })

  it('explains when no Active claims need attention', () => {
    renderQueue({
      queueKind: 'active',
      view: 'active_claims',
      claims: [],
      activeClaimCounts: {
        status: 'available',
        total: 0,
        navigation_total: 0,
        items: activeClaimCounts.items.map((item) => ({ ...item, count: 0 })),
        limitation: null,
      },
    })

    expect(screen.getByText('No Active claims currently need attention.')).toBeVisible()
    expect(screen.queryByLabelText('Search claims')).not.toBeInTheDocument()
  })

  it('presents the formal queue as Submitted claims without a competing view switch', () => {
    renderQueue({ queueKind: 'submitted', view: 'created_routed' })

    expect(screen.getByRole('heading', { name: 'Submitted claims' })).toBeVisible()
    expect(screen.queryByLabelText('Current work')).not.toBeInTheDocument()
    expect(screen.getByText('Submitted · Motor · Unassigned')).toBeVisible()
    expect(screen.queryByText(/^Completed/)).not.toBeInTheDocument()
  })

  it('presents Draft claims with submission state, type, reference, and last customer activity', () => {
    const lastClaimantActivity = '2026-09-03T00:45:00Z'
    renderQueue({
      queueKind: 'drafts',
      view: 'incomplete_claims',
      claims: [{
        ...claim,
        claimant: { customer_id: 'cus_1' },
        incident: { family: null, summary: 'Kitchen water damage' },
        work_summary: {
          ...claim.work_summary,
          incomplete_context: { last_meaningful_activity_at: lastClaimantActivity },
        },
      }],
    })

    expect(screen.getByRole('heading', { name: 'Draft claims' })).toBeVisible()
    expect(screen.getByText('Customers are still completing these claims. They have not entered the formal work queue.')).toBeVisible()
    expect(screen.queryByLabelText('Current work')).not.toBeInTheDocument()
    expect(screen.getByText('Kitchen water damage', { selector: 'strong' })).toBeVisible()
    expect(screen.getByText('Draft')).toBeVisible()
    expect(screen.getByText('Not submitted · Type not confirmed')).toBeVisible()
    expect(screen.getByText(`Last customer activity ${formatDateTime(lastClaimantActivity)}`)).toBeVisible()
    expect(screen.getByText('NW-1042')).toBeVisible()
    expect(screen.queryByLabelText('Priority Standard')).not.toBeInTheDocument()
  })

  it('uses backend tag codes for filtering while displaying staff labels', async () => {
    const onTag = vi.fn()
    const user = userEvent.setup()
    renderQueue({ onTag })

    await user.click(screen.getByRole('button', { name: 'Filters' }))
    expect(screen.getByRole('option', { name: 'Vehicle not drivable' })).toBeInTheDocument()
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

    expect(screen.getByLabelText('Priority Standard')).toHaveClass('priority--standard')
    expect(screen.getByLabelText('Priority Standard')).toHaveTextContent('Standard')
    expect(screen.getByText('Collecting · Motor · Unassigned')).toBeInTheDocument()
    expect(screen.getByText('Review the reported vehicle damage.')).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Filters' }))
    await user.selectOptions(screen.getByLabelText('Claim status'), 'professional_review')
    await user.selectOptions(screen.getByLabelText('Claim priority'), 'high')

    expect(onWorkflowState).toHaveBeenCalledWith('professional_review')
    expect(onPriority).toHaveBeenCalledWith('high')
  })

  it('uses readable Claim context as the title and shows the complete reference', () => {
    const opaqueId = 'clm_26ebb97a053bebb885e6'
    const summary = 'The claimant has not yet completed the report.'
    renderQueue({
      claims: [{
        ...claim,
        claim_id: opaqueId,
        display_reference: opaqueId,
        claimant: { customer_id: 'cus_demo' },
        incident: { family: null, summary },
        created_at: '2026-09-22T01:00:00Z',
        updated_at: '2026-09-22T01:00:00Z',
      }],
    })

    const card = screen.getByRole('button', { name: new RegExp(summary) })
    expect(within(card).getByText(summary, { selector: 'strong' })).toBeVisible()
    expect(within(card).getByText(opaqueId)).toBeVisible()
    expect(within(card).queryByText('…b885e6')).not.toBeInTheDocument()
    expect(within(card).getByText('Collecting · Type not confirmed · Unassigned')).toBeVisible()
    expect(within(card).getByText(formatQueueDateTime('2026-09-22T01:00:00Z')))
      .toHaveAccessibleName(`Updated ${formatDateTime('2026-09-22T01:00:00Z')}`)
    expect(within(card).getAllByText(summary)).toHaveLength(1)
  })

  it('shows one backend-projected reason without duplicating attention context', () => {
    const lastClaimantActivity = '2026-09-03T00:45:00Z'
    renderQueue({
      claims: [{
        ...claim,
        priority_projection: {
          level: 'high',
          reasons: [{
            code: 'OPEN_HANDOFF',
            summary: 'A claimant support handoff needs staff action.',
            source_refs: ['hnd_1'],
          }],
        },
        work_summary: {
          ...claim.work_summary,
          current_work_item: {
            requested_outcome: 'Collect supporting evidence.',
          },
          primary_blocker: 'Police Report',
          incomplete_context: {
            resume_point: 'incident_details',
          },
          external_wait_count: 2,
          last_claimant_activity_at: lastClaimantActivity,
        },
      }],
    })

    expect(screen.getByLabelText('Priority High')).toHaveClass('priority--high')
    expect(screen.getByText('A claimant support handoff needs staff action.')).toBeInTheDocument()
    expect(screen.queryByText('Collect supporting evidence.')).not.toBeInTheDocument()
    expect(screen.queryByText('Police Report')).not.toBeInTheDocument()
    expect(screen.queryByText('Why now')).not.toBeInTheDocument()
    expect(screen.queryByText('Needs attention')).not.toBeInTheDocument()
    expect(screen.queryByText('Incomplete')).not.toBeInTheDocument()
    expect(screen.queryByText('External wait')).not.toBeInTheDocument()
    expect(screen.queryByText('Claimant activity')).not.toBeInTheDocument()
    expect(screen.getByText(formatQueueDateTime(claim.updated_at)))
      .toHaveAttribute('datetime', claim.updated_at)
      .toHaveAccessibleName(`Updated ${formatDateTime(claim.updated_at)}`)
    expect(screen.queryByText(/Unread/)).not.toBeInTheDocument()
    expect(screen.queryByText(/Overdue/)).not.toBeInTheDocument()
  })

  it.each([
    {
      label: 'primary blocker',
      workSummary: { primary_blocker: 'Police Report' },
      expected: 'Needs attention · Police Report',
    },
    {
      label: 'current work',
      workSummary: { current_work_item: { requested_outcome: 'Collect supporting evidence.' } },
      expected: 'Collect supporting evidence.',
    },
    {
      label: 'incomplete recovery',
      workSummary: { incomplete_context: { resume_point: 'incident_details' } },
      expected: 'Incomplete · Resume Incident Details',
    },
    {
      label: 'external wait',
      workSummary: { external_wait_count: 2 },
      expected: 'Waiting on 2 external services',
    },
    {
      label: 'single external wait',
      workSummary: { external_wait_count: 1 },
      expected: 'Waiting on 1 external service',
    },
  ])('uses the $label as a single fallback reason', ({ workSummary, expected }) => {
    renderQueue({
      claims: [{
        ...claim,
        work_summary: { ...claim.work_summary, ...workSummary },
      }],
    })

    expect(screen.getByText(expected)).toBeInTheDocument()
  })

  it('presents an unconfirmed claim type as plain status text', () => {
    renderQueue({
      claims: [{
        ...claim,
        incident: { ...claim.incident, family: null },
      }],
    })

    expect(screen.getByText('Collecting · Type not confirmed · Unassigned')).toBeInTheDocument()
    expect(screen.queryByText(/Claim type/)).not.toBeInTheDocument()
  })

  it('marks the selected claim as the current queue item', () => {
    const otherClaim = { ...claim, claim_id: 'clm_2', display_reference: 'NW-1043' }
    renderQueue({ claims: [claim, otherClaim], selectedId: claim.claim_id })

    expect(screen.getByRole('button', { name: /NW-1042/ }))
      .toHaveClass('is-selected')
      .toHaveAttribute('aria-current', 'true')
    expect(screen.getByRole('button', { name: /NW-1043/ }))
      .not.toHaveClass('is-selected')
      .not.toHaveAttribute('aria-current')
  })

  it('omits classification tags from compact queue cards', () => {
    renderQueue()

    expect(screen.queryByText(tag.label)).not.toBeInTheDocument()
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

  it('keeps terminal disposition and an unconfirmed type ahead of retained workflow context', () => {
    renderQueue({
      claims: [{
        ...claim,
        incident: { ...claim.incident, family: null },
        terminal_disposition: { value: 'completed' },
        workflow_state: 'professional_review',
        work_summary: { ...claim.work_summary, queue_key: 'processing' },
      }],
      view: 'processing',
    })

    expect(screen.getByText(
      'Completed · Type not confirmed · Professional Review retained · Unassigned',
    )).toBeInTheDocument()
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
