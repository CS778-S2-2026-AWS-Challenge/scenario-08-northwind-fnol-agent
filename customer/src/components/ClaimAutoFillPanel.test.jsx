import { useState } from 'react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

const api = vi.hoisted(() => ({
  getClaim: vi.fn(),
  getClaimAutoFillSuggestions: vi.fn(),
  listAccountAssets: vi.fn(),
  listAccountPolicies: vi.fn(),
  listClaimAssetSnapshots: vi.fn(),
  requestId: vi.fn((prefix) => `${prefix}-stable-key`),
  selectClaimAsset: vi.fn(),
  selectClaimPolicy: vi.fn(),
}))

vi.mock('../api.js', () => api)

import ClaimAutoFillPanel from './ClaimAutoFillPanel.jsx'

const account = { customer_id: 'cus_synthetic', revision: 3 }
const claim = {
  claim_id: 'clm_synthetic',
  revision: 7,
  form: {},
  contents_items: [],
}

function suggestion(category, { enabled = true, available = true, action } = {}) {
  return { category, enabled, available, eligible: enabled && available, action }
}

function manifest(suggestions) {
  return {
    claim_id: claim.claim_id,
    claim_revision: claim.revision,
    account_revision: account.revision,
    suggestions,
  }
}

function page(items = []) {
  return { items, page: { next_cursor: null } }
}

function renderPanel(props = {}) {
  return render(
    <ClaimAutoFillPanel
      account={account}
      claim={claim}
      onClaimReadback={vi.fn(() => true)}
      {...props}
    />,
  )
}

