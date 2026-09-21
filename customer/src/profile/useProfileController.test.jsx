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
})
