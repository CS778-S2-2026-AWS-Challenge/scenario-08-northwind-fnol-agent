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

function reportUpdatedLabel(updatedAt) {
  const updated = new Date(updatedAt)
  const now = new Date()
  const isToday = Number.isFinite(updated.getTime())
    && updated.getFullYear() === now.getFullYear()
    && updated.getMonth() === now.getMonth()
    && updated.getDate() === now.getDate()

  return isToday ? 'Updated today' : `Updated ${formatDateTime(updatedAt)}`
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

function ClaimHistoryProgress({ inProgress, onContinueReport }) {
  if (!inProgress.length) return null

  const [latestReport] = sortClaimsByLatestUpdate(inProgress)
  return (
    <section className="claim-history-progress" aria-labelledby="claim-history-in-progress-title">
      <span className="claim-history-progress-icon" role="img" aria-label="Report in progress">↗</span>
      <div className="claim-history-progress-copy">
        <div className="claim-history-progress-meta">
          <span>In progress</span>
          <time dateTime={latestReport.updated_at}>{reportUpdatedLabel(latestReport.updated_at)}</time>
        </div>
        <h2 id="claim-history-in-progress-title">Your report is underway</h2>
        <p>
          Finish the remaining details in your conversation. It will appear in claim history once
          Northwind creates the claim.
        </p>
      </div>
      {onContinueReport && (
        <button
          className="claim-history-progress-action"
          type="button"
          onClick={() => onContinueReport(latestReport.claim_id)}
        >
          Continue report <span aria-hidden="true">→</span>
        </button>
      )}
    </section>
  )
}

function ClaimHistoryEmpty({ onStartClaim, showStartAction }) {
  return (
    <div className="claim-history-empty">
      <span className="claim-history-empty-icon" aria-hidden="true">
        <span />
        <span />
        <span />
      </span>
      <h3>No past claims yet</h3>
      <p>Claims created by Northwind will be listed here with their latest status.</p>
      {showStartAction && onStartClaim && (
        <button className="primary-button" type="button" onClick={onStartClaim}>Start a claim</button>
      )}
    </div>
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
  showEmptyStartAction = true,
}) {
  const allClaims = claims || []
  const created = allClaims.filter(isCreatedClaim)
  const inProgress = allClaims.filter((claim) => !isCreatedClaim(claim))
  const claimCount = created.length === 1 ? '1 claim' : `${created.length} claims`

  return (
    <div className="claim-history-overview">
      {!loading && (
        <ClaimHistoryProgress inProgress={inProgress} onContinueReport={onContinueReport} />
      )}
      <section className="claim-history-past" aria-labelledby="claim-history-past-title">
        <header className="claim-history-past-header">
          <h2 id="claim-history-past-title">Past claims</h2>
          <div className="claim-history-past-actions">
            <span>{loading ? 'Loading…' : claimCount}</span>
            {!loading && created.length > 0 && onRetry && (
              <button type="button" onClick={onRetry} disabled={refreshing}>
                {refreshing ? 'Refreshing…' : 'Refresh'}
              </button>
            )}
          </div>
        </header>
        {loading ? (
          <p className="claim-history-state" role="status">Loading your Claim history…</p>
        ) : error && !created.length ? (
          <section className="claim-history-state is-error" role="alert">
            <h3>Claim history could not be loaded</h3>
            <p>{error} Your Claims have not been changed, and you can try loading them again.</p>
            <button className="secondary-button" type="button" onClick={onRetry}>Try again</button>
          </section>
        ) : (
          <>
            {error && (
              <div className="claim-history-stale" role="status">
                <strong>Showing earlier Claim records</strong>
                <p>{error} The list below may be out of date; try again to load the latest updates.</p>
                <button className="secondary-button" type="button" onClick={onRetry}>Try again</button>
              </div>
            )}
            {created.length ? (
              <ol className="claim-history-list" aria-label="Your Claims, most recently updated first">
                {sortClaimsByLatestUpdate(created).map((claim) => (
                  <ClaimHistoryRow key={claim.claim_id} claim={claim} onSelect={onSelect} />
                ))}
              </ol>
            ) : (
              <ClaimHistoryEmpty
                onStartClaim={onStartClaim}
                showStartAction={showEmptyStartAction && !inProgress.length}
              />
            )}
          </>
        )}
      </section>
    </div>
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
