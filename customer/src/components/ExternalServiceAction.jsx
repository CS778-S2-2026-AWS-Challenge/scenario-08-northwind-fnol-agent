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
  const succeeded = action.status === 'assigned' || action.status === 'queued'

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
        {action.limitations?.length > 0 && (
          <div className="service-limitations">
            {action.limitations.map((limitation) => <p key={limitation}>{limitation}</p>)}
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
      {succeeded && routing && (
        <div className="service-result is-success" role="status">
          <strong>{action.status === 'assigned' ? 'Assessor assigned' : 'Request accepted into the assessor queue'}</strong>
          <p>{routing.next_step}</p>
          <dl>{routing.assessor_reference && <div><dt>Assessor reference</dt><dd>{routing.assessor_reference}</dd></div>}{routing.queue_reference && <div><dt>Queue reference</dt><dd>{routing.queue_reference}</dd></div>}{routing.expected_by && <div><dt>Expected by</dt><dd>{new Date(routing.expected_by).toLocaleString()}</dd></div>}</dl>
        </div>
      )}
      {action.can_request && (!error || error.retryable) && (
        <button className="primary-button" type="button" onClick={onRequest} disabled={isBusy || (needsConsent && !consentChecked)}>
          {isRecordingConsent ? 'Recording permission...' : isRequesting ? 'Sending request...' : error?.retryable ? 'Retry assessment request' : needsConsent ? 'Agree and request assessor' : 'Request assessor'}
        </button>
      )}
    </section>
  )
}
