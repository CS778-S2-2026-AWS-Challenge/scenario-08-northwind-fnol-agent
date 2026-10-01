import { ApiRequestError } from './api.js'

// Claimant-facing outcome of a failed Step 4 submission (agreement acceptance or
// Claim creation). The submission flow decides what to do; this module only says
// which kind of failure it was and how to tell the claimant in plain words.

export function isDefinitiveSubmissionRefusal(requestError) {
  return requestError instanceof ApiRequestError
    && (requestError.status === 409 || requestError.status === 422)
}

const UNCLEAR = Object.freeze({
  kind: 'unknown',
  title: "We're not sure it went through",
  message: "We're not sure your claim went through. Try again — it won't create a duplicate.",
})

export function submissionFailure(requestError) {
  if (requestError instanceof ApiRequestError && requestError.code === 'NETWORK_ERROR') {
    return {
      kind: 'network',
      title: "Couldn't send your claim",
      message: "We couldn't reach Northwind, so your claim hasn't been sent. Check your connection and try again.",
    }
  }
  if (isDefinitiveSubmissionRefusal(requestError)) {
    const reason = requestError.message || 'Northwind could not accept this claim.'
    return {
      kind: 'refused',
      title: "Your claim wasn't accepted",
      message: `${reason} Please check your details and try again.`,
    }
  }
  return { ...UNCLEAR }
}

// The read-back after an unclear failure could not confirm the result either.
export function submissionReconciliationFailure() {
  return { ...UNCLEAR }
}
