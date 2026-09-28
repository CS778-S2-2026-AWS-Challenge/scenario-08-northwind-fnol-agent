import { useState } from 'react'
import { act, renderHook } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

import { ProfileMutationError } from './profileMutation.js'
import useClaimAutoFillEditor from './useClaimAutoFillEditor.js'

const account = {
  customer_id: 'cus_auto_fill_one',
  revision: 4,
  claim_auto_fill_preferences: {
    personal_details: false,
    policy_number: true,
    saved_assets: false,
    payment_details: false,
    identity_information: false,
  },
}

function renderEditor(onSave) {
  return renderHook(() => {
    const [currentAccount, setCurrentAccount] = useState(account)
    return {
      currentAccount,
      setCurrentAccount,
      editor: useClaimAutoFillEditor({ account: currentAccount, onSave }),
    }
  })
}

describe('useClaimAutoFillEditor', () => {
  it('projects exactly five authoritative choices and replaces the complete set on save', async () => {
    const savedAccount = {
      ...account,
      revision: 5,
      claim_auto_fill_preferences: {
        ...account.claim_auto_fill_preferences,
        saved_assets: true,
      },
    }
    const onSave = vi.fn().mockResolvedValue(savedAccount)
    const { result } = renderEditor(onSave)

    expect(result.current.editor.choices).toHaveLength(5)
    expect(result.current.editor.choices.find(({ key }) => key === 'policy_number').visible).toBe(true)

    act(() => result.current.editor.changeChoice('saved_assets', true))
    await act(() => result.current.editor.saveChoices())

    expect(onSave).toHaveBeenCalledWith({
      personal_details: false,
      policy_number: true,
      saved_assets: true,
      payment_details: false,
      identity_information: false,
    })
    expect(result.current.editor.dirty).toBe(false)
    expect(result.current.editor.notice).toMatch(/were updated/i)
  })

  it('keeps the draft after a stale revision reload so the claimant can review and retry', async () => {
    const onSave = vi.fn().mockRejectedValue(new ProfileMutationError(
      'Your saved account changed. Northwind reloaded the latest values and kept your draft.',
      { code: 'REVISION_CONFLICT', kind: 'conflict' },
    ))
    const { result } = renderEditor(onSave)

    act(() => result.current.editor.changeChoice('personal_details', true))
    act(() => result.current.setCurrentAccount({
      ...account,
      revision: 5,
      claim_auto_fill_preferences: {
        ...account.claim_auto_fill_preferences,
        identity_information: true,
      },
    }))
    await act(() => result.current.editor.saveChoices())

    expect(result.current.editor.dirty).toBe(true)
    expect(result.current.editor.choices.find(({ key }) => key === 'personal_details').visible).toBe(true)
    expect(result.current.editor.choices.find(({ key }) => key === 'identity_information').visible).toBe(true)
    expect(result.current.editor.error).toMatch(/kept your draft/i)
  })

  it('does not expose a previous account draft after the authenticated account changes', () => {
    const { result } = renderEditor(vi.fn())

    act(() => result.current.editor.changeChoice('personal_details', true))
    expect(result.current.editor.dirty).toBe(true)

    act(() => result.current.setCurrentAccount({
      ...account,
      customer_id: 'cus_auto_fill_two',
    }))

    expect(result.current.editor.dirty).toBe(false)
    expect(result.current.editor.choices.find(({ key }) => key === 'personal_details').visible).toBe(false)
  })

  it('clears the local draft when the claimant signs out', () => {
    const { result } = renderEditor(vi.fn())

    act(() => result.current.editor.changeChoice('personal_details', true))
    act(() => result.current.editor.reset())

    expect(result.current.editor.dirty).toBe(false)
    expect(result.current.editor.choices.find(({ key }) => key === 'personal_details').visible).toBe(false)
  })

  it('reports the choices unavailable when the Account projection is incomplete', () => {
    const { result } = renderHook(() => useClaimAutoFillEditor({
      account: { customer_id: 'cus_incomplete', revision: 1 },
      onSave: vi.fn(),
    }))

    expect(result.current.available).toBe(false)
    expect(result.current.choices).toBeNull()
  })
})
