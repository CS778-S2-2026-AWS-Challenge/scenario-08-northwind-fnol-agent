import {
  claimTitle,
  formatDateTime,
  formatIdentifierLabel,
  sortClaimsByLatestUpdate,
} from '../formatters.js'

export default function ClaimHistory({ claims, error, loading, refreshing, onRetry, onSelect }) {
  if (loading) {
    return <p className="claim-history-state" role="status">Loading your Claim history…</p>
  }

  if (error && !claims?.length) {
    return (
      <section className="claim-history-state is-error" role="alert">
        <h2>Claim history could not be loaded</h2>
        <p>{error} Your Claims have not been changed.</p>
        <button className="secondary-button" type="button" onClick={onRetry}>Try again</button>
      </section>
    )
  }

  if (!claims?.length) {
    return (
      <section className="claim-history-state" aria-labelledby="claim-history-empty-title">
        <h2 id="claim-history-empty-title">No Claims recorded yet</h2>
        <p>After Northwind confirms a new Claim, it will appear here with its latest update time.</p>
      </section>
    )
  }

  return (
    <>
      <div className="claim-history-toolbar">
        <p>{claims.length} saved {claims.length === 1 ? 'Claim' : 'Claims'}</p>
        <button className="secondary-button" type="button" onClick={onRetry} disabled={refreshing}>
          {refreshing ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>
      {error && (
        <div className="claim-history-stale" role="status">
          <strong>Showing earlier Claim records</strong>
          <p>{error} The list below may be out of date.</p>
          <button className="secondary-button" type="button" onClick={onRetry}>Try again</button>
        </div>
      )}
      <ol className="claim-history-list" aria-label="Your Claims, most recently updated first">
        {sortClaimsByLatestUpdate(claims).map((claim) => (
          <li key={claim.claim_id}>
            <button
              className="claim-history-card"
              type="button"
              onClick={() => onSelect(claim)}
              aria-label={`Open ${claimTitle(claim)} ${claim.claim_id}`}
            >
              <span className="claim-history-card-heading">
                <strong>{claimTitle(claim)}</strong>
                <span aria-hidden="true">→</span>
              </span>
              <span className="claim-history-card-summary">
                {claim.customer_next_step?.summary || 'Review this Claim and its available information.'}
              </span>
              <span className="claim-history-card-meta">
                <span>{claim.claim_id}</span>
                <time dateTime={claim.updated_at}>Updated {formatDateTime(claim.updated_at)}</time>
              </span>
            </button>
          </li>
        ))}
      </ol>
    </>
  )
}

export function ClaimFeatureDirectory({ claim, onOpenEvidence }) {
  const nextStep = claim.customer_next_step || {}
  const claimNumber = claim.external_claim?.claim_number || claim.claim_id
  const statusLabel = formatIdentifierLabel(nextStep.status || claim.workflow_state || 'status unavailable')
  const responsibleParty = {
    claimant: 'You',
    northwind: 'Northwind claims team',
    claims_professional: 'Claims professional',
    external_party: 'External service provider',
  }[nextStep.responsible_party] || 'Not available'

  return (
    <section className="claim-feature-directory" aria-labelledby="claim-features-title">
      <div className="claim-feature-summary">
        <header className="claim-status-header">
          <div>
            <p className="claim-status-kicker">
              {claim.external_claim?.claim_number ? 'Claim number' : 'Claim reference'}
            </p>
            <h2 id="claim-features-title">{claimNumber}</h2>
          </div>
          <span className="claim-status-badge">
            <span aria-hidden="true" />
            {statusLabel}
          </span>
        </header>
        <dl className="claim-status-details">
          <div>
            <dt>Responsible now</dt>
            <dd>{responsibleParty}</dd>
          </div>
          <div>
            <dt>Estimated wait</dt>
            <dd>
              {nextStep.expected_by
                ? `Expected by ${formatDateTime(nextStep.expected_by)}`
                : 'No estimate available'}
            </dd>
          </div>
          <div className="claim-status-next-step">
            <dt>Next step</dt>
            <dd>{nextStep.summary || 'No next step is available yet.'}</dd>
          </div>
        </dl>
        <p className="claim-status-updated">
          <span aria-hidden="true">↻</span>
          <time dateTime={claim.updated_at}>Last updated {formatDateTime(claim.updated_at)}</time>
        </p>
      </div>
      <div className="claim-feature-list" aria-label="Features available for this Claim">
        <button className="claim-feature-card" type="button" onClick={onOpenEvidence}>
          <span className="claim-feature-icon" aria-hidden="true">↗</span>
          <span className="claim-feature-copy">
            <strong>Evidence history</strong>
            <span>Review the files and supporting material recorded for this Claim.</span>
          </span>
          <span className="claim-feature-open" aria-hidden="true">Open →</span>
        </button>
      </div>
    </section>
  )
}
