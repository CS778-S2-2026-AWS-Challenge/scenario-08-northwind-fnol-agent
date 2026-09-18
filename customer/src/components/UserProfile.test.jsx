import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import UserProfile from './UserProfile.jsx'

const account = {
  profile: {
    display_name: 'Iris Zhang',
    email: 'iris@gmail.com',
    phone: '+64 21 555 123',
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

function ProfileHarness({ initialSection = null, profileProps }) {
  const [activeSection, setActiveSection] = useState(initialSection)

  return (
    <UserProfile
      {...profileProps}
      activeSection={activeSection}
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
    expect(screen.queryByRole('button', { name: 'Policies' })).not.toBeInTheDocument()
    expect(screen.getByText('i•••@gmail.com')).toBeInTheDocument()
    expect(screen.getByText('••• ••• 123')).toBeInTheDocument()
    expect(screen.getByText('Policy number')).toBeInTheDocument()
    expect(screen.queryByText(/^Saved$/)).not.toBeInTheDocument()
    expect(screen.getByText('Iris Zhang').closest('.profile-header')).toBeInTheDocument()
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
    expect(screen.getAllByText('Unavailable')).toHaveLength(3)

    await user.click(screen.getAllByRole('button', { name: 'Claim auto-fill' })[0])
    expect(screen.getByText(/must review and confirm it before it becomes claim information/i)).toBeInTheDocument()
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument()
  })

  it('submits only current-contract account fields and reports the authoritative update', async () => {
    const user = userEvent.setup()
    const updatedAccount = {
      ...account,
      profile: { ...account.profile, display_name: 'Iris' },
    }
    const onSaveProfile = vi.fn().mockResolvedValue(updatedAccount)
    renderProfile({ onSaveProfile }, 'personal-details')

    await user.click(screen.getByRole('button', { name: 'Edit profile' }))
    const name = screen.getByLabelText('Preferred name')
    expect(name).toHaveFocus()
    await user.clear(name)
    await user.type(name, 'Iris')
    expect(screen.queryByLabelText(/Phone number/)).not.toBeInTheDocument()
    expect(screen.queryByRole('heading', { name: 'Contact preferences' })).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Save profile' }))

    expect(onSaveProfile).toHaveBeenCalledWith({ display_name: 'Iris', phone: '+64 21 555 123' })
    expect(await screen.findByRole('status')).toHaveTextContent('updated in your saved Northwind account')
    expect(screen.getByRole('button', { name: 'Done' })).toBeInTheDocument()
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
    expect(screen.getByLabelText(/Phone number/)).toHaveFocus()
    await user.click(screen.getByRole('checkbox', { name: /SMS/ }))
    await user.click(screen.getByRole('button', { name: 'Save contact preferences' }))

    expect(onSavePreferences).toHaveBeenCalledWith({ email: true, sms: true })
    expect(await screen.findByRole('alert')).toHaveTextContent('Your changes were not saved')
    expect(screen.getByRole('heading', { name: 'Contact preferences' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Done editing personal information' })).toBeInTheDocument()
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
