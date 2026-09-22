import { act, renderHook } from '@testing-library/react'
import { beforeEach, describe, expect, it } from 'vitest'
import { usePersistentTabs } from './usePersistentTabs.js'

describe('usePersistentTabs', () => {
  beforeEach(() => localStorage.clear())

  it('reuses the existing tab when the same Claim is opened twice', () => {
    const { result } = renderHook(() => usePersistentTabs())
    const claim = {
      claim_id: 'clm_100',
      display_reference: 'NW-100',
      claimant: { display_name: 'Alex Morgan' },
    }

    act(() => result.current.open(claim))
    act(() => result.current.open(claim))

    expect(result.current.tabs).toHaveLength(1)
    expect(result.current.activeId).toBe('clm_100')
    expect(result.current.activeTab).toMatchObject({ label: 'Alex Morgan', referenceLabel: 'NW-100' })
  })

  it('replaces an incident fallback with the authorised claimant name without losing tab state', () => {
    const { result } = renderHook(() => usePersistentTabs())
    const claimId = 'clm_26ebb97a053bebb885e6'
    const createdAt = '2026-09-22T01:00:00Z'

    act(() => result.current.open({
      claim_id: claimId,
      display_reference: claimId,
      claimant: { customer_id: 'cus_demo' },
      incident: { family: null, summary: 'The claimant has not yet completed the report.' },
      created_at: createdAt,
    }))
    act(() => result.current.update(claimId, { draft: 'Keep this draft', section: 'conversation' }))

    expect(result.current.activeTab).toMatchObject({
      label: 'The claimant has not yet completed the report.',
      referenceLabel: claimId,
    })

    act(() => result.current.open({
      claim_id: claimId,
      display_reference: claimId,
      claimant: { customer_id: 'cus_demo', display_name: 'Alex Morgan' },
      incident: { family: null, summary: 'The claimant has not yet completed the report.' },
      created_at: createdAt,
    }))

    expect(result.current.activeTab).toMatchObject({
      label: 'Alex Morgan',
      referenceLabel: claimId,
      draft: 'Keep this draft',
      section: 'conversation',
    })
  })

  it('refreshes restored tab identities from the queue without activating another Claim', () => {
    localStorage.setItem('northwind.workbench.tabs.v1', JSON.stringify({
      activeId: 'clm_second',
      tabs: [
        { claimId: 'clm_first', label: 'clm_first', draft: 'First draft', section: 'summary' },
        { claimId: 'clm_second', label: 'clm_second', draft: 'Second draft', section: 'activity' },
      ],
    }))
    const { result } = renderHook(() => usePersistentTabs())

    expect(result.current.tabs.map((tab) => tab.label)).toEqual(['Claim in progress', 'Claim in progress'])

    act(() => result.current.syncIdentities([
      {
        claim_id: 'clm_first',
        display_reference: 'clm_first',
        claimant: { customer_id: 'cus_first' },
        incident: { family: null, summary: 'First report.' },
        created_at: '2026-09-21T01:00:00Z',
      },
      {
        claim_id: 'clm_second',
        display_reference: 'clm_second',
        claimant: { customer_id: 'cus_second' },
        incident: { family: null, summary: 'Second report.' },
        created_at: '2026-09-22T01:00:00Z',
      },
    ]))

    expect(result.current.tabs.map((tab) => tab.label)).toEqual([
      'First report.',
      'Second report.',
    ])
    expect(result.current.activeId).toBe('clm_second')
    expect(result.current.activeTab).toMatchObject({ draft: 'Second draft', section: 'activity' })
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
