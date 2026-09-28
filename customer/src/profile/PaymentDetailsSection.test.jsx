import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import { ProfileMutationError } from './profileMutation.js'
import PaymentDetailsSection from './PaymentDetailsSection.jsx'

const commonDestination = {
  payment_destination_id: 'pyd_11111111111111111111',
  account_type: 'everyday',
  bank_name: 'Northwind Bank',
  account_holder_name: 'Synthetic Claimant',
  is_common: true,
  masked_account_number: '•••• 4321',
  revision: 2,
}

function PaymentHarness({ initialDestinations = [], onCreate = vi.fn(), onUpdate = vi.fn() }) {
  const [destinations, setDestinations] = useState(initialDestinations)
  return (
    <PaymentDetailsSection
      resource={{ items: destinations, error: '', loading: false, stale: false }}
      pending={{}}
      onBeginCreate={() => 'payment-attempt-1'}
      onAbandonCreate={vi.fn()}
      onCreate={async (request) => {
        const saved = await onCreate(request)
        setDestinations((current) => [saved, ...current.filter(({ payment_destination_id: id }) => id !== saved.payment_destination_id)])
        return saved
      }}
      onReload={vi.fn()}
      onUpdate={async (...args) => {
        const saved = await onUpdate(...args)
        setDestinations((current) => current.map((destination) => (
          destination.payment_destination_id === saved.payment_destination_id ? saved : destination
        )))
        return saved
      }}
    />
  )
}

describe('PaymentDetailsSection', () => {
  it('creates one common destination and never redisplays the plaintext number', async () => {
    const user = userEvent.setup()
    const onCreate = vi.fn().mockResolvedValue({ ...commonDestination, revision: 1 })
    render(<PaymentHarness onCreate={onCreate} />)

    expect(screen.queryByText('Saved accounts')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Add payment details' }))
    expect(screen.getByLabelText('Bank')).toHaveFocus()
    await user.type(screen.getByLabelText('Bank'), 'Northwind Bank')
    await user.type(screen.getByLabelText('Account holder'), 'Synthetic Claimant')
    await user.type(screen.getByLabelText('Account type'), 'everyday')
    await user.type(screen.getByLabelText('Bank account number'), '12-3456-0789012-00')
    await user.click(screen.getByRole('button', { name: 'Save payment details' }))

    await waitFor(() => expect(onCreate).toHaveBeenCalledWith({
      bankName: 'Northwind Bank',
      accountHolderName: 'Synthetic Claimant',
      accountType: 'everyday',
      accountNumber: '12-3456-0789012-00',
      attemptId: 'payment-attempt-1',
    }))
    expect(await screen.findByText('Everyday •••• 4321')).toBeInTheDocument()
    expect(screen.queryByDisplayValue('12-3456-0789012-00')).not.toBeInTheDocument()
    expect(screen.queryByText('Saved accounts')).not.toBeInTheDocument()
  })

  it('edits projected names without pre-filling or replacing the protected account number', async () => {
    const user = userEvent.setup()
    const updated = { ...commonDestination, bank_name: 'Updated Bank', revision: 3 }
    const onUpdate = vi.fn().mockResolvedValue(updated)
    render(<PaymentHarness initialDestinations={[commonDestination]} onUpdate={onUpdate} />)

    await user.click(screen.getByRole('button', { name: 'Edit payment details' }))
    expect(screen.getByLabelText('Bank')).toHaveValue('Northwind Bank')
    expect(screen.getByLabelText(/Bank account number/)).toHaveValue('')
    await user.clear(screen.getByLabelText('Bank'))
    await user.type(screen.getByLabelText('Bank'), 'Updated Bank')
    await user.click(screen.getByRole('button', { name: 'Save payment details' }))

    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith(
      commonDestination.payment_destination_id,
      2,
      {
        bankName: 'Updated Bank',
        accountHolderName: 'Synthetic Claimant',
        accountType: 'everyday',
        isCommon: true,
      },
    ))
    expect(await screen.findByText('Updated Bank')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit payment details' })).toHaveFocus()
  })

  it('requires an explicit choice when legacy records have no common destination', async () => {
    const user = userEvent.setup()
    const legacy = { ...commonDestination, is_common: false }
    const selected = { ...legacy, is_common: true, revision: 3 }
    const onUpdate = vi.fn().mockResolvedValue(selected)
    render(<PaymentHarness initialDestinations={[legacy]} onUpdate={onUpdate} />)

    expect(screen.getByText('Choose a Claim payment destination')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Edit payment details' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Use for Claims' }))

    await waitFor(() => expect(onUpdate).toHaveBeenCalledWith(legacy.payment_destination_id, 2, { isCommon: true }))
    expect(await screen.findByRole('button', { name: 'Edit payment details' })).toBeInTheDocument()
  })

  it('keeps protected edits in the form when an ambiguous save cannot be confirmed', async () => {
    const user = userEvent.setup()
    const onUpdate = vi.fn().mockRejectedValue(new ProfileMutationError(
      'Northwind could not confirm that the payment update completed. Your draft is still here.',
      { code: 'NETWORK_ERROR', kind: 'unknown' },
    ))
    render(<PaymentHarness initialDestinations={[commonDestination]} onUpdate={onUpdate} />)

    await user.click(screen.getByRole('button', { name: 'Edit payment details' }))
    await user.type(screen.getByLabelText(/Bank account number/), '12-3456-0000000-00')
    await user.click(screen.getByRole('button', { name: 'Save payment details' }))

    expect(await screen.findByRole('alert')).toHaveTextContent('could not confirm')
    expect(screen.getByLabelText(/Bank account number/)).toHaveValue('12-3456-0000000-00')
  })
})
