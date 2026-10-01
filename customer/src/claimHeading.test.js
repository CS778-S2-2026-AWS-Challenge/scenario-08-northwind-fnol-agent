import { describe, expect, it } from 'vitest'

import { claimHeading, claimStartedLabel } from './claimHeading.js'

const started = '2026-10-01T10:20:00Z'
const localTime = new Date(started).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })

describe('claim heading', () => {
  it('uses the Northwind claim number once the claim is created', () => {
    expect(claimHeading({
      claim_id: 'clm_internal',
      incident_type: 'motor',
      created_at: started,
      external_claim: { claim_number: 'NWF-2026-000123' },
    })).toBe('NWF-2026-000123')
  })

  it('names an uncreated claim by type and start time', () => {
    expect(claimHeading({ claim_id: 'clm_internal', incident_type: 'motor', created_at: started }))
      .toBe(`Motor claim · started ${localTime}`)
    expect(claimHeading({ claim_id: 'clm_internal', incident_type: 'home', created_at: null }))
      .toBe('Home claim')
  })

  it('falls back to New claim and never shows the internal id', () => {
    for (const claim of [{ claim_id: 'clm_internal' }, { claim_id: 'clm_internal', incident_type: 'travel' }, null]) {
      expect(claimHeading(claim)).toBe('New claim')
    }
    expect(claimStartedLabel({ claim_id: 'clm_internal', created_at: started })).toBe(`Started ${localTime}`)
    expect(claimStartedLabel({ claim_id: 'clm_internal' })).toBe('In progress')
  })
})
