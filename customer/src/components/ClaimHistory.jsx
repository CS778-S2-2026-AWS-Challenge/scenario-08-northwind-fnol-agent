import {
  claimStatusLabel,
  claimTitle,
  formatDateTime,
  responsiblePartyLabel,
  sortClaimsByLatestUpdate,
} from '../formatters.js'

// Claim history lists Claims that completed external creation. An unfinished Working Claim stays
// in conversation history and resume, which receive the same complete list (#972).
function isCreatedClaim(claim) {
  return claim.external_claim?.creation_status === 'created'
}

function claimReference(claim) {
  const claimNumber = claim.external_claim?.claim_number
  return claimNumber ? `Claim ${claimNumber}` : `Claim reference ${claim.claim_id}`
}

function ClaimHistoryRow({ claim, onSelect }) {
  const nextStep = claim.customer_next_step || {}
  const detailsId = `claim-history-${claim.claim_id}-details`
  return (
    <li>
      <button
        className="claim-history-card"
        type="button"
        onClick={() => onSelect(claim)}
        aria-label={`Open ${claimTitle(claim)}, ${claimReference(claim)}`}
        aria-describedby={detailsId}
      >
        <span className="claim-history-card-heading">
          <strong>{claimTitle(claim)}</strong>
          <span className="claim-status-badge">
            <span aria-hidden="true" />
            {claimStatusLabel(nextStep.status)}
          </span>
        </span>
        <span className="claim-history-card-reference">{claimReference(claim)}</span>
        <span className="claim-history-card-details" id={detailsId}>
          <span className="claim-history-card-summary">
            {nextStep.summary || 'No next step is available yet.'}
          </span>
          {/* Keeps the two sentences apart in the accessible description. */}
          {' '}
          <span className="claim-history-card-responsible">
            Responsible now: {responsiblePartyLabel(nextStep.responsible_party)}
          </span>
        </span>
        <span className="claim-history-card-meta">
          <time dateTime={claim.updated_at}>Updated {formatDateTime(claim.updated_at)}</time>
          <span aria-hidden="true">Open →</span>
        </span>
      </button>
    </li>
  )
}

function ClaimHistoryEmpty({ inProgress, onStartClaim, onContinueReport }) {
  if (!inProgress.length) {
    return (
      <section className="claim-history-state" aria-labelledby="claim-history-empty-title">
        <h2 id="claim-history-empty-title">No Claims yet</h2>
        <p>When Northwind creates a Claim from your report, it appears here with its status and latest update.</p>
        {onStartClaim && (
          <button className="primary-button" type="button" onClick={onStartClaim}>Start a claim</button>
        )}
      </section>
    )
  }

  const [latestReport] = sortClaimsByLatestUpdate(inProgress)
  const reports = inProgress.length === 1 ? '1 report' : `${inProgress.length} reports`
  return (
    <section className="claim-history-state" aria-labelledby="claim-history-in-progress-title">
      <h2 id="claim-history-in-progress-title">No created Claims yet</h2>
      <p>
        You have {reports} in progress. A report appears here after Northwind creates its Claim; until
        then, continue it from your conversation.
      </p>
      {onContinueReport && (
        <button className="primary-button" type="button" onClick={() => onContinueReport(latestReport.claim_id)}>
          Continue your report
        </button>
      )}
    </section>
  )
}

export default function ClaimHistory({
  claims,
  error,
  loading,
  refreshing,
  onRetry,
  onSelect,
  onStartClaim,
  onContinueReport,
}) {
  if (loading) {
    return <p className="claim-history-state" role="status">Loading your Claim history…</p>
  }

  const created = (claims || []).filter(isCreatedClaim)

  if (error && !created.length) {
    return (
      <section className="claim-history-state is-error" role="alert">
        <h2>Claim history could not be loaded</h2>
        <p>{error} Your Claims have not been changed, and you can try loading them again.</p>
        <button className="secondary-button" type="button" onClick={onRetry}>Try again</button>
      </section>
    )
  }

  if (!created.length) {
    return (
      <ClaimHistoryEmpty
        inProgress={(claims || []).filter((claim) => !isCreatedClaim(claim))}
        onStartClaim={onStartClaim}
        onContinueReport={onContinueReport}
      />
    )
  }

  return (
    <>
      <div className="claim-history-toolbar">
        <p>{created.length} saved {created.length === 1 ? 'Claim' : 'Claims'}</p>
        <button className="secondary-button" type="button" onClick={onRetry} disabled={refreshing}>
          {refreshing ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>
      {error && (
        <div className="claim-history-stale" role="status">
          <strong>Showing earlier Claim records</strong>
          <p>{error} The list below may be out of date; try again to load the latest updates.</p>
          <button className="secondary-button" type="button" onClick={onRetry}>Try again</button>
        </div>
      )}
      <ol className="claim-history-list" aria-label="Your Claims, most recently updated first">
        {sortClaimsByLatestUpdate(created).map((claim) => (
          <ClaimHistoryRow key={claim.claim_id} claim={claim} onSelect={onSelect} />
        ))}
      </ol>
    </>
  )
}

export function ClaimFeatureDirectory({ claim, onOpenEvidence }) {
  const nextStep = claim.customer_next_step || {}
  const claimNumber = claim.external_claim?.claim_number || claim.claim_id
  const statusLabel = claimStatusLabel(nextStep.status)
  const responsibleParty = responsiblePartyLabel(nextStep.responsible_party)

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
