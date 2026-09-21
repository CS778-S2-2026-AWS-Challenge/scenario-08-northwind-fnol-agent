import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { describe, expect, it, vi } from 'vitest'

import PayoutContactPanel from './PayoutContactPanel.jsx'

const account = {
  profile: {
    email: 'claimant@example.test',
    phone: '',
  },
}

const claim = {
  claim_id: 'clm_test',
  form: {},
  payment_destination_id: null,
}

describe('PayoutContactPanel', () => {
  it('saves a new protected payout account, clears plaintext, and continues with a usable contact method', async () => {
    const user = userEvent.setup()
    const onAddDestination = vi.fn().mockResolvedValue({
      payment_destination_id: 'pyd_1234567890abcdef1234',
      account_type: 'Everyday',
      masked_account_number: '***************6700',
      active: true,
    })
    const onContinue = vi.fn().mockResolvedValue({})

    const { rerender } = render(
      <PayoutContactPanel
        account={account}
        claim={claim}
        destinations={[]}
        loading={false}
        loadError=""
        busy={false}
        onAddDestination={onAddDestination}
        onContinue={onContinue}
        onManageContact={vi.fn()}
        onLogin={vi.fn()}
      />,
    )

    await user.type(screen.getByLabelText('Account type'), 'Everyday')
    await user.type(screen.getByLabelText('Bank account number'), '12-3456-1234567-00')
    await user.click(screen.getByRole('button', { name: 'Save payout account' }))

    expect(onAddDestination).toHaveBeenCalledWith({
      accountType: 'Everyday',
      accountNumber: '12-3456-1234567-00',
    })
    expect(screen.getByLabelText('Bank account number')).toHaveValue('')

    rerender(
      <PayoutContactPanel
        account={account}
        claim={claim}
        destinations={[{
          payment_destination_id: 'pyd_1234567890abcdef1234',
          account_type: 'Everyday',
          masked_account_number: '***************6700',
          active: true,
        }]}
        loading={false}
        loadError=""
        busy={false}
        onAddDestination={onAddDestination}
        onContinue={onContinue}
        onManageContact={vi.fn()}
        onLogin={vi.fn()}
      />,
    )

    expect(screen.queryByText('12-3456-1234567-00')).not.toBeInTheDocument()
    expect(screen.getByText('***************6700')).toBeInTheDocument()
    await user.click(screen.getByRole('radio', { name: /Email claimant@example.test/i }))
    await user.click(screen.getByRole('button', { name: 'Continue to agreement' }))
    expect(onContinue).toHaveBeenCalledWith({
      paymentDestinationId: 'pyd_1234567890abcdef1234',
      contactPreference: 'email',
    })
  })

  it('blocks phone and SMS when the profile has no phone destination', () => {
    render(
      <PayoutContactPanel
        account={account}
        claim={claim}
        destinations={[{
          payment_destination_id: 'pyd_1234567890abcdef1234',
          account_type: 'Everyday',
          masked_account_number: '***************6700',
          active: true,
        }]}
        loading={false}
        loadError=""
        busy={false}
        onAddDestination={vi.fn()}
        onContinue={vi.fn()}
        onManageContact={vi.fn()}
        onLogin={vi.fn()}
      />,
    )

    expect(screen.getByRole('radio', { name: /SMS .*Add this contact detail/i })).toBeDisabled()
    expect(screen.getByRole('radio', { name: /Phone call .*Add this contact detail/i })).toBeDisabled()
    expect(screen.getByRole('radio', { name: /In-app Northwind account messages/i })).toBeEnabled()
  })

  it('requires login before exposing protected payout controls', () => {
    const onLogin = vi.fn()
    render(
      <PayoutContactPanel
        account={null}
        claim={claim}
        destinations={[]}
        loading={false}
        loadError=""
        busy={false}
        onAddDestination={vi.fn()}
        onContinue={vi.fn()}
        onManageContact={vi.fn()}
        onLogin={onLogin}
      />,
    )

    expect(screen.queryByLabelText('Bank account number')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Log in to continue' })).toBeInTheDocument()
  })
})
