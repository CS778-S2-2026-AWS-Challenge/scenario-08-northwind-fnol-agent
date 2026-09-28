import { useState } from 'react'
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
  ApiRequestError: class ApiRequestError extends Error {},
  createAccountAsset: vi.fn(),
  createAccountIdentityDocument: vi.fn(),
  createAccountPolicy: vi.fn(),
  createPaymentDestination: vi.fn(),
  getAuthenticatedAccount: vi.fn(),
  listAccountAssets: vi.fn(),
  listAccountIdentityDocuments: vi.fn(),
  listAccountPaymentDestinations: vi.fn(),
  listAccountPolicies: vi.fn(),
  requestId: vi.fn(),
  updateAccountAsset: vi.fn(),
  updateAccountIdentityDocument: vi.fn(),
  updateAccountPaymentDestination: vi.fn(),
  updateAccountPolicy: vi.fn(),
  updateAccountPreferences: vi.fn(),
  updateAccountProfile: vi.fn(),
  updateClaimAutoFillPreferences: vi.fn(),
}))

vi.mock('../api.js', () => api)

import useProfileController, { ProfileMutationError } from './useProfileController.js'

const account = {
  customer_id: 'cus_profile_controller',
  revision: 4,
  profile: {
    display_name: 'Iris',
    legal_name: 'Iris Zhang',
    preferred_name: 'Iris',
    email: 'iris@example.com',
  },
  preferences: { email: true, sms: false },
  claim_auto_fill_preferences: {
    personal_details: false,
    policy_number: false,
    saved_assets: false,
    payment_details: false,
    identity_information: false,
  },
}

const asset = {
  asset_id: 'ase_11111111111111111111',
  asset_type: 'vehicle',
  display_name: 'Family SUV',
  details: { registration: 'ABC123' },
  revision: 1,
}

const payment = {
  payment_destination_id: 'pyd_11111111111111111111',
  account_type: 'everyday',
  bank_name: 'Northwind Bank',
  account_holder_name: 'Iris Zhang',
  is_common: true,
  masked_account_number: '•••• 4321',
  revision: 1,
}

const policy = {
  policy_id: 'pol_11111111111111111111',
  policy_number: 'MOTOR-1234',
  revision: 1,
}

const identity = {
  identity_id: 'idn_11111111111111111111',
  document_type: 'driver_licence',
  masked_document_number: '****1234',
  revision: 1,
}

const resourceCases = [
  {
    label: 'Policies',
    resource: 'policies',
    listMethod: 'listAccountPolicies',
    reloadMethod: 'reloadPolicies',
    records: [policy],
  },
  {
    label: 'Assets',
    resource: 'assets',
    listMethod: 'listAccountAssets',
    reloadMethod: 'reloadAssets',
    records: [asset],
  },
  {
    label: 'Identity',
    resource: 'identities',
    listMethod: 'listAccountIdentityDocuments',
    reloadMethod: 'reloadIdentities',
    records: [identity],
  },
  {
    label: 'Payment',
    resource: 'payments',
    listMethod: 'listAccountPaymentDestinations',
    reloadMethod: 'reloadPayments',
    records: [payment],
  },
]

function emptyPage(items = []) {
  return { items, page: { next_cursor: null } }
}

function renderController() {
  return renderHook(() => {
    const [currentAccount, setCurrentAccount] = useState(account)
    return {
      account: currentAccount,
      controller: useProfileController({ account: currentAccount, setAccount: setCurrentAccount }),
    }
  })
}

