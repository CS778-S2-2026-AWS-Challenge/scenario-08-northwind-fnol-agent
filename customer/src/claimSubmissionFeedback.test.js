import { describe, expect, it } from 'vitest'

import { ApiRequestError } from './api.js'
import {
  isDefinitiveSubmissionRefusal,
  submissionFailure,
  submissionReconciliationFailure,
} from './claimSubmissionFeedback.js'

function apiError(status, code, message = 'The claim changed since you opened it.') {
  return Object.assign(new ApiRequestError(message), { status, code })
}

describe('submission failure feedback', () => {
  it('tells the claimant a network failure means nothing was sent', () => {
    const failure = submissionFailure(apiError(0, 'NETWORK_ERROR'))

    expect(failure.kind).toBe('network')
    expect(failure.title).toBe("Couldn't send your claim")
    expect(failure.message).toContain("your claim hasn't been sent")
  })

  it.each([409, 422])('treats HTTP %s as a refusal and keeps the server reason', (status) => {
    const failure = submissionFailure(apiError(status, 'REVISION_CONFLICT'))

    expect(isDefinitiveSubmissionRefusal(apiError(status, 'X'))).toBe(true)
    expect(failure.kind).toBe('refused')
    expect(failure.title).toBe("Your claim wasn't accepted")
    expect(failure.message).toBe(
      'The claim changed since you opened it. Please check your details and try again.',
    )
  })

  it('treats other failures and an inconclusive read-back as unclear', () => {
    const fromServer = submissionFailure(apiError(503, 'CLAIM_SERVICE_UNAVAILABLE'))
    const fromReadback = submissionReconciliationFailure()

    for (const failure of [fromServer, fromReadback, submissionFailure(new Error('boom'))]) {
      expect(failure.kind).toBe('unknown')
      expect(failure.message).toBe(
        "We're not sure your claim went through. Try again — it won't create a duplicate.",
      )
    }
    expect(isDefinitiveSubmissionRefusal(apiError(503, 'X'))).toBe(false)
  })

  it('never uses internal wording', () => {
    const messages = [
      submissionFailure(apiError(0, 'NETWORK_ERROR')),
      submissionFailure(apiError(409, 'X')),
      submissionFailure(apiError(503, 'X')),
    ].map((failure) => `${failure.title} ${failure.message}`.toLowerCase())

    for (const text of messages) {
      expect(text).not.toMatch(/identity|reconcile|this screen|submission identity/)
    }
  })
})
