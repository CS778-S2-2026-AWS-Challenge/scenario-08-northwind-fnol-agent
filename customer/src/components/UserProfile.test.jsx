import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import UserProfile from './UserProfile.jsx'

const account = {
  profile: {
    display_name: 'Iris',
    legal_name: 'Iris Zhang',
    preferred_name: 'Iris',
    date_of_birth: '1990-04-12',
    email: 'iris@gmail.com',
    phone: '+64 21 555 123',
    residential_address: '1 Queen Street, Auckland',
  },
  preferences: { email: true, sms: false },
}

const vehicleAsset = {
  asset_id: 'ase_11111111111111111111',
  asset_type: 'vehicle',
  display_name: 'Family SUV',
  details: {
    registration: 'ABC123',
    registered_owner: 'Iris Zhang',
    make: 'Toyota',
    model: 'RAV4',
    year: 2022,
  },
  revision: 2,
  active: true,
  created_at: '2026-09-12T01:00:00Z',
  updated_at: '2026-09-17T01:00:00Z',
}

const policy = {
  policy_id: 'pol_11111111111111111111',
  policy_number: 'NTH-1234',
  revision: 2,
}

function profileController(policyResource, overrides = {}) {
  return {
    resources: {
      assets: { items: [], error: '', loading: false, stale: false },
      policies: policyResource,
      payments: { items: [], error: '', loading: false, stale: false },
      identities: { items: [], error: '', loading: false, stale: false },
    },
    pending: {},
    beginCreate: vi.fn().mockReturnValue('policy-attempt-1'),
    abandonCreate: vi.fn(),
    saveProfile: vi.fn().mockResolvedValue(account),
    savePreferences: vi.fn().mockResolvedValue(account),
    createAsset: vi.fn(),
    saveAsset: vi.fn(),
    createPolicy: vi.fn().mockResolvedValue(policy),
    savePolicy: vi.fn().mockResolvedValue(policy),
    createIdentity: vi.fn(),
    saveIdentity: vi.fn(),
    reloadAssets: vi.fn().mockResolvedValue([]),
    reloadPolicies: vi.fn().mockResolvedValue(policyResource.items || []),
    reloadPayments: vi.fn().mockResolvedValue([]),
    reloadIdentities: vi.fn().mockResolvedValue([]),
    ...overrides,
  }
}

function ProfileHarness({ initialSection = null, profileProps }) {
  const [activeSection, setActiveSection] = useState(initialSection)
  const [currentAccount, setCurrentAccount] = useState(profileProps.account)

  return (
    <UserProfile
      {...profileProps}
      account={currentAccount}
      activeSection={activeSection}
      onSaveProfile={async (profile) => {
        const updated = await profileProps.onSaveProfile(profile)
        setCurrentAccount(updated)
        return updated
      }}
      onSavePreferences={async (preferences) => {
        const updated = await profileProps.onSavePreferences(preferences)
        setCurrentAccount(updated)
        return updated
      }}
      onSelectSection={(section) => {
        profileProps.onSelectSection(section)
        setActiveSection(section)
      }}
    />
  )
}

function renderProfile(overrides = {}, initialSection = null) {
  const props = {
    account,
    assets: [],
    onCreateAsset: vi.fn(),
    onOpenClaims: vi.fn(),
    onReloadAssets: vi.fn().mockResolvedValue([]),
    onSaveProfile: vi.fn().mockResolvedValue(account),
    onSavePreferences: vi.fn().mockResolvedValue(account),
    onSelectSection: vi.fn(),
    onSignOut: vi.fn(),
    onUpdateAsset: vi.fn(),
    ...overrides,
  }
  const view = render(<ProfileHarness initialSection={initialSection} profileProps={props} />)
  return { ...props, container: view.container }
}

