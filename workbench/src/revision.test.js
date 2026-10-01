import { describe, expect, it } from 'vitest'
import { mutationResultRevision, revisionNotice } from './revision.js'

describe('revisionNotice', () => {
  it('returns a visible notice payload when a loaded Claim changes elsewhere', () => {
    expect(revisionNotice({ claim_id: 'clm_1', revision: 3 }, { claim_id: 'clm_1', revision: 4 }))
      .toEqual({ claimId: 'clm_1', revision: 4 })
  })

  it('does not warn for the same revision or a different Claim', () => {
    expect(revisionNotice({ claim_id: 'clm_1', revision: 3 }, { claim_id: 'clm_1', revision: 3 })).toBeNull()
    expect(revisionNotice({ claim_id: 'clm_1', revision: 3 }, { claim_id: 'clm_2', revision: 4 })).toBeNull()
  })

  it('does not warn for a revision produced by the current staff member', () => {
    expect(revisionNotice(
      { claim_id: 'clm_1', revision: 4 },
      { claim_id: 'clm_1', revision: 5 },
      5,
    )).toBeNull()
  })

  it('still warns when another session changes the Claim after an own mutation', () => {
    expect(revisionNotice(
      { claim_id: 'clm_1', revision: 5 },
      { claim_id: 'clm_1', revision: 6 },
      5,
    )).toEqual({ claimId: 'clm_1', revision: 6 })
  })
})

describe('mutationResultRevision', () => {
  it.each([
    ['a Claim projection', { claim_id: 'clm_1', revision: 7 }, 7],
    ['a staff message response', { claim_id: 'clm_1', claim_revision: 8 }, 8],
    ['a response without a Claim revision', { decision_id: 'cdec_1' }, null],
    ['an empty response', null, null],
  ])('reads %s', (_name, result, expected) => {
    expect(mutationResultRevision(result)).toBe(expected)
  })
})
