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

const handoffAction = {
  action_code: 'human.resolve_handoff',
  target_ref: 'hnd_1',
  label: 'Resolve handoff',
  availability: 'confirmation_required',
  confirmation: { message: 'This resolution updates the shared Claim context.' },
  inputs: [
    { field_code: 'result.summary', label: 'Internal result summary', control: 'textarea', required: true, choices: [] },
    { field_code: 'customer_update.summary', label: 'Claimant update', control: 'textarea', required: true, choices: [] },
  ],
  payload_defaults: {
    result: { outcome: 'support_completed', reason_codes: ['SUPPORT_NEED_MET'], source_refs: ['msg_1'] },
    state_changes: [{ path: 'claim_state.customer_support', to: 'self_service' }],
    customer_update: { responsible_party: 'claimant', related_refs: ['hnd_1'] },
  },
}

const signalAction = {
  action_code: 'signal.record_decision',
  target_ref: 'sig_1',
  availability: 'confirmation_required',
  confirmation: { message: 'This decision is audited.' },
  inputs: [
    { field_code: 'decision', label: 'Decision', control: 'select', required: true, choices: [{ value: 'dismissed', label: 'Dismiss signal' }] },
    { field_code: 'reason_codes.0', label: 'Reason', control: 'select', required: true, choices: [{ value: 'SOURCE_RECORD_NOT_COMPARABLE', label: 'Source record not comparable' }] },
    { field_code: 'summary', label: 'Decision summary', control: 'textarea', required: true, choices: [] },
  ],
  payload_defaults: { evidence_refs: ['his_1', 'pol_1'] },
}

