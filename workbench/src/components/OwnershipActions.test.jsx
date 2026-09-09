import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import OwnershipActions from './OwnershipActions.jsx'

const transferAction = {
  action_code: 'ownership.request_transfer',
  target_type: 'claim',
  target_ref: 'clm_1',
  label: 'Request transfer',
  purpose: 'Ask another staff member to become the primary owner.',
  availability: 'confirmation_required',
  confirmation: { message: 'Ownership changes only after the target staff member accepts.' },
  inputs: [
    { field_code: 'target_staff_id', label: 'Projected target colleague', control: 'text', required: true, choices: [] },
    { field_code: 'reason', label: 'Projected transfer reason', control: 'textarea', required: true, choices: [] },
  ],
}

describe('ownership actions', () => {
  it('renders and submits the exact projected ownership inputs', async () => {
    const onAction = vi.fn().mockResolvedValue(undefined)
    const user = userEvent.setup()
    render(<OwnershipActions actions={[transferAction]} onAction={onAction} />)

    await user.click(screen.getByText('Request transfer'))
    await user.type(screen.getByLabelText('Projected target colleague'), 'stf_target')
    await user.type(screen.getByLabelText('Projected transfer reason'), 'They own the next review.')
    await user.click(screen.getByRole('button', { name: 'Request transfer' }))

    expect(onAction).toHaveBeenCalledWith(transferAction, {
      target_staff_id: 'stf_target',
      reason: 'They own the next review.',
    })
  })

  it('keeps a blocked ownership action visible without a submit path', () => {
    render(<OwnershipActions actions={[{
      ...transferAction,
      action_code: 'ownership.requeue',
      label: 'Return to queue',
      purpose: 'Release primary ownership.',
      availability: 'blocked',
      blocked_reason: 'Complete or pause in-progress staff work before returning this Claim.',
      inputs: [{ field_code: 'reason', label: 'Reason', control: 'textarea', required: true, choices: [] }],
    }]} onAction={vi.fn()} />)

    expect(screen.getByText('Return to queue')).toBeVisible()
    expect(screen.getByText(/complete or pause in-progress staff work/i)).toBeVisible()
    expect(screen.queryByRole('button', { name: /return to queue/i })).not.toBeInTheDocument()
  })
})
