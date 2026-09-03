import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { usePersistentTabs } from './usePersistentTabs.js'

describe('usePersistentTabs', () => {
  beforeEach(() => localStorage.clear())

  it('reuses the existing tab when the same Claim is opened twice', () => {
    const { result } = renderHook(() => usePersistentTabs())
    const claim = { claim_id: 'clm_100', display_reference: 'NW-100' }

    act(() => result.current.open(claim))
    act(() => result.current.open(claim))

    expect(result.current.tabs).toHaveLength(1)
    expect(result.current.activeId).toBe('clm_100')
  })

  it('keeps each Claim draft and section when another tab becomes active', () => {
    const { result } = renderHook(() => usePersistentTabs())

    act(() => result.current.open({ claim_id: 'clm_100', display_reference: 'NW-100' }))
    act(() => result.current.update('clm_100', { draft: 'Claimant update', section: 'conversation' }))
    act(() => result.current.open({ claim_id: 'clm_200', display_reference: 'NW-200' }))
    act(() => result.current.activate('clm_100'))

    expect(result.current.activeTab).toMatchObject({
      claimId: 'clm_100',
      draft: 'Claimant update',
      section: 'conversation',
    })
  })

  it('restores tabs after a browser refresh and selects the adjacent tab on close', () => {
    const first = renderHook(() => usePersistentTabs())
    act(() => first.result.current.open({ claim_id: 'clm_100', display_reference: 'NW-100' }))
    act(() => first.result.current.open({ claim_id: 'clm_200', display_reference: 'NW-200' }))
    act(() => first.result.current.open({ claim_id: 'clm_300', display_reference: 'NW-300' }))
    act(() => first.result.current.activate('clm_200'))
    first.unmount()

    const restored = renderHook(() => usePersistentTabs())
    expect(restored.result.current.tabs.map((tab) => tab.claimId)).toEqual([
      'clm_100',
      'clm_200',
      'clm_300',
    ])
    act(() => restored.result.current.close('clm_200'))
    expect(restored.result.current.activeId).toBe('clm_300')
  })
})
