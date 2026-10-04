import { describe, expect, it } from 'vitest'

import { continueClaimCard } from './continueClaim.js'

const report = (claimId, updatedAt, extra = {}) => ({
  claim_id: claimId,
  incident_type: 'motor',
  created_at: '2026-10-01T01:00:00Z',
  updated_at: updatedAt,
  can_resume: false,
  open_items: [],
  ...extra,
})

describe('continue your claim card', () => {
  it('offers the latest claim that still owes something and says what', () => {
    const owed = { item_id: 'q', kind: 'document', owner: 'claimant', state: 'open', subject: 'repair_quote' }
    const card = continueClaimCard([
      report('clm_old', '2026-10-01T02:00:00Z', { can_resume: true }),
      report('clm_new', '2026-10-02T02:00:00Z', { open_items: [owed] }),
      report('clm_done', '2026-10-03T02:00:00Z'),
    ])
    expect(card.claimId).toBe('clm_new')
    expect(card.detail).toBe('Still to send: Repair quote')
  })

  it('offers nothing when no claim needs the claimant', () => {
    expect(continueClaimCard([report('clm_done', '2026-10-03T02:00:00Z')])).toBeNull()
    expect(continueClaimCard()).toBeNull()
  })
})
