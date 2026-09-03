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

describe('QueuePanel', () => {
  it('uses backend tag codes for filtering while displaying staff labels', async () => {
    const onTag = vi.fn()
    const user = userEvent.setup()
    render(<QueuePanel claims={[claim]} loading={false} view="all" onView={vi.fn()} tagFilter="" tags={[tag]} onTag={onTag} nextCursor={null} onLoadMore={vi.fn()} onOpen={vi.fn()} />)

    expect(screen.getAllByText('Vehicle not drivable')).toHaveLength(2)
    await user.selectOptions(screen.getByLabelText('Staff tag'), tag.code)
    expect(onTag).toHaveBeenCalledWith(tag.code)
  })

  it('loads the next backend page only when a cursor is available', async () => {
    const onLoadMore = vi.fn()
    const user = userEvent.setup()
    render(<QueuePanel claims={[claim]} loading={false} view="all" onView={vi.fn()} tagFilter="" tags={[tag]} onTag={vi.fn()} nextCursor="cursor-2" onLoadMore={onLoadMore} onOpen={vi.fn()} />)

    await user.click(screen.getByRole('button', { name: 'Load more Claims' }))
    expect(onLoadMore).toHaveBeenCalledOnce()
  })
})
