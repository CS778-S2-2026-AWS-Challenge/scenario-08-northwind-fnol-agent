import { describe, expect, it } from 'vitest'
import { revisionNotice } from './revision.js'

describe('revisionNotice', () => {
  it('returns a visible notice payload when a loaded Claim changes elsewhere', () => {
    expect(revisionNotice({ claim_id: 'clm_1', revision: 3 }, { claim_id: 'clm_1', revision: 4 }))
      .toEqual({ claimId: 'clm_1', revision: 4 })
  })

  it('does not warn for the same revision or a different Claim', () => {
    expect(revisionNotice({ claim_id: 'clm_1', revision: 3 }, { claim_id: 'clm_1', revision: 3 })).toBeNull()
    expect(revisionNotice({ claim_id: 'clm_1', revision: 3 }, { claim_id: 'clm_2', revision: 4 })).toBeNull()
  })
})
