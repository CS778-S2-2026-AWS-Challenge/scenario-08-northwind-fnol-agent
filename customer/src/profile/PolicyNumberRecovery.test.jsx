import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const api = vi.hoisted(() => ({
  ApiRequestError: class ApiRequestError extends Error {},
  createAccountAsset: vi.fn(),
  createAccountIdentityDocument: vi.fn(),
  createAccountPolicy: vi.fn(),
  getAuthenticatedAccount: vi.fn(),
  listAccountAssets: vi.fn(),
  listAccountIdentityDocuments: vi.fn(),
  listAccountPaymentDestinations: vi.fn(),
  listAccountPolicies: vi.fn(),
  requestId: vi.fn(() => 'req_policy_recovery'),
  updateAccountAsset: vi.fn(),
  updateAccountIdentityDocument: vi.fn(),
  updateAccountPolicy: vi.fn(),
  updateAccountPreferences: vi.fn(),
  updateAccountProfile: vi.fn(),
}))

vi.mock('../api.js', () => api)

import UserProfile from '../components/UserProfile.jsx'
import useProfileController from './useProfileController.js'

const account = {
  customer_id: 'cus_policy_recovery',
  revision: 4,
  profile: {
    display_name: 'Iris',
    legal_name: 'Iris Zhang',
    preferred_name: 'Iris',
    email: 'iris@example.com',
  },
  preferences: { email: true, sms: false },
}

const policy = {
  policy_id: 'pol_11111111111111111111',
  policy_number: 'NTH-1234',
  revision: 1,
}

function emptyPage(items = []) {
  return { items, page: { next_cursor: null } }
}

// Renders Personal details through the real controller so the test follows the state
// transitions the hook produces, not hand-assembled resource snapshots.
function Harness() {
  const [currentAccount, setCurrentAccount] = useState(account)
  const controller = useProfileController({ account: currentAccount, setAccount: setCurrentAccount, enabled: true })
  return (
    <UserProfile
      account={currentAccount}
      activeSection="personal-details"
      controller={controller}
      onOpenClaims={() => {}}
      onSelectSection={() => {}}
      onSignOut={() => {}}
    />
  )
}

describe('policy number mutation recovery through the real controller', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listAccountAssets.mockResolvedValue(emptyPage())
    api.listAccountIdentityDocuments.mockResolvedValue(emptyPage())
    api.listAccountPaymentDestinations.mockResolvedValue(emptyPage())
    api.listAccountPolicies.mockResolvedValue(emptyPage([policy]))
  })

  it('moves focus to the preserved draft when a save enters readback and the readback fails, and again when a retry fails', async () => {
    const user = userEvent.setup()
    render(<Harness />)
    await screen.findByText('••••1234', { selector: '.profile-header-meta *' })

    await user.click(screen.getByText('View or edit policy number', { selector: 'summary' }))
    await user.click(screen.getByRole('button', { name: 'Edit policy number ••••1234' }))
    const input = screen.getByLabelText('Policy number', { selector: 'input' })
    await user.clear(input)
    await user.type(input, 'NTH-9876')

    let rejectReadback
    api.updateAccountPolicy.mockRejectedValueOnce({ code: 'NETWORK_ERROR' })
    api.listAccountPolicies.mockImplementationOnce(() => new Promise((_, reject) => { rejectReadback = reject }))

    const save = screen.getByRole('button', { name: 'Save policy number' })
    await user.click(save)
    await waitFor(() => expect(api.updateAccountPolicy).toHaveBeenCalledTimes(1))
    await waitFor(() => expect(rejectReadback).toBeTypeOf('function'))

    rejectReadback({ code: 'NETWORK_ERROR' })
    await screen.findByText(/could not confirm whether the policy-number update completed/)

    // The draft, Cancel and the retry control are all still rendered; focus must land on a usable one.
    expect(screen.getByRole('button', { name: 'Save policy number' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeEnabled()
    expect(input).toHaveValue('NTH-9876')
    expect(input).toBeEnabled()
    await waitFor(() => expect(input).toHaveFocus())

    api.listAccountPolicies.mockRejectedValueOnce({ code: 'NETWORK_ERROR' })
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(api.listAccountPolicies).toHaveBeenCalledTimes(3))
    await screen.findByRole('button', { name: 'Try again' })
    expect(screen.getByRole('button', { name: 'Save policy number' })).toBeDisabled()
    await waitFor(() => expect(input).toHaveFocus())

    api.listAccountPolicies.mockResolvedValueOnce(emptyPage([policy]))
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Save policy number' })).toBeEnabled())
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
    expect(input).toHaveValue('NTH-9876')
    await waitFor(() => expect(input).toHaveFocus())
  })

  it('keeps focus on a usable control when a retry without an open draft fails and then succeeds', async () => {
    const user = userEvent.setup()
    api.listAccountPolicies.mockReset()
    api.listAccountPolicies.mockRejectedValueOnce({ code: 'NETWORK_ERROR' })
    render(<Harness />)
    await screen.findByText('Unavailable', { selector: '.profile-header-meta *' })

    await user.click(screen.getByText('Add policy number — refresh failed', { selector: 'summary' }))
    api.listAccountPolicies.mockRejectedValueOnce({ code: 'NETWORK_ERROR' })
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    await waitFor(() => expect(api.listAccountPolicies).toHaveBeenCalledTimes(2))
    const retry = await screen.findByRole('button', { name: 'Try again' })
    await waitFor(() => expect(retry).toHaveFocus())

    api.listAccountPolicies.mockResolvedValueOnce(emptyPage([policy]))
    await user.click(retry)
    await screen.findByRole('button', { name: 'Edit policy number ••••1234' })
    expect(screen.queryByRole('button', { name: 'Try again' })).not.toBeInTheDocument()
    await waitFor(() => expect(screen.getByText('View or edit policy number', { selector: 'summary' })).toHaveFocus())
  })
})
