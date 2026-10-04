// Claimant wording approved by the AT-10 controlled assessor scenario, one entry per
// provider-neutral failure code. The claim itself is unchanged by a failure, so this is
// what the claimant sees when they return to a claim whose last attempt did not succeed.
export const FAILURE_WORDING = {
  timeout: 'The assessment request did not complete. Your claim is saved; Northwind can safely retry the same request.',
  unavailable: 'The assessment service is unavailable right now. Your claim is saved, and no assessor has been assigned.',
  access_denied: 'We could not send the assessment request because its authorisation was not accepted. Northwind must review the request before trying again.',
  malformed: 'The assessment service returned an unusable response. Your claim is saved; Northwind must review the integration response.',
}

// An attempt that may already have reached the assessor is not one of AT-10's four
// failure outcomes: it is the same `timeout` code with a delivery that scenario does
// not describe. The wording is proposed on Discussion #758 and is deliberately the
// only sentence here that does not come from AT-10; it says what is known, what is
// unchanged, and what the claimant should not do.
export const RECONCILIATION_WORDING =
  'The assessment request may already have reached the assessor, but we did not get a confirmation. Your claim is saved and unchanged. Northwind is checking with the assessor before anything is sent again, so please do not resend it.'

export function claimantStatusCopy(action) {
  if (action.effective_label || action.status_detail) {
    return {
      label: action.effective_label || 'External service update',
      detail: action.status_detail
        || (typeof action.next_action === 'string' ? action.next_action : null)
        || 'Northwind has recorded an external-service update for this claim.',
      attention: Boolean(action.attention_required),
    }
  }
  if (action.status === 'consent_required') {
    return {
      label: 'Permission needed',
      detail: 'Northwind needs your permission before it can share the listed details for this service.',
      attention: false,
    }
  }
  if (action.status === 'ready_to_request') {
    return {
      label: 'Ready to request',
      detail: 'The required permission and claim details are ready. No request has been sent yet.',
      attention: false,
    }
  }
  if (action.status === 'pending_input') {
    return {
      label: 'Permission recorded',
      detail: 'Northwind will continue this request when its required claim details are ready.',
      attention: false,
    }
  }
  if (action.status === 'manual_available') {
    return {
      label: 'Official contact ready',
      detail: 'Use the registered official contact below. Northwind has not created an external task.',
      attention: false,
    }
  }
  if (action.status === 'consent_declined') {
    return {
      label: 'Not requested',
      detail: 'No information was shared and no external request was created.',
      attention: false,
    }
  }
  if (action.status === 'consent_withdrawn') {
    return {
      label: 'Permission withdrawn',
      detail: 'Northwind will not send an unsubmitted request under this permission.',
      attention: false,
    }
  }
  if (action.status === 'queued') {
    return {
      label: 'Request queued',
      detail: action.routing?.next_step
        || 'The service accepted the request into its queue. This does not mean the service is complete.',
      attention: false,
    }
  }
  if (action.status === 'assigned') {
    return {
      label: 'Assessor assigned',
      detail: action.routing?.next_step
        || 'An assessor is assigned. This does not mean the assessment or claim decision is complete.',
      attention: false,
    }
  }
  if (action.status === 'retryable_failure') {
    return {
      label: 'Request did not complete',
      detail: FAILURE_WORDING[action.failure_code]
        || 'The request did not complete. Your claim is saved and Northwind can review the safe next step.',
      attention: true,
    }
  }
  if (action.status === 'terminal_failure') {
    return {
      label: 'Northwind review needed',
      detail: FAILURE_WORDING[action.failure_code]
        || 'The request did not complete. Northwind needs to review it before another request is attempted.',
      attention: true,
    }
  }
  if (action.status === 'awaiting_reconciliation') {
    return {
      label: 'Outcome not confirmed',
      detail: RECONCILIATION_WORDING,
      attention: true,
    }
  }
  return {
    label: 'External service',
    detail: 'Northwind has recorded an external-service step for this claim.',
    attention: false,
  }
}