describe('useProfileController mutation recovery', () => {
  beforeEach(() => {
    vi.clearAllMocks()
    let requestNumber = 0
    api.requestId.mockImplementation((prefix) => `${prefix}-key-${requestNumber += 1}`)
    api.listAccountAssets.mockResolvedValue(emptyPage())
    api.listAccountPolicies.mockResolvedValue(emptyPage())
    api.listAccountPaymentDestinations.mockResolvedValue(emptyPage())
    api.listAccountIdentityDocuments.mockResolvedValue(emptyPage())
  })

  it('treats a lost profile response as saved only after authoritative readback matches', async () => {
    const savedAccount = {
      ...account,
      revision: 5,
      profile: { ...account.profile, display_name: 'Iris Liu', preferred_name: 'Iris Liu' },
    }
    api.updateAccountProfile.mockRejectedValue({ code: 'NETWORK_ERROR' })
    api.getAuthenticatedAccount.mockResolvedValue(savedAccount)
    const { result } = renderController()

    await waitFor(() => expect(api.listAccountAssets).toHaveBeenCalledOnce())
    let saved
    await act(async () => {
      saved = await result.current.controller.saveProfile({ preferred_name: 'Iris Liu' })
    })

    expect(api.updateAccountProfile).toHaveBeenCalledWith({ preferred_name: 'Iris Liu' }, 4)
    expect(api.getAuthenticatedAccount).toHaveBeenCalledOnce()
    expect(saved).toEqual(savedAccount)
    expect(result.current.account).toEqual(savedAccount)
  })

  it('reloads the latest account after a stale revision and requires an explicit retry', async () => {
    const latestAccount = {
      ...account,
      revision: 5,
      profile: { ...account.profile, phone: '+64 21 555 999' },
    }
    api.updateAccountProfile.mockRejectedValue({ code: 'REVISION_CONFLICT', status: 409 })
    api.getAuthenticatedAccount.mockResolvedValue(latestAccount)
    const { result } = renderController()

    await waitFor(() => expect(api.listAccountAssets).toHaveBeenCalledOnce())
    let error
    await act(async () => {
      try {
        await result.current.controller.saveProfile({ phone: '+64 21 555 123' })
      } catch (requestError) {
        error = requestError
      }
    })

    expect(error).toBeInstanceOf(ProfileMutationError)
    expect(error).toMatchObject({ code: 'REVISION_CONFLICT', kind: 'conflict' })
    expect(result.current.account).toEqual(latestAccount)
    expect(api.updateAccountProfile).toHaveBeenCalledOnce()
  })

  it('sends the loaded account revision when saving contact preferences', async () => {
    const savedAccount = {
      ...account,
      revision: 5,
      preferences: { email: false, sms: true },
    }
    api.updateAccountPreferences.mockResolvedValue(savedAccount)
    const { result } = renderController()

    await waitFor(() => expect(api.listAccountAssets).toHaveBeenCalledOnce())
    await act(async () => {
      await result.current.controller.savePreferences({ email: false, sms: true })
    })

    expect(api.updateAccountPreferences).toHaveBeenCalledWith({ email: false, sms: true }, 4)
    expect(result.current.account).toEqual(savedAccount)
  })

  it('saves the complete Claim auto-fill choice set with the loaded account revision', async () => {
    const preferences = {
      personal_details: true,
      policy_number: false,
      saved_assets: true,
      payment_details: false,
      identity_information: true,
    }
    const savedAccount = {
      ...account,
      revision: 5,
      claim_auto_fill_preferences: preferences,
    }
    api.updateClaimAutoFillPreferences.mockResolvedValue(savedAccount)
    const { result } = renderController()

    await waitFor(() => expect(api.listAccountAssets).toHaveBeenCalledOnce())
    await act(async () => {
      await result.current.controller.saveAutoFillPreferences(preferences)
    })

    expect(api.updateClaimAutoFillPreferences).toHaveBeenCalledWith(preferences, 4)
    expect(result.current.account).toEqual(savedAccount)
  })

  it('reconciles an interrupted Claim auto-fill save from authoritative account readback', async () => {
    const preferences = {
      personal_details: true,
      policy_number: true,
      saved_assets: false,
      payment_details: false,
      identity_information: false,
    }
    const savedAccount = {
      ...account,
      revision: 5,
      claim_auto_fill_preferences: preferences,
    }
    api.updateClaimAutoFillPreferences.mockRejectedValue({ code: 'NETWORK_ERROR' })
    api.getAuthenticatedAccount.mockResolvedValue(savedAccount)
    const { result } = renderController()

    await waitFor(() => expect(api.listAccountAssets).toHaveBeenCalledOnce())
    let saved
    await act(async () => {
      saved = await result.current.controller.saveAutoFillPreferences(preferences)
    })

    expect(saved).toEqual(savedAccount)
    expect(api.getAuthenticatedAccount).toHaveBeenCalledOnce()
    expect(result.current.account).toEqual(savedAccount)
  })

  it.each(resourceCases)('keeps $label unavailable when its initial load fails', async ({ listMethod, resource }) => {
    api[listMethod].mockRejectedValueOnce({ code: 'NETWORK_ERROR' })
    const { result } = renderController()

    await waitFor(() => expect(result.current.controller.resources[resource].error).not.toBe(''))

    expect(result.current.controller.resources[resource]).toMatchObject({
      items: null,
      loading: false,
      stale: false,
    })
  })

  it.each(resourceCases)(
    'marks retained $label data stale when a reload fails',
    async ({ listMethod, records, reloadMethod, resource }) => {
      api[listMethod]
        .mockResolvedValueOnce(emptyPage(records))
        .mockRejectedValueOnce({ code: 'NETWORK_ERROR' })
      const { result } = renderController()

      await waitFor(() => expect(result.current.controller.resources[resource].items).toEqual(records))
      await act(async () => {
        await expect(result.current.controller[reloadMethod]()).rejects.toMatchObject({ code: 'NETWORK_ERROR' })
      })

      expect(result.current.controller.resources[resource]).toMatchObject({
        items: records,
        loading: false,
        stale: true,
      })
      expect(result.current.controller.resources[resource].error).not.toBe('')
    },
  )

  it.each([
    { label: 'one retained asset', records: [asset] },
    { label: 'a retained empty asset list', records: [] },
  ])('reports active loading while retrying $label after failure', async ({ records }) => {
    let resolveRetry
    const retryResponse = new Promise((resolve) => { resolveRetry = resolve })
    api.listAccountAssets
      .mockResolvedValueOnce(emptyPage(records))
      .mockRejectedValueOnce({ code: 'NETWORK_ERROR' })
      .mockImplementationOnce(() => retryResponse)
    const { result } = renderController()

    await waitFor(() => expect(result.current.controller.resources.assets.items).toEqual(records))
    await act(async () => {
      await expect(result.current.controller.reloadAssets()).rejects.toMatchObject({ code: 'NETWORK_ERROR' })
    })

    let retryPromise
    act(() => { retryPromise = result.current.controller.reloadAssets() })
    await waitFor(() => expect(result.current.controller.resources.assets).toMatchObject({
      items: records,
      error: '',
      loading: true,
      stale: true,
    }))

    await act(async () => {
      resolveRetry(emptyPage(records))
      await retryPromise
    })
    expect(result.current.controller.resources.assets).toMatchObject({
      items: records,
      error: '',
      loading: false,
      stale: false,
    })
  })

  it('retains records while mutation readback loads and fails', async () => {
    let rejectReadback
    const readback = new Promise((resolve, reject) => { rejectReadback = reject })
    api.listAccountAssets
      .mockResolvedValueOnce(emptyPage([asset]))
      .mockImplementationOnce(() => readback)
    api.updateAccountAsset.mockRejectedValueOnce({ code: 'NETWORK_ERROR' })
    const { result } = renderController()

    await waitFor(() => expect(result.current.controller.resources.assets.items).toEqual([asset]))
    let mutationPromise
    act(() => {
      mutationPromise = result.current.controller.saveAsset(asset.asset_id, asset.revision, { display_name: 'Renamed SUV' })
    })
    await waitFor(() => expect(result.current.controller.resources.assets).toMatchObject({
      items: [asset],
      error: '',
      loading: true,
      stale: false,
    }))

    await act(async () => {
      rejectReadback({ code: 'NETWORK_ERROR' })
      await expect(mutationPromise).rejects.toMatchObject({ kind: 'unknown' })
    })
    expect(result.current.controller.resources.assets).toMatchObject({
      items: [asset],
      loading: false,
      stale: true,
    })
    expect(result.current.controller.resources.assets.error).not.toBe('')
  })

  it('reuses the same idempotency key when an asset response is lost and readback cannot find it', async () => {
    api.createAccountAsset
      .mockRejectedValueOnce({ code: 'NETWORK_ERROR' })
      .mockResolvedValueOnce(asset)
    const { result } = renderController()

    await waitFor(() => expect(api.listAccountAssets).toHaveBeenCalledOnce())
    const attemptId = result.current.controller.beginCreate('asset')
    await act(async () => {
      await expect(result.current.controller.createAsset({
        asset: { asset_type: 'vehicle', display_name: 'Family SUV', details: { registration: 'ABC123' } },
        attemptId,
      })).rejects.toMatchObject({ kind: 'unknown' })
    })
    await act(async () => {
      await result.current.controller.createAsset({
        asset: { asset_type: 'vehicle', display_name: 'Family SUV', details: { registration: 'ABC123' } },
        attemptId,
      })
    })

    expect(api.createAccountAsset).toHaveBeenCalledTimes(2)
    expect(api.createAccountAsset.mock.calls[1][0].idempotencyKey)
      .toBe(api.createAccountAsset.mock.calls[0][0].idempotencyKey)
  })

  it('reconciles a lost asset-create response from the authoritative list without posting twice', async () => {
    api.listAccountAssets
      .mockResolvedValueOnce(emptyPage())
      .mockResolvedValueOnce(emptyPage([asset]))
    api.createAccountAsset.mockRejectedValue({ code: 'NETWORK_ERROR' })
    const { result } = renderController()

    await waitFor(() => expect(api.listAccountAssets).toHaveBeenCalledOnce())
    const attemptId = result.current.controller.beginCreate('asset')
    let saved
    await act(async () => {
      saved = await result.current.controller.createAsset({
        asset: { asset_type: 'vehicle', display_name: 'Family SUV', details: { registration: 'ABC123' } },
        attemptId,
      })
    })

    expect(saved).toEqual(asset)
    expect(api.createAccountAsset).toHaveBeenCalledOnce()
    expect(result.current.controller.resources.assets.items).toEqual([asset])
  })

  it('reloads the current asset after a stale revision and does not loop the update', async () => {
    const latestAsset = { ...asset, display_name: 'Shared SUV', revision: 2 }
    api.listAccountAssets
      .mockResolvedValueOnce(emptyPage([asset]))
      .mockResolvedValueOnce(emptyPage([latestAsset]))
    api.updateAccountAsset.mockRejectedValue({ code: 'REVISION_CONFLICT', status: 409 })
    const { result } = renderController()

    await waitFor(() => expect(result.current.controller.resources.assets.items).toEqual([asset]))
    await act(async () => {
      await expect(result.current.controller.saveAsset(asset.asset_id, 1, { display_name: 'My SUV' }))
        .rejects.toMatchObject({ kind: 'conflict' })
    })

    expect(result.current.controller.resources.assets.items).toEqual([latestAsset])
    expect(api.updateAccountAsset).toHaveBeenCalledOnce()
  })

  it('replays an ambiguous identity create with the same key instead of matching masked collisions', async () => {
    const concurrentIdentity = {
      ...identity,
      identity_id: 'idn_22222222222222222222',
      revision: 2,
    }
    const createdIdentity = {
      ...identity,
      identity_id: 'idn_33333333333333333333',
      revision: 1,
    }
    api.listAccountIdentityDocuments
      .mockResolvedValueOnce(emptyPage([identity]))
      .mockResolvedValue(emptyPage([identity, concurrentIdentity]))
    api.createAccountIdentityDocument
      .mockRejectedValueOnce({ code: 'NETWORK_ERROR' })
      .mockResolvedValueOnce(createdIdentity)
    const { result } = renderController()

    await waitFor(() => expect(result.current.controller.resources.identities.items).toEqual([identity]))
    const attemptId = result.current.controller.beginCreate('identity')
    let saved
    await act(async () => {
      saved = await result.current.controller.createIdentity({
        documentType: 'driver_licence',
        documentNumber: 'DL9991234',
        attemptId,
      })
    })

    expect(saved).toEqual(createdIdentity)
    expect(api.createAccountIdentityDocument).toHaveBeenCalledTimes(2)
    expect(api.createAccountIdentityDocument.mock.calls[1][0])
      .toEqual(api.createAccountIdentityDocument.mock.calls[0][0])
    expect(api.listAccountIdentityDocuments).toHaveBeenCalledOnce()
    expect(result.current.controller.resources.identities.items).toEqual([createdIdentity, identity])
  })

  it('keeps an ambiguous identity update unknown when the masked suffix still matches', async () => {
    const latestIdentity = { ...identity, revision: 2 }
    const savedIdentity = { ...identity, revision: 3 }
    api.listAccountIdentityDocuments
      .mockResolvedValueOnce(emptyPage([identity]))
      .mockResolvedValueOnce(emptyPage([latestIdentity]))
    api.updateAccountIdentityDocument
      .mockRejectedValueOnce({ code: 'NETWORK_ERROR' })
      .mockResolvedValueOnce(savedIdentity)
    const { result } = renderController()

    await waitFor(() => expect(result.current.controller.resources.identities.items).toEqual([identity]))
    await act(async () => {
      await expect(result.current.controller.saveIdentity(
        identity.identity_id,
        identity.revision,
        'DIFFERENT-1234',
      )).rejects.toMatchObject({ kind: 'unknown' })
    })

    expect(result.current.controller.resources.identities.items).toEqual([latestIdentity])
    expect(api.updateAccountIdentityDocument).toHaveBeenCalledOnce()

    let saved
    await act(async () => {
      saved = await result.current.controller.saveIdentity(
        latestIdentity.identity_id,
        latestIdentity.revision,
        'DIFFERENT-1234',
      )
    })

    expect(saved).toEqual(savedIdentity)
    expect(api.updateAccountIdentityDocument).toHaveBeenLastCalledWith({
      identityId: latestIdentity.identity_id,
      revision: 2,
      documentNumber: 'DIFFERENT-1234',
    })
  })

  it('replays an ambiguous protected payment create with the same idempotency key', async () => {
    api.createPaymentDestination
      .mockRejectedValueOnce({ code: 'NETWORK_ERROR' })
      .mockResolvedValueOnce(payment)
    const { result } = renderController()

    await waitFor(() => expect(api.listAccountPaymentDestinations).toHaveBeenCalledOnce())
    const attemptId = result.current.controller.beginCreate('payment')
    let saved
    await act(async () => {
      saved = await result.current.controller.createPayment({
        bankName: 'Northwind Bank',
        accountHolderName: 'Iris Zhang',
        accountType: 'everyday',
        accountNumber: '12-3456-0789012-00',
        attemptId,
      })
    })

    expect(saved).toEqual(payment)
    expect(api.createPaymentDestination).toHaveBeenCalledTimes(2)
    expect(api.createPaymentDestination.mock.calls[1][0])
      .toEqual(api.createPaymentDestination.mock.calls[0][0])
    expect(result.current.controller.resources.payments.items).toEqual([payment])
  })

  it('replays an ambiguous policy create with the same idempotency key', async () => {
    api.createAccountPolicy
      .mockRejectedValueOnce({ code: 'NETWORK_ERROR' })
      .mockResolvedValueOnce(policy)
    const { result } = renderController()

    await waitFor(() => expect(api.listAccountPolicies).toHaveBeenCalledOnce())
    const attemptId = result.current.controller.beginCreate('policy')
    let saved
    await act(async () => {
      saved = await result.current.controller.createPolicy({
        policyNumber: ' MOTOR-1234 ',
        attemptId,
      })
    })

    expect(saved).toEqual(policy)
    expect(api.createAccountPolicy).toHaveBeenCalledTimes(2)
    expect(api.createAccountPolicy.mock.calls[1][0])
      .toEqual(api.createAccountPolicy.mock.calls[0][0])
    expect(api.createAccountPolicy).toHaveBeenCalledWith({
      policyNumber: 'MOTOR-1234',
      idempotencyKey: expect.any(String),
    })
    expect(result.current.controller.resources.policies.items).toEqual([policy])
  })

  it('updates a policy number with the selected record revision', async () => {
    const updatedPolicy = { ...policy, policy_number: 'HOME-5678', revision: 2 }
    api.listAccountPolicies.mockResolvedValueOnce(emptyPage([policy]))
    api.updateAccountPolicy.mockResolvedValueOnce(updatedPolicy)
    const { result } = renderController()

    await waitFor(() => expect(result.current.controller.resources.policies.items).toEqual([policy]))
    await act(async () => {
      await result.current.controller.savePolicy(policy.policy_id, policy.revision, ' HOME-5678 ')
    })

    expect(api.updateAccountPolicy).toHaveBeenCalledWith({
      policyId: policy.policy_id,
      revision: 1,
      policyNumber: 'HOME-5678',
    })
    expect(result.current.controller.resources.policies.items).toEqual([updatedPolicy])
  })
})
