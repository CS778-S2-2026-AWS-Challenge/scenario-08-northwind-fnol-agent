import { ExternalServiceOverview } from './ExternalServiceAction.jsx'
import './ExternalServicesPage.css'

function InfoIcon({ name }) {
  if (name === 'bell') {
    return (
      <svg viewBox="0 0 24 24" aria-hidden="true">
        <path d="M18 9a6 6 0 0 0-12 0c0 7-3 7-3 9h18c0-2-3-2-3-9M10 21h4" />
      </svg>
    )
  }
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <rect x="5" y="10" width="14" height="11" rx="2" />
      <path d="M8 10V7a4 4 0 0 1 8 0v3M12 14v3" />
    </svg>
  )
}

function StatusIllustration() {
  return (
    <svg className="external-services-illustration" viewBox="0 0 180 116" aria-hidden="true">
      <path className="illustration-road" d="M18 87h144" />
      <path className="illustration-car" d="M51 72l8-22c2-5 6-8 12-8h40c6 0 10 3 12 8l8 22" />
      <path className="illustration-car" d="M43 72h96c5 0 9 4 9 9v12H34V81c0-5 4-9 9-9Z" />
      <path className="illustration-window" d="M66 51h49l6 17H60z" />
      <circle className="illustration-wheel" cx="57" cy="94" r="10" />
      <circle className="illustration-wheel" cx="125" cy="94" r="10" />
      <path className="illustration-check" d="M129 28l8 8 16-18" />
    </svg>
  )
}

function EmptyServiceState() {
  return (
    <section className="external-services-status-card is-empty" aria-labelledby="external-services-status-title">
      <div className="external-services-status-icon" aria-hidden="true">
        <svg viewBox="0 0 24 24"><path d="m6 12 4 4 8-9" /></svg>
      </div>
      <div className="external-services-status-copy">
        <p className="external-services-state-label">Current status</p>
        <h2 id="external-services-status-title">No external service is needed right now</h2>
        <p>You don’t need to do anything. If we later arrange an assessor, repairer, or other provider, we’ll add the details here before they contact you.</p>
      </div>
      <StatusIllustration />
    </section>
  )
}

export default function ExternalServicesPage({
  action,
  claim,
  onBackToOverview,
  onWhatToProvide,
}) {
  return (
    <div className="external-services-page">
      <nav className="external-services-breadcrumb" aria-label="Breadcrumb">
        <button type="button" onClick={onBackToOverview}>Current claim</button>
        <span aria-hidden="true">/</span>
        <span aria-current="page">External services</span>
      </nav>

      <header className="external-services-page-heading">
        <div>
          <h1>External services</h1>
          <p>See whether another provider is involved in your claim, what information may be shared, and what happens next.</p>
        </div>
        <p className="external-services-claim-number"><span>Claim</span> {claim?.claim_id}</p>
      </header>

      {action ? <ExternalServiceOverview action={action} /> : <EmptyServiceState />}

      <div className="external-services-assurances">
        <article>
          <span className="external-services-info-icon"><InfoIcon name="bell" /></span>
          <div>
            <h2>We’ll keep you informed</h2>
            <p>You’ll see the provider’s name, why they’re involved, and what they’ll do.</p>
          </div>
        </article>
        <article>
          <span className="external-services-info-icon"><InfoIcon name="lock" /></span>
          <div>
            <h2>Your information stays protected</h2>
            <p>Only information needed to progress this claim will be shared.</p>
          </div>
        </article>
      </div>

      <footer className="external-services-next-step">
        <div>
          <strong>Next: check what to provide</strong>
          <p>Review any documents or photos we may need.</p>
        </div>
        <div className="external-services-next-actions">
          <button className="secondary-button" type="button" onClick={onBackToOverview}>Back to overview</button>
          <button className="primary-button" type="button" onClick={onWhatToProvide}>
            <span>What to provide</span>
            <span aria-hidden="true">→</span>
          </button>
        </div>
      </footer>
    </div>
  )
}
