// Claimant wording approved by the AT-10 controlled assessor scenario, one entry per
// provider-neutral failure code. The claim itself is unchanged by a failure, so this is
// what the claimant sees when they return to a claim whose last attempt did not succeed.
const FAILURE_WORDING = {
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
const RECONCILIATION_WORDING =
  'The assessment request may already have reached the assessor, but we did not get a confirmation. Your claim is saved and unchanged. Northwind is checking with the assessor before anything is sent again, so please do not resend it.'

function claimantStatusCopy(action) {
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

function consentLabel(consentStatus) {
  if (consentStatus === 'granted') return 'Permission recorded'
  if (consentStatus === 'withdrawn') return 'Permission withdrawn'
  return 'Not recorded'
}

export function ExternalServiceOverview({ action }) {
  if (!action) return null
  const state = claimantStatusCopy(action)
  const routing = action.routing
  const limitations = routing?.limitations || []

  return (
    <section className="external-service external-service-overview" aria-labelledby="external-service-overview-title">
      <p className="transfer-label">External service</p>
      <h2 id="external-service-overview-title">{action.service_name}</h2>
      <p>{action.purpose}</p>
      <div className={`service-result ${state.attention ? 'is-error' : 'is-success'}`} role="status">
        <strong>{state.label}</strong>
        <p>{state.detail}</p>
        {limitations.map((limitation) => (
          <p className="service-limitation" key={limitation}>{limitation}</p>
        ))}
      </div>
      <dl className="service-details">
        <div><dt>Service</dt><dd>{action.service_name}</dd></div>
        <div><dt>Provider</dt><dd>{action.provider}</dd></div>
        <div><dt>Permission</dt><dd>{consentLabel(action.consent_status)}</dd></div>
      </dl>
      <details className="service-disclosure" open>
        <summary>What Northwind may share</summary>
        <ul className="shared-data-list">
          {action.shared_data_summary.map((item) => <li key={item}>{item}</li>)}
        </ul>
      </details>
      {routing && (
        <dl className="service-details">
          {routing.assessor_reference && <div><dt>Assessor reference</dt><dd>{routing.assessor_reference}</dd></div>}
          {routing.queue_reference && <div><dt>Queue reference</dt><dd>{routing.queue_reference}</dd></div>}
          {routing.expected_by && <div><dt>Expected by</dt><dd>{new Date(routing.expected_by).toLocaleString()}</dd></div>}
        </dl>
      )}
    </section>
  )
}


export default function ExternalServiceAction({
  action,
  consentChecked,
  setConsentChecked,
  onRequest,
  status,
  error,
}) {
  const isRecordingConsent = status === 'granting-service-consent'
  const isRequesting = status === 'requesting-assessor'
  const isBusy = isRecordingConsent || isRequesting
  const needsConsent = action.status === 'consent_required'
  const routing = action.routing
  const limitations = routing?.limitations || []
  const succeeded = action.status === 'assigned' || action.status === 'queued'
  const retryableFailure = action.status === 'retryable_failure'
  const awaitingReconciliation = action.status === 'awaiting_reconciliation'
  const recordedFailure = !error && (retryableFailure || action.status === 'terminal_failure')

  return (
    <section className="external-service" aria-labelledby="external-service-title">
      <p className="transfer-label">Optional next step</p>
      <h2 id="external-service-title">Request a vehicle damage assessment</h2>
      <p>{action.purpose}</p>
      <dl className="service-details">
        <div><dt>Service</dt><dd>{action.service_name}</dd></div>
        <div><dt>Provider</dt><dd>{action.provider}</dd></div>
      </dl>
      <details className="service-disclosure">
        <summary>What will be shared</summary>
        <ul className="shared-data-list">
          {action.shared_data_summary.map((item) => <li key={item}>{item}</li>)}
        </ul>
        {limitations.length > 0 && (
          <div className="service-limitations">
            {limitations.map((limitation) => <p key={limitation}>{limitation}</p>)}
          </div>
        )}
      </details>
      {needsConsent && (
        <label className="service-consent">
          <input type="checkbox" checked={consentChecked} onChange={(event) => setConsentChecked(event.target.checked)} disabled={isBusy} />
          <span>I give Northwind permission to share only these details for this assessment request.</span>
        </label>
      )}
      {isBusy && <div className="service-progress" role="status"><span className="status-dot" /><span>{isRecordingConsent ? 'Recording your permission...' : 'Sending the assessment request...'}</span></div>}
      {error && (
        <div className="service-result is-error" role="alert">
          <strong>Assessment request not sent</strong>
          <p>{error.message}</p>
          <p>Your claim is saved, and no assessor has been assigned.</p>
          {!error.retryable && <p>Northwind needs to review this before another request.</p>}
        </div>
      )}
      {recordedFailure && (
        <div className="service-result is-error" role="status">
          <strong>Assessment request not sent</strong>
          <p>{FAILURE_WORDING[action.failure_code] ?? 'The assessment request did not complete. Your claim is saved, and no assessor has been assigned.'}</p>
          {!retryableFailure && <p>Northwind needs to review this before another request.</p>}
        </div>
      )}
      {awaitingReconciliation && !error && (
        <div className="service-result is-error" role="status">
          <strong>Assessment request outcome not confirmed</strong>
          <p>{RECONCILIATION_WORDING}</p>
        </div>
      )}
      {succeeded && routing && (
        <div className="service-result is-success" role="status">
          <strong>{action.status === 'assigned' ? 'Assessor assigned' : 'Request accepted into the assessor queue'}</strong>
          <p>{routing.next_step}</p>
          {limitations.map((limitation) => (
            <p className="service-limitation" key={limitation}>{limitation}</p>
          ))}
          <dl>{routing.assessor_reference && <div><dt>Assessor reference</dt><dd>{routing.assessor_reference}</dd></div>}{routing.queue_reference && <div><dt>Queue reference</dt><dd>{routing.queue_reference}</dd></div>}{routing.expected_by && <div><dt>Expected by</dt><dd>{new Date(routing.expected_by).toLocaleString()}</dd></div>}</dl>
        </div>
      )}
      {action.can_request && (!error || error.retryable) && (
        <button className="primary-button" type="button" onClick={onRequest} disabled={isBusy || (needsConsent && !consentChecked)}>
          {isRecordingConsent ? 'Recording permission...' : isRequesting ? 'Sending request...' : (error?.retryable || retryableFailure) ? 'Retry assessment request' : needsConsent ? 'Agree and request assessor' : 'Request assessor'}
        </button>
      )}
    </section>
  )
}
