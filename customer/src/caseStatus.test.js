import { describe, expect, it } from 'vitest'

import { caseStatus } from './caseStatus.js'

const claim = { claim_id: 'clm_1', external_claim: null, claim_decision: null }

describe('title-bar status', () => {
  it('shows one thing: a person first, then the lodged stage, then progress', () => {
    const staff = { key: 'waiting', title: 'Waiting for staff', description: 'Your request has been sent.' }
    expect(caseStatus({ claim, assistanceState: staff, progress: { noted: 2, total: 5 } }))
      .toEqual({ tone: 'staff', text: 'Waiting for staff', detail: 'Your request has been sent.' })
    expect(caseStatus({ claim, isUrgentSupport: true, assistanceState: staff }).tone).toBe('urgent')

    const lodged = { ...claim, external_claim: { creation_status: 'created' } }
    expect(caseStatus({ claim: lodged, progress: { noted: 5, total: 5 } }).text)
      .toBe('Lodged · Waiting for a claims handler')
    expect(caseStatus({ claim: lodged, handlerAssigned: true }).text).toBe('Lodged · With your claims handler')

    expect(caseStatus({ claim, progress: { noted: 2, total: 5 } }))
      .toEqual({ tone: 'neutral', text: 'Noted 2/5', opensPanel: true })
    expect(caseStatus({ claim }).text).toBe('Your claim')
    expect(caseStatus({ claim: null })).toBeNull()
  })

  it('lets a finished assistance fall back to the claim status', () => {
    const completed = { key: 'completed', title: 'Staff assistance completed' }
    expect(caseStatus({ claim, assistanceState: completed, progress: { noted: 1, total: 4 } }).text)
      .toBe('Noted 1/4')
  })
})
