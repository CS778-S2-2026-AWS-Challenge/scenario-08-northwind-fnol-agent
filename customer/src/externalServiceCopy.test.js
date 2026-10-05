import { describe, expect, it } from 'vitest'

import { claimantStatusCopy } from './externalServiceCopy.js'

describe('claimantStatusCopy', () => {
  it('uses the status label projected by the backend', () => {
    expect(claimantStatusCopy({
      status: 'assigned',
      status_label: 'Assessor assigned',
      status_detail: 'An assessor is assigned to this request.',
    })).toEqual({
      label: 'Assessor assigned',
      detail: 'An assessor is assigned to this request.',
      attention: false,
    })
  })

  it('does not treat an unsupported effective_label field as the claimant label', () => {
    expect(claimantStatusCopy({
      status: 'assigned',
      effective_label: 'Incorrect legacy label',
      status_detail: 'The projected status is available.',
    })).toEqual({
      label: 'External service update',
      detail: 'The projected status is available.',
      attention: false,
    })
  })
})
