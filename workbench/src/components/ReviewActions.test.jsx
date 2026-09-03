import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { HandoffResolution, SignalReviews, StaffActions } from './ReviewActions.jsx'

const handoff = {
  handoff_id: 'hnd_1',
  status: 'accepted',
  assigned_to: 'stf_1',
  requested_action: 'Continue the Claim with the claimant.',
  reason: 'The claimant requested staff assistance.',
  priority: 'high',
  packet: {
    incident_summary: 'Rear-end collision.',
    missing_items: ['other_party.registration'],
    pending_items: [],
    conflicts: [],
    source_refs: ['msg_1'],
    promised_next_step: 'A staff member will continue this Claim.',
  },
}

describe('review actions', () => {
  it('keeps handoff resolution split into an internal result and claimant update', async () => {
    const onResolve = vi.fn().mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<HandoffResolution handoff={handoff} profile={{ staff_id: 'stf_1' }} onResolve={onResolve} />)

    await user.click(screen.getByRole('button', { name: 'Record resolution' }))
    await user.type(screen.getByLabelText('Internal result summary'), 'The staff review is complete.')
    await user.type(screen.getByLabelText('Claimant update'), 'We have reviewed this with you and your Claim can continue.')
    await user.click(screen.getByRole('button', { name: 'Resolve handoff' }))

    expect(onResolve).toHaveBeenCalledWith(handoff, expect.objectContaining({
      result: expect.objectContaining({ summary: 'The staff review is complete.', source_refs: ['msg_1'] }),
      customer_update: expect.objectContaining({ summary: 'We have reviewed this with you and your Claim can continue.' }),
    }))
  })

  it('records a source-linked internal signal decision', async () => {
    const onDecision = vi.fn().mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<SignalReviews signals={[{ signal_id: 'sig_1', code: 'HISTORY_REVIEW', summary: 'Records may not match.' }]} onDecision={onDecision} />)

    await user.click(screen.getByText(/history review/i))
    await user.type(screen.getByLabelText('Reason code'), 'SOURCE_RECORD_NOT_COMPARABLE')
    await user.type(screen.getByLabelText('Decision summary'), 'The records concern different insured items.')
    await user.type(screen.getByLabelText('Evidence references'), 'his_1, pol_1')
    await user.click(screen.getByRole('button', { name: 'Record decision' }))

    expect(onDecision).toHaveBeenCalledWith('sig_1', {
      decision: 'dismissed',
      reason_codes: ['SOURCE_RECORD_NOT_COMPARABLE'],
      summary: 'The records concern different insured items.',
      evidence_refs: ['his_1', 'pol_1'],
    })
  })

  it('creates an audited staff action without claiming a state change', async () => {
    const onCreate = vi.fn().mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<StaffActions actions={[]} onCreate={onCreate} onUpdate={vi.fn()} />)

    await user.type(screen.getByLabelText('Action type'), 'coverage_review')
    await user.type(screen.getByLabelText('Requested outcome'), 'Review the policy wording.')
    await user.type(screen.getByLabelText('Source references'), 'pol_1')
    await user.click(screen.getByRole('button', { name: 'Create action' }))

    expect(onCreate).toHaveBeenCalledWith({
      action_type: 'coverage_review',
      requested_outcome: 'Review the policy wording.',
      source_refs: ['pol_1'],
    })
  })
})