describe('UserProfile', () => {
  it('shows one Profile category at a time and keeps unsupported capabilities honest', async () => {
    const user = userEvent.setup()
    const props = renderProfile()

    expect(screen.getByRole('region', { name: 'Personal details' })).toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Personal details' })).not.toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Personal information' })).toBeInTheDocument()
    expect(screen.queryByText('Account summary')).not.toBeInTheDocument()
    expect(screen.queryByText('Review the information Northwind can currently show for this account.')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'My profile' })).not.toBeInTheDocument()
    expect(screen.getAllByRole('button', { name: 'Personal details' })).toHaveLength(2)
    expect(screen.queryByRole('button', { name: 'Policies' })).not.toBeInTheDocument()
    expect(screen.getByText('i•••@gmail.com')).toBeInTheDocument()
    expect(screen.getByText('••• ••• 123')).toBeInTheDocument()
    expect(screen.getByText('Policy number')).toBeInTheDocument()
    expect(screen.getByText('Not provided', { selector: '.profile-header-meta > strong' })).toBeInTheDocument()
    expect(screen.getByText('Add policy number', { selector: 'summary' })).toBeInTheDocument()
    expect(screen.queryByText(/^Saved$/)).not.toBeInTheDocument()
    expect(screen.getByText('Iris', { selector: '.profile-header-copy > strong' }).closest('.profile-header')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit profile' }).closest('.profile-header')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit personal information' }).closest('.profile-personal-information-heading')).toBeInTheDocument()
    expect(screen.getByText('Legal name').closest('.profile-personal-information')).toBeInTheDocument()
    expect(props.container.querySelector('.profile-sidebar .profile-header')).not.toBeInTheDocument()
    expect(props.container.querySelector('.profile-sidebar')).toHaveTextContent('Claim history')
    expect(props.container.querySelector('.profile-sidebar')).not.toHaveTextContent('Evidence history')
    expect(screen.getAllByRole('button', { name: 'Claim history' })).toHaveLength(2)
    expect(screen.queryByRole('button', { name: 'Evidence history' })).not.toBeInTheDocument()
    expect(props.container.querySelector('.profile-sidebar')).not.toHaveTextContent('Log out')
    expect(props.container.querySelector('.profile-footer')).toHaveTextContent('Log out')

    await user.click(screen.getAllByRole('button', { name: 'Insured assets' })[0])

    expect(props.onSelectSection).toHaveBeenCalledWith('insured-assets')
    expect(screen.getByRole('heading', { name: 'Insured assets' })).toBeInTheDocument()
    expect(screen.queryByRole('region', { name: 'Personal details' })).not.toBeInTheDocument()
    expect(props.container.querySelector('.profile-availability-note')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Vehicles/ })).not.toHaveAttribute('aria-expanded')
    expect(screen.getByRole('button', { name: /^Properties/ })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: /^Valuable items/ })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Add vehicle' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /^Vehicles/ }))
    expect(screen.getByRole('heading', { name: 'Vehicles' })).toBeInTheDocument()
    expect(screen.getByText('0 saved')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Back to Insured assets' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Add vehicle' })).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /^Properties/ })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /add policy/i })).not.toBeInTheDocument()
    expect(screen.queryByRole('button', { name: /edit avatar/i })).not.toBeInTheDocument()

    await user.click(screen.getAllByRole('button', { name: 'Payment details' })[0])
    expect(screen.getByRole('heading', { name: 'Payment details' })).toBeInTheDocument()
    expect(screen.getByText('Bank account to receive claim payments')).toBeInTheDocument()
    expect(screen.queryByText('Bank account for claim payments')).not.toBeInTheDocument()
    expect(screen.queryByText('This information is not supported by the current account service.')).not.toBeInTheDocument()
    expect(screen.queryByText(/Used only when a claim payment needs to be made/)).not.toBeInTheDocument()
    expect(props.container.querySelector('.profile-availability-note')).not.toBeInTheDocument()
    expect(screen.getAllByText('Not supported')).toHaveLength(2)
    expect(screen.getByText('Not designated')).toBeInTheDocument()

    await user.click(screen.getAllByRole('button', { name: 'Claim auto-fill' })[0])
    expect(screen.getByText(/must review and confirm it before it becomes claim information/i)).toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
    expect(screen.getAllByText('Not configured')).toHaveLength(5)
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument()
  })

  it('shows and edits the account policy number through Personal details disclosure', async () => {
    const user = userEvent.setup()
    const savePolicy = vi.fn().mockResolvedValue({ ...policy, policy_number: 'NTH-9876', revision: 3 })
    const controller = profileController(
      { items: [policy], error: '', loading: false, stale: false },
      { savePolicy },
    )
    renderProfile({ controller }, 'personal-details')

    expect(screen.getByText('••••1234', { selector: '.profile-header-meta > strong' })).toBeInTheDocument()
    await user.click(screen.getByText('View or edit policy number', { selector: 'summary' }))
    await user.click(screen.getByRole('button', { name: 'Edit policy number ••••1234' }))

    const input = screen.getByLabelText('Policy number', { selector: 'input' })
    expect(input).toHaveFocus()
    await user.clear(input)
    await user.type(input, 'NTH-9876')
    await user.click(screen.getByRole('button', { name: 'Save policy number' }))

    expect(savePolicy).toHaveBeenCalledWith(policy.policy_id, policy.revision, 'NTH-9876')
    expect(await screen.findByText(/Policy number ••••9876 was saved/)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Edit policy number ••••1234' })).toHaveFocus())
  })

  it('adds an account policy number through the Personal details disclosure', async () => {
    const user = userEvent.setup()
    const createPolicy = vi.fn().mockResolvedValue(policy)
    const controller = profileController(
      { items: [], error: '', loading: false, stale: false },
      { createPolicy },
    )
    renderProfile({ controller }, 'personal-details')

    await user.click(screen.getByText('Add policy number', { selector: 'summary' }))
    await user.click(screen.getByRole('button', { name: 'Add policy number' }))

    const input = screen.getByLabelText('Policy number', { selector: 'input' })
    expect(input).toHaveFocus()
    await user.type(input, 'NTH-1234')
    await user.click(screen.getByRole('button', { name: 'Save policy number' }))

    expect(createPolicy).toHaveBeenCalledWith({
      policyNumber: 'NTH-1234',
      attemptId: 'policy-attempt-1',
    })
    expect(await screen.findByText(/Policy number ••••1234 was saved/)).toBeInTheDocument()
    await waitFor(() => expect(screen.getByRole('button', { name: 'Add policy number' })).toHaveFocus())
  })

  it('keeps Personal details forms mutually exclusive and returns focus after policy cancellation', async () => {
    const user = userEvent.setup()
    const controller = profileController({
      items: [policy], error: '', loading: false, stale: false,
    })
    renderProfile({ controller }, 'personal-details')

    await user.click(screen.getByText('View or edit policy number', { selector: 'summary' }))
    await user.click(screen.getByRole('button', { name: 'Edit profile' }))
    expect(screen.getByRole('button', { name: 'Edit policy number ••••1234' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Save profile' })).toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Done' }))
    await user.click(screen.getByRole('button', { name: 'Edit policy number ••••1234' }))
    expect(screen.getByRole('button', { name: 'Edit profile' })).toBeDisabled()
    expect(screen.getByRole('button', { name: 'Edit personal information' })).toBeDisabled()
    expect(screen.queryByRole('button', { name: 'Save profile' })).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.getByRole('button', { name: 'Edit policy number ••••1234' })).toHaveFocus())
  })

  it('keeps the active policy draft recoverable through retained loading and failure', async () => {
    const user = userEvent.setup()
    const sharedProps = {
      account,
      activeSection: 'personal-details',
      onCreateAsset: vi.fn(),
      onOpenClaims: vi.fn(),
      onReloadAssets: vi.fn(),
      onSaveProfile: vi.fn().mockResolvedValue(account),
      onSavePreferences: vi.fn().mockResolvedValue(account),
      onSelectSection: vi.fn(),
      onSignOut: vi.fn(),
      onUpdateAsset: vi.fn(),
    }
    const view = (resource) => <UserProfile {...sharedProps} controller={profileController(resource)} />
    const { rerender } = render(view({ items: [policy], error: '', loading: false, stale: false }))

    await user.click(screen.getByText('View or edit policy number', { selector: 'summary' }))
    await user.click(screen.getByRole('button', { name: 'Edit policy number ••••1234' }))
    const input = screen.getByLabelText('Policy number', { selector: 'input' })
    expect(input).toHaveFocus()

    rerender(view({ items: [policy], error: '', loading: true, stale: true }))
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Save policy number' })).toBeDisabled()
    expect(input).toHaveFocus()

    rerender(view({ items: [policy], error: 'Reload failed.', loading: false, stale: true }))
    expect(screen.getByRole('button', { name: 'Cancel' })).toBeInTheDocument()
    expect(screen.getByText(/Reload failed/)).toBeInTheDocument()
    expect(input).toHaveFocus()

    await user.click(screen.getByRole('button', { name: 'Cancel' }))
    await waitFor(() => expect(screen.getByText('View or edit policy number — refresh failed', { selector: 'summary' })).toHaveFocus())
    expect(screen.getByRole('button', { name: 'Edit profile' })).not.toBeDisabled()
  })

  it('announces collapsed policy loading, completion, and failure once', async () => {
    const user = userEvent.setup()
    const sharedProps = {
      account,
      activeSection: 'personal-details',
      onCreateAsset: vi.fn(),
      onOpenClaims: vi.fn(),
      onReloadAssets: vi.fn(),
      onSaveProfile: vi.fn().mockResolvedValue(account),
      onSavePreferences: vi.fn().mockResolvedValue(account),
      onSelectSection: vi.fn(),
      onSignOut: vi.fn(),
      onUpdateAsset: vi.fn(),
    }
    const view = (resource) => <UserProfile {...sharedProps} controller={profileController(resource)} />
    const { rerender } = render(view({ items: null, error: '', loading: true, stale: false }))

    const liveStatus = screen.getByRole('status', { name: 'Policy number status' })
    expect(liveStatus).toHaveAttribute('aria-live', 'polite')
    expect(liveStatus).toHaveAttribute('aria-atomic', 'true')
    expect(liveStatus).toHaveTextContent('Loading…')

    rerender(view({ items: [policy], error: '', loading: false, stale: false }))
    expect(liveStatus).toHaveTextContent('••••1234')
    await user.click(screen.getByText('View or edit policy number', { selector: 'summary' }))

    rerender(view({ items: [policy], error: 'Reload failed.', loading: false, stale: true }))
    expect(liveStatus).toHaveTextContent('••••1234 · Could not refresh')
    expect(screen.getAllByRole('status')).toEqual([liveStatus])
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
    expect(screen.getByText(/Reload failed/)).toBeInTheDocument()
  })

  it('keeps every historical policy record visible without inventing a primary policy', async () => {
    const user = userEvent.setup()
    const secondPolicy = { ...policy, policy_id: 'pol_22222222222222222222', policy_number: 'NTH-5678' }
    const controller = profileController({
      items: [policy, secondPolicy], error: '', loading: false, stale: false,
    })
    renderProfile({ controller }, 'personal-details')

    expect(screen.getByText('2 policy numbers saved', { selector: '.profile-header-meta > strong' })).toBeInTheDocument()
    await user.click(screen.getByText('View or edit policy number', { selector: 'summary' }))
    expect(screen.getByText('••••1234')).toBeInTheDocument()
    expect(screen.getByText('••••5678')).toBeInTheDocument()
  })

  it('labels a retained policy number when its refresh fails', async () => {
    const user = userEvent.setup()
    const controller = profileController({
      items: [policy], error: 'Reload failed.', loading: false, stale: true,
    })
    renderProfile({ controller }, 'personal-details')

    expect(screen.getByText('••••1234 · Could not refresh', { selector: '.profile-header-meta > strong' })).toBeInTheDocument()
    await user.click(screen.getByText('View or edit policy number — refresh failed', { selector: 'summary' }))
    expect(screen.getByText(/Reload failed/)).toBeInTheDocument()
    expect(screen.getByText('••••1234')).toBeInTheDocument()
  })

  it('labels retained policy records while a refresh is running', async () => {
    const user = userEvent.setup()
    const secondPolicy = { ...policy, policy_id: 'pol_22222222222222222222', policy_number: 'NTH-5678' }
    const controller = profileController({
      items: [policy, secondPolicy], error: '', loading: true, stale: false,
    })
    renderProfile({ controller }, 'personal-details')

    expect(screen.getByText('2 policy numbers saved · Refreshing…', { selector: '.profile-header-meta > strong' })).toBeInTheDocument()
    await user.click(screen.getByText('View or edit policy number — refreshing', { selector: 'summary' }))
    expect(screen.getByText('••••1234')).toBeInTheDocument()
    expect(screen.getByText('••••5678')).toBeInTheDocument()
  })

  it('keeps policy loading and retryable errors inside Personal details', async () => {
    const user = userEvent.setup()
    const reloadPolicies = vi.fn().mockResolvedValue([])
    const controller = profileController(
      { items: null, error: 'Northwind could not load saved policy numbers. Reload this section and try again.', loading: false, stale: false },
      { reloadPolicies },
    )
    renderProfile({ controller }, 'personal-details')

    expect(screen.getByText('Unavailable', { selector: '.profile-header-meta > strong' })).toBeInTheDocument()
    await user.click(screen.getByText('Add policy number — refresh failed', { selector: 'summary' }))
    expect(screen.getByText(/could not load saved policy numbers/)).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Try again' }))
    expect(reloadPolicies).toHaveBeenCalledTimes(1)
  })

  it('shows policy loading feedback inside Personal details', async () => {
    const user = userEvent.setup()
    const controller = profileController({
      items: null, error: '', loading: true, stale: false,
    })
    renderProfile({ controller }, 'personal-details')

    expect(screen.getByText('Loading…', { selector: '.profile-header-meta > strong' })).toBeInTheDocument()
    await user.click(screen.getByText('Add policy number — loading', { selector: 'summary' }))
    expect(screen.getByText('Loading saved policy numbers…')).toBeInTheDocument()
  })

  it('shows the prepared Claim choices only when account-backed handlers are supplied', async () => {
    const user = userEvent.setup()
    const onChangeAutoFillChoice = vi.fn()
    const onSaveAutoFillChoices = vi.fn()
    renderProfile({
      autoFillChoices: [
        { key: 'a', label: 'Personal details', visible: false },
        { key: 'b', label: 'Policy number', visible: false },
        { key: 'c', label: 'Saved assets', visible: false },
        { key: 'd', label: 'Payment details', visible: false },
        { key: 'e', label: 'Identity information', visible: false },
      ],
      autoFillDirty: true,
      onChangeAutoFillChoice,
      onSaveAutoFillChoices,
    }, 'claim-auto-fill')

    expect(screen.queryByText('Not configured')).not.toBeInTheDocument()
    expect(screen.getAllByRole('combobox')).toHaveLength(5)
    await user.selectOptions(screen.getByRole('combobox', { name: 'Saved assets' }), 'show')
    expect(onChangeAutoFillChoice).toHaveBeenCalledWith('c', true)
    await user.click(screen.getByRole('button', { name: 'Save Claim auto-fill choices' }))
    expect(onSaveAutoFillChoices).toHaveBeenCalledTimes(1)
  })

  it('updates the preferred name without changing the legal name', async () => {
    const user = userEvent.setup()
    const updatedAccount = {
      ...account,
      profile: { ...account.profile, display_name: 'Iris Liu', preferred_name: 'Iris Liu' },
    }
    const onSaveProfile = vi.fn().mockResolvedValue(updatedAccount)
    renderProfile({ onSaveProfile }, 'personal-details')

    await user.click(screen.getByRole('button', { name: 'Edit profile' }))
    const name = screen.getByLabelText('Preferred name')
    expect(name).toHaveFocus()
    await user.clear(name)
    await user.type(name, 'Iris Liu')
    expect(screen.queryByLabelText(/Phone number/)).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Contact preferences' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save profile' }))

    expect(onSaveProfile).toHaveBeenCalledWith({ preferred_name: 'Iris Liu' })
    expect(await screen.findByText(/updated in your saved Northwind account/)).toBeInTheDocument()
    expect(screen.getByText('Iris Liu', { selector: '.profile-header-copy > strong' })).toBeInTheDocument()
    expect(screen.getByText('Iris Zhang', { selector: '.profile-summary-row > dd' })).toBeInTheDocument()
    expect(screen.queryByLabelText('Preferred name')).not.toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit profile' })).toHaveFocus()
  })

  it('clears the preferred name with an explicit null value', async () => {
    const user = userEvent.setup()
    const updatedAccount = {
      ...account,
      profile: { ...account.profile, display_name: 'Iris Zhang', preferred_name: null },
    }
    const onSaveProfile = vi.fn().mockResolvedValue(updatedAccount)
    renderProfile({ onSaveProfile }, 'personal-details')

    await user.click(screen.getByRole('button', { name: 'Edit profile' }))
    await user.clear(screen.getByLabelText('Preferred name'))
    await user.click(screen.getByRole('button', { name: 'Save profile' }))

    expect(onSaveProfile).toHaveBeenCalledWith({ preferred_name: null })
    expect(await screen.findByText('Not provided', { selector: '.profile-header-copy > strong' })).toBeInTheDocument()
    expect(screen.getByText('Iris Zhang', { selector: '.profile-summary-row > dd' })).toBeInTheDocument()
  })

  it('does not show the legal-name projection as an unset preferred name', () => {
    renderProfile({
      account: {
        ...account,
        profile: { ...account.profile, display_name: 'Iris Zhang', preferred_name: null },
      },
    }, 'personal-details')

    expect(screen.getByText('Not provided', { selector: '.profile-header-copy > strong' })).toBeInTheDocument()
    expect(screen.getByText('Iris Zhang', { selector: '.profile-summary-row > dd' })).toBeInTheDocument()
  })

  it('edits personal identity and address fields through the account projection', async () => {
    const user = userEvent.setup()
    const updatedAccount = {
      ...account,
      profile: {
        ...account.profile,
        legal_name: 'Iris Zhang-Smith',
        date_of_birth: '1991-05-23',
        email: 'iris.smith@example.com',
        residential_address: '22 Harbour Road, Auckland',
      },
    }
    const secondAccount = {
      ...updatedAccount,
      profile: { ...updatedAccount.profile, residential_address: '30 Harbour Road, Auckland' },
    }
    const onSaveProfile = vi.fn()
      .mockResolvedValueOnce(updatedAccount)
      .mockResolvedValueOnce(secondAccount)
    renderProfile({ onSaveProfile }, 'personal-details')

    await user.click(screen.getByRole('button', { name: 'Edit personal information' }))
    expect(screen.getByLabelText('Legal name')).toHaveValue('Iris Zhang')
    expect(screen.getByLabelText('Date of birth')).toHaveValue('1990-04-12')
    expect(screen.getByLabelText('Email')).toHaveValue('iris@gmail.com')
    expect(screen.getByLabelText(/Residential address/)).toHaveValue('1 Queen Street, Auckland')

    await user.clear(screen.getByLabelText('Legal name'))
    await user.type(screen.getByLabelText('Legal name'), 'Iris Zhang-Smith')
    await user.clear(screen.getByLabelText('Date of birth'))
    await user.type(screen.getByLabelText('Date of birth'), '1991-05-23')
    await user.clear(screen.getByLabelText('Email'))
    await user.type(screen.getByLabelText('Email'), 'iris.smith@example.com')
    await user.clear(screen.getByLabelText(/Residential address/))
    await user.type(screen.getByLabelText(/Residential address/), '22 Harbour Road, Auckland')
    await user.click(screen.getByRole('button', { name: 'Save personal information' }))

    expect(onSaveProfile).toHaveBeenCalledWith({
      legal_name: 'Iris Zhang-Smith',
      date_of_birth: '1991-05-23',
      email: 'iris.smith@example.com',
      phone: '+64 21 555 123',
      residential_address: '22 Harbour Road, Auckland',
    })
    expect(await screen.findByText(/Profile information was updated/)).toBeInTheDocument()
    expect(screen.getByText('Iris', { selector: '.profile-header-copy > strong' })).toBeInTheDocument()
    expect(screen.getByText('Iris Zhang-Smith', { selector: '.profile-summary-row > dd' })).toBeInTheDocument()
    expect(screen.getByText('22 Harbour Road, Auckland')).toBeInTheDocument()
    expect(screen.queryByRole('button', { name: 'Save personal information' })).not.toBeInTheDocument()

    const editButton = screen.getByRole('button', { name: 'Edit personal information' })
    expect(editButton).toHaveFocus()
    await user.click(editButton)
    const address = screen.getByLabelText(/Residential address/)
    expect(address).toHaveValue('22 Harbour Road, Auckland')
    await user.clear(address)
    await user.type(address, '30 Harbour Road, Auckland')
    await user.click(screen.getByRole('button', { name: 'Save personal information' }))

    expect(onSaveProfile).toHaveBeenCalledTimes(2)
    expect(onSaveProfile).toHaveBeenLastCalledWith(expect.objectContaining({
      residential_address: '30 Harbour Road, Auckland',
    }))
    expect(await screen.findByText('30 Harbour Road, Auckland')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit personal information' })).toBeInTheDocument()
  })

  it('keeps personal information saving usable after a transient save failure', async () => {
    const user = userEvent.setup()
    const updatedAccount = {
      ...account,
      profile: { ...account.profile, residential_address: '22 Harbour Road, Auckland' },
    }
    const onSaveProfile = vi.fn()
      .mockRejectedValueOnce(new Error('The account service is temporarily unavailable.'))
      .mockResolvedValueOnce(updatedAccount)
    renderProfile({ busy: true, onSaveProfile }, 'personal-details')

    await user.click(screen.getByRole('button', { name: 'Edit personal information' }))
    const address = screen.getByLabelText(/Residential address/)
    await user.clear(address)
    await user.type(address, '22 Harbour Road, Auckland')
    const saveButton = screen.getByRole('button', { name: 'Save personal information' })
    await user.click(saveButton)

    expect(await screen.findByRole('alert')).toHaveTextContent('Your changes were not saved')
    expect(saveButton).not.toBeDisabled()
    await user.click(saveButton)

    expect(onSaveProfile).toHaveBeenCalledTimes(2)
    expect(await screen.findByText(/Profile information was updated/)).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Edit personal information' })).toBeInTheDocument()
  })

  it('preserves an unsaved personal draft while the customer visits another category', async () => {
    const user = userEvent.setup()
    renderProfile({}, 'personal-details')

    await user.click(screen.getByRole('button', { name: 'Edit profile' }))
    const name = screen.getByLabelText('Preferred name')
    await user.clear(name)
    await user.type(name, 'Iris draft')
    await user.click(screen.getAllByRole('button', { name: 'Insured assets' })[0])
    await user.click(screen.getAllByRole('button', { name: 'Personal details' })[0])

    expect(screen.getByLabelText('Preferred name')).toHaveValue('Iris draft')
    expect(screen.getByRole('button', { name: 'Done' })).toBeInTheDocument()
  })

  it('keeps the personal editor open after a recoverable preference save failure', async () => {
    const user = userEvent.setup()
    const onSavePreferences = vi.fn().mockRejectedValue(new Error('The account service is temporarily unavailable.'))
    renderProfile({ onSavePreferences }, 'personal-details')

    await user.click(screen.getByRole('button', { name: 'Edit personal information' }))
    expect(screen.queryByLabelText('Preferred name')).not.toBeInTheDocument()
    expect(screen.getByLabelText('Legal name')).toHaveFocus()
    await user.click(screen.getByRole('radio', { name: /SMS/ }))
    await user.click(screen.getByRole('button', { name: 'Save contact preferences' }))

    expect(onSavePreferences).toHaveBeenCalledWith({ email: false, sms: true })
    expect(await screen.findByRole('alert')).toHaveTextContent('Your changes were not saved')
    expect(screen.getByRole('heading', { name: 'Contact preferences' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Done editing personal information' })).toBeInTheDocument()
  })

  it('saves one contact method when an older account has both enabled', async () => {
    const user = userEvent.setup()
    const accountWithBoth = { ...account, preferences: { email: true, sms: true } }
    const updatedAccount = { ...accountWithBoth, preferences: { email: false, sms: true } }
    const onSavePreferences = vi.fn().mockResolvedValue(updatedAccount)
    renderProfile({ account: accountWithBoth, onSavePreferences }, 'personal-details')

    expect(screen.getByText('Multiple saved — choose one')).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Edit personal information' }))
    const email = screen.getByRole('radio', { name: /Email/ })
    const sms = screen.getByRole('radio', { name: /SMS/ })
    expect(email).not.toBeChecked()
    expect(sms).not.toBeChecked()
    await user.click(email)
    expect(email).toBeChecked()
    expect(sms).not.toBeChecked()
    await user.click(sms)
    expect(email).not.toBeChecked()
    expect(sms).toBeChecked()
    await user.click(screen.getByRole('button', { name: 'Save contact preferences' }))

    expect(onSavePreferences).toHaveBeenCalledWith({ email: false, sms: true })
    expect(await screen.findByText('SMS', { selector: '.profile-summary-row > dd' })).toBeInTheDocument()
    expect(screen.queryByText('Multiple saved — choose one')).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Contact preferences' })).not.toBeInTheDocument()
    const editButton = screen.getByRole('button', { name: 'Edit personal information' })
    expect(editButton).toHaveFocus()
    await user.click(editButton)
    expect(screen.getByRole('radio', { name: /SMS/ })).toBeChecked()
  })

  it('opens a saved asset in a read-only detail view before offering edit controls', async () => {
    const user = userEvent.setup()
    const updatedAsset = {
      ...vehicleAsset,
      display_name: 'Family vehicle',
      revision: 3,
    }
    const onUpdateAsset = vi.fn().mockResolvedValue(updatedAsset)
    const { container } = renderProfile({ assets: [vehicleAsset], onUpdateAsset }, 'insured-assets')

    expect(screen.queryByRole('button', { name: 'Open Family SUV' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: /^Vehicles/ }))
    expect(screen.getByRole('heading', { name: 'Vehicles' })).toBeInTheDocument()
    expect(screen.getByText('1 saved')).toBeInTheDocument()
    expect(screen.getByText('Toyota RAV4', { exact: false })).toBeInTheDocument()
    expect(screen.getByText(/Updated 17 Sept 2026/)).toBeInTheDocument()
    const assetRow = screen.getByRole('button', { name: 'Open Family SUV' })
    expect(assetRow).toHaveClass('profile-asset-list-row')
    expect(container.querySelector('.profile-asset-card')).not.toBeInTheDocument()
    await user.click(assetRow)

    expect(screen.getByRole('heading', { name: 'Family SUV' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Overview' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Ownership & insurance' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Photos & documents' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Notes' })).toBeInTheDocument()
    expect(screen.queryByLabelText(/Vehicle type\/name/)).not.toBeInTheDocument()

    await user.click(screen.getByRole('button', { name: 'Back to Vehicles' }))
    expect(screen.getByRole('heading', { name: 'Vehicles' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open Family SUV' })).toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Open Family SUV' }))

    await user.click(screen.getByRole('button', { name: 'Edit asset' }))
    expect(screen.getByLabelText('Registration plate')).toHaveFocus()
    const vehicleTypeName = screen.getByLabelText('Vehicle type/name (optional)')
    await user.clear(vehicleTypeName)
    await user.type(vehicleTypeName, 'Family vehicle')
    await user.click(screen.getByRole('button', { name: 'Save asset' }))

    expect(onUpdateAsset).toHaveBeenCalledWith(
      vehicleAsset.asset_id,
      2,
      {
        display_name: 'Family vehicle',
        details: {
          registration: 'ABC123',
          registered_owner: 'Iris Zhang',
          make: 'Toyota',
          model: 'RAV4',
          year: 2022,
        },
      },
    )
    expect(await screen.findByRole('status')).toHaveTextContent('Family vehicle was updated')
  })

  it('adds a compact vehicle using only fields supported by the account asset contract', async () => {
    const user = userEvent.setup()
    const createdVehicle = {
      ...vehicleAsset,
      display_name: 'Toyota Corolla',
      details: {
        registration: 'NTH123',
        registered_owner: 'Iris Zhang',
        make: 'Toyota',
        model: 'Corolla',
        year: 2021,
      },
    }
    const onCreateAsset = vi.fn().mockResolvedValue(createdVehicle)
    const { container } = renderProfile({ onCreateAsset }, 'insured-assets')

    await user.click(screen.getByRole('button', { name: /^Vehicles/ }))
    await user.click(screen.getByRole('button', { name: 'Add vehicle' }))

    expect(screen.getByRole('heading', { name: 'Vehicle details' })).toBeInTheDocument()
    expect(screen.getByRole('heading', { name: 'Ownership' })).toBeInTheDocument()
    expect(screen.getByLabelText('Registration plate')).toHaveFocus()
    expect(screen.getByLabelText('Vehicle type/name (optional)')).toHaveValue('')
    expect(screen.queryByLabelText(/Colour|VIN|Purchase date|Purchase price/i)).not.toBeInTheDocument()
    expect(screen.queryByLabelText(/Damage|Police report|Repair quote|Accident location|Other driver/i)).not.toBeInTheDocument()
    expect(container.querySelector('input[type="file"]')).not.toBeInTheDocument()

    await user.type(screen.getByLabelText('Registration plate'), 'NTH123')
    await user.type(screen.getByLabelText('Make (optional)'), 'Toyota')
    await user.type(screen.getByLabelText('Model (optional)'), 'Corolla')
    await user.type(screen.getByLabelText('Year (optional)'), '2021')
    await user.type(screen.getByLabelText('Registered owner name (optional)'), 'Iris Zhang')
    await user.click(screen.getByRole('button', { name: 'Save asset' }))

    expect(onCreateAsset).toHaveBeenCalledWith({
      asset_type: 'vehicle',
      display_name: 'Toyota Corolla',
      details: {
        registration: 'NTH123',
        registered_owner: 'Iris Zhang',
        make: 'Toyota',
        model: 'Corolla',
        year: 2021,
      },
    })
    expect(await screen.findByRole('status')).toHaveTextContent('Toyota Corolla was added')
  })

  it('uses the registration plate as the vehicle name when no nickname, make, or model is provided', async () => {
    const user = userEvent.setup()
    const onCreateAsset = vi.fn().mockResolvedValue({
      ...vehicleAsset,
      display_name: 'NTH456',
      details: { registration: 'NTH456' },
    })
    renderProfile({ onCreateAsset }, 'insured-assets')

    await user.click(screen.getByRole('button', { name: /^Vehicles/ }))
    await user.click(screen.getByRole('button', { name: 'Add vehicle' }))
    await user.type(screen.getByLabelText('Registration plate'), 'NTH456')
    await user.click(screen.getByRole('button', { name: 'Save asset' }))

    expect(onCreateAsset).toHaveBeenCalledWith({
      asset_type: 'vehicle',
      display_name: 'NTH456',
      details: { registration: 'NTH456' },
    })
  })

  it('adds a property using only fields from the claimant asset contract', async () => {
    const user = userEvent.setup()
    const createdProperty = {
      asset_id: 'ase_22222222222222222222',
      asset_type: 'property',
      display_name: 'Home',
      details: { address: '1 Queen Street, Auckland', property_type: 'House' },
      revision: 1,
      active: true,
      created_at: '2026-09-18T01:00:00Z',
      updated_at: '2026-09-18T01:00:00Z',
    }
    const onCreateAsset = vi.fn().mockResolvedValue(createdProperty)
    renderProfile({ onCreateAsset }, 'insured-assets')

    await user.click(screen.getByRole('button', { name: /^Properties/ }))
    await user.click(screen.getByRole('button', { name: 'Add property' }))
    await user.type(screen.getByLabelText('Asset name'), 'Home')
    await user.type(screen.getByLabelText('Property address'), '1 Queen Street, Auckland')
    await user.type(screen.getByLabelText(/Property type/), 'House')
    await user.click(screen.getByRole('button', { name: 'Save asset' }))

    expect(onCreateAsset).toHaveBeenCalledWith({
      asset_type: 'property',
      display_name: 'Home',
      details: { address: '1 Queen Street, Auckland', property_type: 'House' },
    })
    expect(await screen.findByRole('status')).toHaveTextContent('Home was added')
  })
})