describe('review actions', () => {
  it('keeps handoff resolution split into an internal result and claimant update', async () => {
    const onResolve = vi.fn().mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<HandoffResolution handoff={handoff} allowedAction={handoffAction} onResolve={onResolve} />)

    await user.click(screen.getByRole('button', { name: 'Record resolution' }))
    await user.type(screen.getByLabelText('Internal result summary'), 'The staff review is complete.')
    await user.type(screen.getByLabelText('Claimant update'), 'We have reviewed this with you and your Claim can continue.')
    await user.click(screen.getByRole('button', { name: 'Resolve handoff' }))

    expect(onResolve).toHaveBeenCalledWith(handoff, expect.objectContaining({
      result: expect.objectContaining({ summary: 'The staff review is complete.', source_refs: ['msg_1'] }),
      state_changes: [{ path: 'claim_state.customer_support', to: 'self_service' }],
      customer_update: expect.objectContaining({ summary: 'We have reviewed this with you and your Claim can continue.', responsible_party: 'claimant' }),
    }))
  })

  it('records a source-linked internal signal decision', async () => {
    const onDecision = vi.fn().mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<SignalReviews signals={[{ signal_id: 'sig_1', code: 'HISTORY_REVIEW', summary: 'Records may not match.' }]} allowedActions={[signalAction]} onDecision={onDecision} />)

    await user.click(screen.getByText(/history review/i))
    await user.type(screen.getByLabelText('Decision summary'), 'The records concern different insured items.')
    await user.click(screen.getByRole('button', { name: 'Record decision' }))

    expect(onDecision).toHaveBeenCalledWith('sig_1', {
      decision: 'dismissed',
      reason_codes: ['SOURCE_RECORD_NOT_COMPARABLE'],
      summary: 'The records concern different insured items.',
      evidence_refs: ['his_1', 'pol_1'],
    })
  })

  it('updates only the exact WorkItem action projected by the runtime', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined)
    const user = userEvent.setup()
    const action = {
      action_id: 'act_1', action_type: 'coverage_review', requested_outcome: 'Review policy.',
      status: 'open', assigned_to: 'stf_1', source_refs: ['pol_1'], created_at: '2026-09-03T01:00:00Z',
    }
    const allowedAction = {
      action_code: 'work_item.update', target_ref: 'act_1', availability: 'confirmation_required',
      confirmation: { message: 'The completion result is audited.' },
      inputs: [
        { field_code: 'status', label: 'Status', control: 'select', required: true, choices: [{ value: 'completed', label: 'Completed' }] },
        { field_code: 'result.summary', label: 'Result summary', control: 'textarea', required: false, required_when: { field_code: 'status', equals: 'completed' }, choices: [] },
      ],
      payload_defaults: {
        result: { outcome: 'professional_review_completed', reason_codes: ['POLICY_SECTION_CONFIRMED'], source_refs: ['pol_1'] },
        state_changes: [{ path: 'claim_state.coverage', to: 'clear' }], customer_update: null,
      },
    }
    render(<StaffActions actions={[action]} allowedActions={[allowedAction]} onUpdate={onUpdate} />)

    await user.click(screen.getByText('Coverage Review'))
    await user.type(screen.getByLabelText('Result summary'), 'The policy review is complete.')
    await user.click(screen.getByRole('button', { name: 'Update action' }))

    expect(onUpdate).toHaveBeenCalledWith('act_1', {
      status: 'completed',
      result: { outcome: 'professional_review_completed', reason_codes: ['POLICY_SECTION_CONFIRMED'], source_refs: ['pol_1'], summary: 'The policy review is complete.' },
      state_changes: [{ path: 'claim_state.coverage', to: 'clear' }],
      customer_update: null,
    })
  })

  it('prevents completed WorkItems from submitting an empty projected summary', async () => {
    const onUpdate = vi.fn().mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<StaffActions
      actions={[workItemRecord()]}
      allowedActions={[workItemUpdateAction()]}
      onUpdate={onUpdate}
    />)

    await user.click(screen.getByText('Claimant Support'))
    await user.selectOptions(screen.getByLabelText('Status'), 'completed')
    expect(screen.getByLabelText('Result summary')).toBeRequired()
    expect(screen.getByLabelText('Claimant update')).toBeRequired()
    await user.click(screen.getByRole('button', { name: 'Update action' }))

    expect(onUpdate).not.toHaveBeenCalled()
  })

  it.each(['in_progress', 'cancelled'])('allows %s without a completion summary', async (status) => {
    const onUpdate = vi.fn().mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<StaffActions
      actions={[workItemRecord()]}
      allowedActions={[workItemUpdateAction()]}
      onUpdate={onUpdate}
    />)

    await user.click(screen.getByText('Claimant Support'))
    await user.selectOptions(screen.getByLabelText('Status'), status)
    expect(screen.getByLabelText('Result summary')).not.toBeRequired()
    await user.click(screen.getByRole('button', { name: 'Update action' }))

    expect(onUpdate).toHaveBeenCalledWith('act_transition', {
      status,
      result: null,
      state_changes: [],
      customer_update: null,
    })
  })

  it('does not expose mutation controls with read-only Claim access', async () => {
    const action = {
      action_id: 'act_1',
      action_type: 'coverage_review',
      requested_outcome: 'Review the policy wording.',
      status: 'open',
      assigned_to: 'stf_owner',
      source_refs: [],
      created_at: '2026-09-03T01:00:00Z',
    }
    const user = userEvent.setup()
    render(<StaffActions actions={[action]} allowedActions={[]} onUpdate={vi.fn()} />)

    expect(screen.queryByRole('button', { name: 'Create action' })).not.toBeInTheDocument()
    await user.click(screen.getByText('Coverage Review'))
    expect(screen.queryByRole('button', { name: 'Update action' })).not.toBeInTheDocument()
    expect(screen.getByText(/no work-item update action is projected/i)).toBeVisible()
  })

  it('does not expose signal or handoff decisions without projected authority', async () => {
    const user = userEvent.setup()
    const { rerender } = render(<SignalReviews signals={[{ signal_id: 'sig_1', code: 'HISTORY_REVIEW' }]} onDecision={vi.fn()} />)

    await user.click(screen.getByText(/history review/i))
    expect(screen.queryByRole('button', { name: 'Record decision' })).not.toBeInTheDocument()
    expect(screen.getByText(/no signal-decision action is projected/i)).toBeVisible()

    rerender(<HandoffResolution handoff={handoff} allowedAction={undefined} onResolve={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Record resolution' })).not.toBeInTheDocument()
  })

  it('preserves exact blocked reasons for signal, WorkItem, and handoff actions', async () => {
    const user = userEvent.setup()
    const blockedSignal = { ...signalAction, availability: 'blocked', blocked_reason: 'A primary owner must decide this signal.' }
    const blockedWorkItem = { ...workItemUpdateAction(), availability: 'blocked', blocked_reason: 'This WorkItem is assigned to another professional.' }
    const { rerender } = render(<SignalReviews signals={[{ signal_id: 'sig_1', code: 'HISTORY_REVIEW' }]} allowedActions={[blockedSignal]} onDecision={vi.fn()} />)

    await user.click(screen.getByText(/history review/i))
    expect(screen.getByText('A primary owner must decide this signal.')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Record decision' })).not.toBeInTheDocument()

    rerender(<StaffActions actions={[workItemRecord()]} allowedActions={[blockedWorkItem]} onUpdate={vi.fn()} />)
    await user.click(screen.getByText('Claimant Support'))
    expect(screen.getByText('This WorkItem is assigned to another professional.')).toBeVisible()

    rerender(<HandoffResolution handoff={handoff} allowedAction={{ ...handoffAction, availability: 'blocked', blocked_reason: 'Resolve after the evidence review.' }} onResolve={vi.fn()} />)
    expect(screen.getByText('Resolve after the evidence review.')).toBeVisible()
    expect(screen.queryByRole('button', { name: 'Record resolution' })).not.toBeInTheDocument()
  })

  it('renders an available projected signal form as executable', async () => {
    const user = userEvent.setup()
    render(<SignalReviews signals={[{ signal_id: 'sig_1', code: 'HISTORY_REVIEW' }]} allowedActions={[{ ...signalAction, availability: 'available' }]} onDecision={vi.fn()} />)
    await user.click(screen.getByText(/history review/i))
    expect(screen.getByRole('button', { name: 'Record decision' })).toBeVisible()
  })
})

function workItemRecord() {
  return {
    action_id: 'act_transition',
    action_type: 'claimant_support',
    requested_outcome: 'Continue claimant support.',
    status: 'open',
    assigned_to: 'stf_1',
    source_refs: [],
    created_at: '2026-09-03T01:00:00Z',
  }
}

function workItemUpdateAction() {
  return {
    action_code: 'work_item.update',
    target_ref: 'act_transition',
    availability: 'confirmation_required',
    confirmation: { message: 'The selected status is audited.' },
    inputs: [
      {
        field_code: 'status',
        label: 'Status',
        control: 'select',
        required: true,
        choices: [
          { value: 'in_progress', label: 'In progress' },
          { value: 'completed', label: 'Completed' },
          { value: 'cancelled', label: 'Cancelled' },
        ],
      },
      {
        field_code: 'result.summary',
        label: 'Result summary',
        control: 'textarea',
        required: false,
        required_when: { field_code: 'status', equals: 'completed' },
        choices: [],
      },
      {
        field_code: 'customer_update.summary',
        label: 'Claimant update',
        control: 'textarea',
        required: false,
        required_when: { field_code: 'status', equals: 'completed' },
        choices: [],
      },
    ],
    payload_defaults: {
      result: {
        outcome: 'staff_work_completed',
        reason_codes: ['SUPPORT_NEED_MET'],
        source_refs: [],
      },
      state_changes: [],
      customer_update: {
        responsible_party: 'claimant',
        related_refs: ['act_transition'],
      },
    },
  }
}
