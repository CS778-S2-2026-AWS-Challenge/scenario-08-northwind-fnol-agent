import { useState } from 'react'
import { act, renderHook, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

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
  requestId: vi.fn(),
  updateAccountAsset: vi.fn(),
  updateAccountIdentityDocument: vi.fn(),
  updateAccountPolicy: vi.fn(),
  updateAccountPreferences: vi.fn(),
  updateAccountProfile: vi.fn(),
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
}

const asset = {
  asset_id: 'ase_11111111111111111111',
  asset_type: 'vehicle',
  display_name: 'Family SUV',
  details: { registration: 'ABC123' },
  revision: 1,
}

const policy = {
  policy_id: 'pol_11111111111111111111',
  policy_number: 'NTH-1234',
  revision: 1,
}

const payment = {
  payment_destination_id: 'pay_11111111111111111111',
  account_type: 'everyday',
  masked_account_number: '•••• 4321',
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
      .mockResolvedValueOnce(emptyPage([identity, concurrentIdentity]))
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
})