describe('ClaimAutoFillPanel', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    api.listAccountPolicies.mockResolvedValue(page())
    api.listAccountAssets.mockResolvedValue(page())
    api.listClaimAssetSnapshots.mockResolvedValue(page())
  })

  it('automatically applies the sole policy and asset in revision order as reviewable information', async () => {
    const policy = {
      policy_id: 'pol_11111111111111111111',
      policy_number: 'MOTOR-1234',
      revision: 1,
    }
    const asset = {
      asset_id: 'ase_11111111111111111111',
      asset_type: 'vehicle',
      display_name: 'Family SUV',
      details: { registration: 'ABC123' },
      revision: 2,
    }
    const policyClaim = {
      ...claim,
      revision: 8,
      form: {
        'policy.policy_number': {
          value: policy.policy_number,
          status: 'proposed',
          source_refs: [`policy:${policy.policy_id}:revision:1`],
        },
      },
    }
    const assetClaim = {
      ...policyClaim,
      revision: 9,
      form: {
        ...policyClaim.form,
        'vehicle.registration': {
          value: 'ABC123',
          status: 'proposed',
          source_refs: [`asset:${asset.asset_id}:revision:2`],
        },
      },
    }
    api.getClaimAutoFillSuggestions.mockResolvedValue(manifest([
      suggestion('policy_number', { action: 'select_policy' }),
      suggestion('saved_assets', { action: 'select_asset' }),
    ]))
    api.listAccountPolicies.mockResolvedValue(page([policy]))
    api.listAccountAssets.mockResolvedValue(page([asset]))
    api.selectClaimPolicy.mockResolvedValue({ claim_id: claim.claim_id, revision: 8 })
    api.selectClaimAsset.mockResolvedValue({ claim_id: claim.claim_id, revision: 9 })
    api.getClaim.mockResolvedValueOnce(policyClaim).mockResolvedValueOnce(assetClaim)
    const onBusyChange = vi.fn()

    function Harness() {
      const [currentClaim, setCurrentClaim] = useState(claim)
      return (
        <ClaimAutoFillPanel
          account={account}
          claim={currentClaim}
          onBusyChange={onBusyChange}
          onClaimReadback={(nextClaim) => {
            setCurrentClaim(nextClaim)
            return true
          }}
        />
      )
    }

    render(<Harness />)

    await waitFor(() => expect(api.selectClaimPolicy).toHaveBeenCalledWith({
      claimId: claim.claim_id,
      revision: 7,
      policyId: policy.policy_id,
      idempotencyKey: 'claim-policy-selection-stable-key',
    }))
    await waitFor(() => expect(api.selectClaimAsset).toHaveBeenCalledWith({
      claimId: claim.claim_id,
      revision: 8,
      assetId: asset.asset_id,
      idempotencyKey: 'claim-asset-selection-stable-key',
    }))

    expect(await screen.findByText(/Policy ••••1234 was added to this Claim as information to review/)).toBeInTheDocument()
    expect(screen.getByText(/Family SUV was added to this Claim as information to review/)).toBeInTheDocument()
    expect(screen.queryByText('Use your saved details')).not.toBeInTheDocument()
    expect(onBusyChange).toHaveBeenCalledWith(true)
    expect(onBusyChange).toHaveBeenLastCalledWith(false)
  })

  it('shows a compact choice for multiple policies and does not select until the claimant chooses', async () => {
    const user = userEvent.setup()
    const policies = [
      { policy_id: 'pol_11111111111111111111', policy_number: 'MOTOR-1234', revision: 1 },
      { policy_id: 'pol_22222222222222222222', policy_number: 'HOME-5678', revision: 2 },
    ]
    api.getClaimAutoFillSuggestions.mockResolvedValue(manifest([
      suggestion('policy_number', { action: 'select_policy' }),
    ]))
    api.listAccountPolicies.mockResolvedValue(page(policies))
    api.selectClaimPolicy.mockResolvedValue({ claim_id: claim.claim_id, revision: 8 })
    api.getClaim.mockResolvedValue({
      ...claim,
      revision: 8,
      form: {
        'policy.policy_number': {
          value: policies[1].policy_number,
          status: 'proposed',
          source_refs: [`policy:${policies[1].policy_id}:revision:2`],
        },
      },
    })

    renderPanel()

    expect(await screen.findByText('Which saved policy applies to this Claim?')).toBeInTheDocument()
    expect(api.selectClaimPolicy).not.toHaveBeenCalled()
    await user.selectOptions(screen.getByRole('combobox', { name: 'Saved policy' }), policies[1].policy_id)
    await user.click(screen.getByRole('button', { name: 'Add for review' }))

    expect(api.selectClaimPolicy).toHaveBeenCalledWith({
      claimId: claim.claim_id,
      revision: 7,
      policyId: policies[1].policy_id,
      idempotencyKey: 'claim-policy-selection-stable-key',
    })
  })

  it('asks about only one ambiguous category at a time', async () => {
    const policies = [
      { policy_id: 'pol_11111111111111111111', policy_number: 'MOTOR-1234', revision: 1 },
      { policy_id: 'pol_22222222222222222222', policy_number: 'HOME-5678', revision: 1 },
    ]
    const assets = [
      { asset_id: 'ase_11111111111111111111', asset_type: 'vehicle', display_name: 'Family SUV', revision: 1 },
      { asset_id: 'ase_22222222222222222222', asset_type: 'property', display_name: 'Home', revision: 1 },
    ]
    api.getClaimAutoFillSuggestions.mockResolvedValue(manifest([
      suggestion('policy_number', { action: 'select_policy' }),
      suggestion('saved_assets', { action: 'select_asset' }),
    ]))
    api.listAccountPolicies.mockResolvedValue(page(policies))
    api.listAccountAssets.mockResolvedValue(page(assets))

    renderPanel()

    expect(await screen.findByText('Which saved policy applies to this Claim?')).toBeInTheDocument()
    expect(screen.queryByText('Which saved asset is involved in this Claim?')).not.toBeInTheDocument()
    expect(screen.getAllByRole('combobox')).toHaveLength(1)
  })

  it('retries an ambiguous automatic selection with the same idempotency key and revision', async () => {
    const user = userEvent.setup()
    const policy = {
      policy_id: 'pol_11111111111111111111',
      policy_number: 'HOME-5678',
      revision: 1,
    }
    const latestClaim = {
      ...claim,
      revision: 8,
      form: {
        'policy.policy_number': {
          value: policy.policy_number,
          status: 'proposed',
          source_refs: [`policy:${policy.policy_id}:revision:1`],
        },
      },
    }
    api.getClaimAutoFillSuggestions.mockResolvedValue(manifest([
      suggestion('policy_number', { action: 'select_policy' }),
    ]))
    api.listAccountPolicies.mockResolvedValue(page([policy]))
    api.selectClaimPolicy
      .mockRejectedValueOnce(new Error('The connection ended before a response arrived.'))
      .mockResolvedValueOnce({ claim_id: claim.claim_id, revision: 8 })
    api.getClaim.mockResolvedValueOnce(claim).mockResolvedValueOnce(latestClaim)

    renderPanel()

    await user.click(await screen.findByRole('button', { name: 'Retry the same selection' }))
    expect(await screen.findByText(/Policy ••••5678 was added to this Claim as information to review/)).toBeInTheDocument()
    expect(api.selectClaimPolicy).toHaveBeenCalledTimes(2)
    expect(api.selectClaimPolicy.mock.calls[0][0]).toEqual(api.selectClaimPolicy.mock.calls[1][0])
    expect(api.requestId).toHaveBeenCalledTimes(1)
  })

  it('reads back a revision conflict and prepares a retry against the latest Claim', async () => {
    const policy = {
      policy_id: 'pol_11111111111111111111',
      policy_number: 'HOME-9012',
      revision: 1,
    }
    const latestClaim = { ...claim, revision: 8 }
    const onClaimReadback = vi.fn(() => true)
    api.getClaimAutoFillSuggestions.mockResolvedValue(manifest([
      suggestion('policy_number', { action: 'select_policy' }),
    ]))
    api.listAccountPolicies.mockResolvedValue(page([policy]))
    api.selectClaimPolicy.mockRejectedValue(Object.assign(
      new Error('The Claim was updated by another action.'),
      { status: 409, code: 'REVISION_CONFLICT' },
    ))
    api.getClaim.mockResolvedValue(latestClaim)

    renderPanel({ onClaimReadback })

    expect(await screen.findByRole('alert')).toHaveTextContent(
      'The Claim changed before Policy ••••9012 could be added',
    )
    expect(screen.getByRole('button', { name: 'Try with the latest Claim' })).toBeInTheDocument()
    expect(onClaimReadback).toHaveBeenCalledWith(latestClaim, { minimumRevision: 0 })
    expect(api.requestId).toHaveBeenCalledTimes(2)
  })

  it('does not add an asset revision already represented by an immutable Claim snapshot', async () => {
    const asset = {
      asset_id: 'ase_11111111111111111111',
      asset_type: 'contents',
      display_name: 'Camera',
      details: { description: 'Mirrorless camera' },
      revision: 4,
    }
    api.getClaimAutoFillSuggestions.mockResolvedValue(manifest([
      suggestion('saved_assets', { action: 'select_asset' }),
    ]))
    api.listAccountAssets.mockResolvedValue(page([asset]))
    api.listClaimAssetSnapshots.mockResolvedValue(page([{
      snapshot_id: 'cas_synthetic',
      claim_id: claim.claim_id,
      asset_id: asset.asset_id,
      asset_revision: 4,
      resulting_claim_revision: 6,
    }]))

    const { container } = renderPanel()

    await waitFor(() => expect(api.listClaimAssetSnapshots).toHaveBeenCalled())
    expect(api.selectClaimAsset).not.toHaveBeenCalled()
    expect(container.querySelector('.claim-autofill-inline')).not.toBeInTheDocument()
  })

  it('does not overwrite Claim information the claimant already supplied', async () => {
    const policy = {
      policy_id: 'pol_11111111111111111111',
      policy_number: 'HOME-9012',
      revision: 1,
    }
    const asset = {
      asset_id: 'ase_11111111111111111111',
      asset_type: 'property',
      display_name: 'Saved home',
      details: { address: '9 Saved Street' },
      revision: 2,
    }
    api.getClaimAutoFillSuggestions.mockResolvedValue(manifest([
      suggestion('policy_number', { action: 'select_policy' }),
      suggestion('saved_assets', { action: 'select_asset' }),
    ]))
    api.listAccountPolicies.mockResolvedValue(page([policy]))
    api.listAccountAssets.mockResolvedValue(page([asset]))

    const { container } = renderPanel({
      claim: {
        ...claim,
        form: {
          'policy.policy_number': { value: 'MANUALLY-ENTERED', status: 'proposed' },
          'property.address': { value: '1 Reported Road', status: 'proposed' },
        },
      },
    })

    await waitFor(() => expect(api.listAccountAssets).toHaveBeenCalled())
    expect(api.selectClaimPolicy).not.toHaveBeenCalled()
    expect(api.selectClaimAsset).not.toHaveBeenCalled()
    expect(container.querySelector('.claim-autofill-inline')).not.toBeInTheDocument()
  })

  it.each(['proposed', 'confirmed'])(
    'does not automatically apply a sole asset to an incompatible %s Claim family',
    async (status) => {
      const asset = {
        asset_id: 'ase_11111111111111111111',
        asset_type: 'vehicle',
        display_name: 'Family SUV',
        details: { registration: 'ABC123' },
        revision: 2,
      }
      api.getClaimAutoFillSuggestions.mockResolvedValue(manifest([
        suggestion('saved_assets', { action: 'select_asset' }),
      ]))
      api.listAccountAssets.mockResolvedValue(page([asset]))

      const { container } = renderPanel({
        claim: {
          ...claim,
          form: {
            'claim.product_family': { value: 'home', status },
            'property.address': { value: '1 Reported Road', status },
          },
        },
      })

      await waitFor(() => expect(api.listAccountAssets).toHaveBeenCalled())
      expect(api.selectClaimAsset).not.toHaveBeenCalled()
      expect(container.querySelector('.claim-autofill-inline')).not.toBeInTheDocument()
    },
  )

  it('keeps confirmation-only categories out of the conversation until their workflow step', async () => {
    api.getClaimAutoFillSuggestions.mockResolvedValue(manifest([
      suggestion('personal_details', { action: 'review_and_confirm' }),
      suggestion('payment_details', { action: 'confirm_separately' }),
      suggestion('identity_information', { action: 'confirm_separately' }),
    ]))

    const { container } = renderPanel()

    await waitFor(() => expect(api.getClaimAutoFillSuggestions).toHaveBeenCalled())
    expect(container.querySelector('.claim-autofill-inline')).not.toBeInTheDocument()
  })

  it('shows a compact retry when saved details cannot be checked', async () => {
    const user = userEvent.setup()
    api.getClaimAutoFillSuggestions
      .mockRejectedValueOnce(new Error('Service temporarily unavailable.'))
      .mockResolvedValueOnce(manifest([]))

    renderPanel()

    expect(await screen.findByRole('alert')).toHaveTextContent('Saved details could not be checked')
    expect(screen.queryByText('Use your saved details')).not.toBeInTheDocument()
    await user.click(screen.getByRole('button', { name: 'Retry' }))
    await waitFor(() => expect(api.getClaimAutoFillSuggestions).toHaveBeenCalledTimes(2))
    expect(screen.queryByRole('alert')).not.toBeInTheDocument()
  })
})
