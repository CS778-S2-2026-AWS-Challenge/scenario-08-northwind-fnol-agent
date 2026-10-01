import { render, screen, waitFor, within } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'
import { ClaimDecisionControls, ClaimDecisionSummary } from './ClaimDecision.jsx'

const action = {
  action_code: 'claim.record_decision',
  target_type: 'claim',
  target_ref: 'clm_decision',
  label: 'Record Claim decision',
  purpose: 'Approve or reject this externally created Claim once.',
  availability: 'confirmation_required',
  confirmation: {
    level: 'high_impact',
    message: 'This final Claim decision cannot be changed in this version.',
  },
  based_on_revision: 7,
}

describe('ClaimDecisionControls', () => {
  it('renders controls only for the exact confirmation-required projected action', () => {
    const { rerender } = render(<ClaimDecisionControls action={action} onDecision={vi.fn()} />)

    expect(screen.getByRole('button', { name: 'Approve Claim' })).toBeVisible()
    expect(screen.getByRole('button', { name: 'Reject Claim' })).toBeVisible()

    rerender(<ClaimDecisionControls action={{ ...action, availability: 'blocked' }} onDecision={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Approve Claim' })).not.toBeInTheDocument()

    rerender(<ClaimDecisionControls action={{ ...action, action_code: 'claim.reopen' }} onDecision={vi.fn()} />)
    expect(screen.queryByRole('button', { name: 'Reject Claim' })).not.toBeInTheDocument()
  })

  it('submits an approval without an explanation and generates a fresh attempt key', async () => {
    const user = userEvent.setup()
    const onDecision = vi.fn().mockResolvedValue({ decision: 'approved' })
    render(<ClaimDecisionControls action={action} onDecision={onDecision} />)

    const trigger = screen.getByRole('button', { name: 'Approve Claim' })
    await user.click(trigger)
    expect(screen.getByRole('alertdialog')).toBeVisible()
    expect(screen.getByRole('button', { name: 'Cancel' })).toHaveFocus()
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Approve Claim' }))

    await waitFor(() => expect(onDecision).toHaveBeenCalledOnce())
    expect(onDecision).toHaveBeenCalledWith(
      action,
      { decision: 'approved' },
      expect.any(String),
      'clm_decision',
    )
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(trigger).toHaveFocus()
  })

  it('blocks a blank rejection reason and labels it as claimant-visible', async () => {
    const user = userEvent.setup()
    const onDecision = vi.fn()
    render(<ClaimDecisionControls action={action} onDecision={onDecision} />)

    await user.click(screen.getByRole('button', { name: 'Reject Claim' }))
    const explanation = screen.getByLabelText('Public rejection explanation')
    expect(screen.getByText('This text may be shown to the claimant.')).toBeVisible()
    await user.type(explanation, '   ')
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Reject Claim' }))

    expect(onDecision).not.toHaveBeenCalled()
    expect(screen.getByRole('alert')).toHaveTextContent('Enter a public rejection explanation.')
    expect(explanation).toHaveAttribute('aria-invalid', 'true')
  })

  it('reuses the exact payload and idempotency key for an explicit ambiguous retry', async () => {
    const user = userEvent.setup()
    const ambiguous = Object.assign(new Error('Connection interrupted.'), {
      code: 'NETWORK_ERROR',
      decisionRetryAllowed: true,
    })
    const onDecision = vi.fn()
      .mockRejectedValueOnce(ambiguous)
      .mockResolvedValueOnce({ decision: 'approved' })
    render(<ClaimDecisionControls action={action} onDecision={onDecision} />)

    await user.click(screen.getByRole('button', { name: 'Approve Claim' }))
    await user.type(screen.getByLabelText('Public approval explanation (optional)'), '  Approved after review.  ')
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Approve Claim' }))

    const retry = await screen.findByRole('button', { name: 'Retry same approval' })
    expect(screen.getByLabelText('Public approval explanation (optional)')).toBeDisabled()
    await user.click(retry)

    await waitFor(() => expect(onDecision).toHaveBeenCalledTimes(2))
    expect(onDecision.mock.calls[1][1]).toEqual(onDecision.mock.calls[0][1])
    expect(onDecision.mock.calls[1][2]).toBe(onDecision.mock.calls[0][2])
    expect(onDecision.mock.calls[0][1]).toEqual({
      decision: 'approved',
      claimant_explanation: 'Approved after review.',
    })
  })

  it('uses a new key after cancellation starts a new decision attempt', async () => {
    const user = userEvent.setup()
    const ambiguous = Object.assign(new Error('Connection interrupted.'), {
      code: 'NETWORK_ERROR',
      decisionRetryAllowed: true,
    })
    const onDecision = vi.fn()
      .mockRejectedValueOnce(ambiguous)
      .mockResolvedValueOnce({ decision: 'approved' })
    render(<ClaimDecisionControls action={action} onDecision={onDecision} />)

    await user.click(screen.getByRole('button', { name: 'Approve Claim' }))
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Approve Claim' }))
    await screen.findByRole('button', { name: 'Retry same approval' })
    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await user.click(screen.getByRole('button', { name: 'Approve Claim' }))
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Approve Claim' }))

    await waitFor(() => expect(onDecision).toHaveBeenCalledTimes(2))
    expect(onDecision.mock.calls[1][2]).not.toBe(onDecision.mock.calls[0][2])
  })

  it('creates a new key when corrected input becomes a new attempt after validation', async () => {
    const user = userEvent.setup()
    const validation = Object.assign(new Error('Use a claimant-safe explanation.'), {
      code: 'VALIDATION_ERROR',
    })
    const onDecision = vi.fn()
      .mockRejectedValueOnce(validation)
      .mockResolvedValueOnce({ decision: 'rejected' })
    render(<ClaimDecisionControls action={action} onDecision={onDecision} />)

    await user.click(screen.getByRole('button', { name: 'Reject Claim' }))
    const explanation = screen.getByLabelText('Public rejection explanation')
    await user.type(explanation, 'Not enough.')
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Reject Claim' }))
    expect(await screen.findByRole('alert')).toHaveTextContent('Use a claimant-safe explanation.')
    const firstKey = onDecision.mock.calls[0][2]

    await user.clear(explanation)
    await user.type(explanation, 'The submitted evidence does not establish coverage.')
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Reject Claim' }))

    await waitFor(() => expect(onDecision).toHaveBeenCalledTimes(2))
    expect(onDecision.mock.calls[1][2]).not.toBe(firstKey)
    expect(onDecision.mock.calls[1][1]).toEqual({
      decision: 'rejected',
      claimant_explanation: 'The submitted evidence does not establish coverage.',
    })
  })

  it('disables every submission control while the decision request is pending', async () => {
    const user = userEvent.setup()
    let resolveDecision
    const onDecision = vi.fn(() => new Promise((resolve) => { resolveDecision = resolve }))
    render(<ClaimDecisionControls action={action} onDecision={onDecision} />)

    await user.click(screen.getByRole('button', { name: 'Approve Claim' }))
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Approve Claim' }))

    expect(screen.getByRole('button', { name: 'Approving...' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeDisabled()
    expect(screen.getByLabelText('Public approval explanation (optional)')).toBeDisabled()
    expect(onDecision).toHaveBeenCalledOnce()

    resolveDecision({ decision: 'approved' })
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
  })

  it('closes and clears an old attempt when the Claim target changes', async () => {
    const user = userEvent.setup()
    const ambiguous = Object.assign(new Error('Connection interrupted.'), {
      code: 'NETWORK_ERROR',
      decisionRetryAllowed: true,
    })
    const onDecision = vi.fn().mockRejectedValueOnce(ambiguous).mockResolvedValueOnce({ decision: 'approved' })
    const { rerender } = render(<ClaimDecisionControls action={action} onDecision={onDecision} />)

    await user.click(screen.getByRole('button', { name: 'Approve Claim' }))
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Approve Claim' }))
    await screen.findByRole('button', { name: 'Retry same approval' })
    const oldKey = onDecision.mock.calls[0][2]

    const nextAction = { ...action, target_ref: 'clm_next', based_on_revision: 2 }
    rerender(<ClaimDecisionControls action={nextAction} onDecision={onDecision} />)
    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    await user.click(screen.getByRole('button', { name: 'Approve Claim' }))
    expect(screen.getByLabelText('Public approval explanation (optional)')).toHaveValue('')
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Approve Claim' }))

    await waitFor(() => expect(onDecision).toHaveBeenCalledTimes(2))
    expect(onDecision.mock.calls[1][2]).not.toBe(oldKey)
    expect(onDecision.mock.calls[1][3]).toBe('clm_next')
  })

  it('requires a new explicit confirmation after a revision conflict', async () => {
    const user = userEvent.setup()
    const conflict = Object.assign(new Error('Review revision 8.'), {
      code: 'REVISION_CONFLICT',
      decisionRequiresNewConfirmation: true,
    })
    const onDecision = vi.fn().mockRejectedValue(conflict)
    render(<ClaimDecisionControls action={action} onDecision={onDecision} />)

    await user.click(screen.getByRole('button', { name: 'Approve Claim' }))
    await user.click(within(screen.getByRole('alertdialog')).getByRole('button', { name: 'Approve Claim' }))

    await waitFor(() => expect(screen.queryByRole('alertdialog')).not.toBeInTheDocument())
    expect(onDecision).toHaveBeenCalledOnce()
  })
})

describe('ClaimDecisionSummary', () => {
  it('shows the authoritative public decision without rendering internal fields', () => {
    render(<ClaimDecisionSummary decision={{
      decision: 'rejected',
      claimant_explanation: 'The evidence did not establish coverage.',
      internal_note: 'Internal staff analysis must stay private.',
      decided_by: 'stf_demo',
      decided_at: '2026-10-01T01:00:00Z',
    }} />)

    expect(screen.getByRole('heading', { name: 'Claim rejected' })).toBeVisible()
    expect(screen.getByText('The evidence did not establish coverage.')).toBeVisible()
    expect(screen.queryByText('Internal staff analysis must stay private.')).not.toBeInTheDocument()
    expect(screen.queryByText('stf_demo')).not.toBeInTheDocument()
  })
})
