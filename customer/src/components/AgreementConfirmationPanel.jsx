import { useState } from 'react'
import './AgreementConfirmationPanel.css'

const SUBMISSION_PROGRESS_TOTAL = 4
const SUBMISSION_PROGRESS_BY_ACTION = Object.freeze({
  'claimant.review_agreement': Object.freeze({ current: 4, label: 'Review & submit' }),
  'claimant.create_claim': Object.freeze({ current: 4, label: 'Submit claim' }),
})
const CLAIM_CREATION_STATUS_LABELS = Object.freeze({
  created: 'Submitted',
})

function readable(value) {
  if (value === null || value === undefined || value === '') return 'Not recorded'
  if (typeof value === 'string' || typeof value === 'number') return String(value)
  if (typeof value === 'boolean') return value ? 'Yes' : 'No'
  try {
    return JSON.stringify(value)
  } catch {
    return 'Recorded'
  }
}

function fieldValue(claim, code) {
  return claim?.form?.[code]?.value
}

function claimSubmissionProgress(claim) {
  const action = claim?.primary_action
  const projectedStep = SUBMISSION_PROGRESS_BY_ACTION[action?.action_code]
  const currentRevision = Number(claim?.revision)
  const projectedRevision = Number(action?.claim_revision)

  if (
    !projectedStep
    || !action.available
    || !Number.isFinite(currentRevision)
    || !Number.isFinite(projectedRevision)
    || projectedRevision !== currentRevision
  ) {
    return {
      available: false,
      current: null,
      total: SUBMISSION_PROGRESS_TOTAL,
      label: 'Review & submit',
      actionCode: null,
    }
  }

  return {
    available: true,
    current: projectedStep.current,
    total: SUBMISSION_PROGRESS_TOTAL,
    label: projectedStep.label,
    actionCode: action.action_code,
  }
}

function humanize(value) {
  if (value === null || value === undefined || value === '') return 'Not recorded'
  return String(value)
    .replaceAll('_', ' ')
    .replace(/\b\w/g, (letter) => letter.toUpperCase())
}

function dateTimePresentation(value, locale = 'en-NZ') {
  if (!value) return null
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) {
    return { label: readable(value), dateTime: null }
  }

  const dateLabel = new Intl.DateTimeFormat(locale || 'en-NZ', {
    day: 'numeric',
    month: 'short',
    year: 'numeric',
  }).format(date)
  const timeLabel = new Intl.DateTimeFormat(locale || 'en-NZ', {
    hour: 'numeric',
    minute: '2-digit',
    hour12: true,
  }).format(date)

  return {
    label: `${dateLabel} · ${timeLabel}`,
    dateTime: date.toISOString(),
  }
}

function DateTimeValue({ value }) {
  if (!value) return null
  return value.dateTime
    ? <time dateTime={value.dateTime}>{value.label}</time>
    : value.label
}

function evidenceStatus(value) {
  const statuses = {
    received: { label: 'Provided', tone: 'success' },
    unofficial: { label: 'Provided · review pending', tone: 'warning' },
    invalid: { label: 'Needs attention', tone: 'warning' },
    pending: { label: 'Processing', tone: 'warning' },
    unavailable: { label: 'Unavailable', tone: 'warning' },
    in_conflict: { label: 'Needs review', tone: 'warning' },
    not_started: { label: 'Not provided', tone: 'warning' },
  }

  return statuses[value] || (value
    ? { label: humanize(value), tone: 'neutral' }
    : { label: 'Not provided', tone: 'warning' })
}

function StatusBadge({ label, tone }) {
  return (
    <span className={`agreement-status-badge is-${tone}`}>
      <span aria-hidden="true" />
      {label}
    </span>
  )
}

export default function AgreementConfirmationPanel({
  claim,
  busy,
  status,
  onSubmit,
  onReviewInformation,
  onReturnToConversation,
  submissionError = null,
}) {
  const externalClaim = claim?.external_claim
  const agreement = claim?.submission_agreement
  const submissionProgress = claimSubmissionProgress(claim)
  const alreadyAccepted = submissionProgress.actionCode === 'claimant.create_claim'
  const confirmationScope = `${claim?.claim_id ?? ''}:${agreement?.agreement_id ?? ''}:${agreement?.version ?? ''}`
  const [confirmationState, setConfirmationState] = useState(() => ({
    scope: confirmationScope,
    values: {},
  }))
  const confirmations = (
    confirmationState.scope === confirmationScope
      ? confirmationState.values
      : {}
  )

  const requiredComplete = agreement
    ? agreement.confirmations
        .filter((confirmation) => confirmation.required)
        .every((confirmation) => confirmations[confirmation.key] === true)
    : false

  if (externalClaim) {
    const submittedAt = dateTimePresentation(externalClaim.created_at, claim?.locale)
    const expectedBy = dateTimePresentation(externalClaim.expected_by, claim?.locale)
    const creationStatus = CLAIM_CREATION_STATUS_LABELS[externalClaim.creation_status]
      || humanize(externalClaim.creation_status)
    const preferredContact = humanize(fieldValue(claim, 'claimant.contact_preference'))

    return (
      <section className="claim-submitted-page" aria-labelledby="claim-submitted-heading">
        <article className="claim-submitted-card">
          <header className="claim-submitted-hero" role="status">
            <span className="claim-submitted-icon" aria-hidden="true">✓</span>
            <div>
              <h1 id="claim-submitted-heading">Your claim has been submitted</h1>
              <p>
                We’ve received your claim and will now review the information provided.
                Keep your reference number handy.
              </p>
            </div>
          </header>

          <section className="claim-submitted-reference" aria-labelledby="claim-reference-heading">
            <p id="claim-reference-heading">Claim reference</p>
            <strong>{readable(externalClaim.claim_number)}</strong>
          </section>

          <div className="claim-submitted-overview">
            <section className="claim-submitted-timeline" aria-labelledby="claim-next-steps-heading">
              <h2 id="claim-next-steps-heading">What happens next</h2>
              <ol>
                <li className="is-complete">
                  <span className="claim-submitted-stage-marker" aria-hidden="true">
                    <span>✓</span>
                  </span>
                  <div className="claim-submitted-stage-content">
                    <header>
                      <h3>Claim submitted</h3>
                      <span>Completed</span>
                    </header>
                    <p>{submittedAt ? <DateTimeValue value={submittedAt} /> : 'Completed'}</p>
                  </div>
                </li>
                <li className="is-current">
                  <span className="claim-submitted-stage-marker" aria-hidden="true">
                    <span />
                  </span>
                  <div className="claim-submitted-stage-content">
                    <header>
                      <h3>{externalClaim.route
                        ? readable(externalClaim.route)
                        : externalClaim.next_step
                          ? readable(externalClaim.next_step)
                          : 'Next step unavailable'}</h3>
                      <span>Current</span>
                    </header>
                    {externalClaim.route && externalClaim.next_step && (
                      <p>{readable(externalClaim.next_step)}</p>
                    )}
                    {expectedBy && (
                      <p>Expected by <DateTimeValue value={expectedBy} /></p>
                    )}
                  </div>
                </li>
              </ol>
            </section>

            <section className="claim-submitted-details" aria-labelledby="claim-details-heading">
              <h2 id="claim-details-heading">Claim details</h2>
              <dl>
                <div>
                  <dt>Status</dt>
                  <dd><span className="claim-submitted-status">{creationStatus}</span></dd>
                </div>
                <div>
                  <dt>Claim type</dt>
                  <dd>{humanize(claim.incident_type)}</dd>
                </div>
                <div>
                  <dt>Preferred contact</dt>
                  <dd>{preferredContact}</dd>
                </div>
              </dl>
            </section>
          </div>

          <footer className="claim-submitted-actions">
            <button
              className="primary-button"
              type="button"
              onClick={onReturnToConversation}
            >
              Back to conversation
            </button>
          </footer>
        </article>
      </section>
    )
  }

  if (!agreement) {
    return (
      <div className="claim-history-state is-error" role="alert">
        <h2>Agreement unavailable</h2>
        <p>Reload this Claim before attempting final submission.</p>
      </div>
    )
  }

  const insuredSubject = (
    fieldValue(claim, 'property.address')
    || fieldValue(claim, 'vehicle.registration')
    || (
      Array.isArray(claim.contents_items) && claim.contents_items.length
        ? `${claim.contents_items.length} contents item${claim.contents_items.length === 1 ? '' : 's'}`
        : null
    )
  )

  const contactPreference = fieldValue(claim, 'claimant.contact_preference')
  const incidentDate = fieldValue(claim, 'incident.occurred_at')
  const incidentDateDisplay = dateTimePresentation(incidentDate, claim?.locale)
  const evidence = evidenceStatus(
    claim.evidence_summary?.state || claim.evidence_summary?.status,
  )
  const insuredSubjectLabel = fieldValue(claim, 'property.address')
    ? 'Insured property'
    : fieldValue(claim, 'vehicle.registration')
      ? 'Insured vehicle'
      : Array.isArray(claim.contents_items) && claim.contents_items.length
        ? 'Insured contents'
        : 'Insured item or property'
  const submitting = status === 'creating-claim'

  return (
    <div className="agreement-review-page">
      <article className="agreement-review-card" aria-labelledby="agreement-heading">
        <header className="agreement-page-header">
          <div className={`agreement-progress ${submissionProgress.available ? '' : 'is-unavailable'}`.trim()}>
            <div
              className="agreement-progress-indicator"
              role={submissionProgress.available ? 'progressbar' : undefined}
              aria-label={submissionProgress.available ? 'Claim submission progress' : undefined}
              aria-valuemin={submissionProgress.available ? 1 : undefined}
              aria-valuemax={submissionProgress.available ? submissionProgress.total : undefined}
              aria-valuenow={submissionProgress.available ? submissionProgress.current : undefined}
              aria-valuetext={submissionProgress.available
                ? `Step ${submissionProgress.current} of ${submissionProgress.total}: ${submissionProgress.label}`
                : undefined}
            >
              <ol aria-hidden="true">
                {Array.from({ length: submissionProgress.total }, (_, index) => index + 1).map((step) => (
                  <li
                    className={step < submissionProgress.current
                      ? 'is-complete'
                      : step === submissionProgress.current
                        ? 'is-current'
                        : 'is-pending'}
                    key={step}
                  >
                    <span aria-hidden="true" />
                  </li>
                ))}
              </ol>
            </div>
            {submissionProgress.available ? (
              <p>
                Step {submissionProgress.current} of {submissionProgress.total}{' '}
                <span aria-hidden="true">·</span> {submissionProgress.label}
              </p>
            ) : (
              <p role="status">Claim progress unavailable <span aria-hidden="true">·</span> Review &amp; submit</p>
            )}
          </div>
          <h1 id="agreement-heading">Review and submit your claim</h1>
          <p>Check the information below. You can still make changes before submitting.</p>
        </header>

        <section className="agreement-summary" aria-labelledby="claim-summary-heading">
          <header className="agreement-section-heading">
            <div>
              <h2 id="claim-summary-heading">Claim summary</h2>
              <p>The key details we’ll use to process your claim.</p>
            </div>
            <button
              className="agreement-edit-action"
              type="button"
              onClick={onReviewInformation}
              disabled={busy}
            >
              Edit details
            </button>
          </header>

          <dl className="agreement-summary-grid">
            <div>
              <dt>Claim type</dt>
              <dd>{humanize(claim.incident_type)}</dd>
            </div>
            <div>
              <dt>Incident date</dt>
              <dd>
                {incidentDate ? (
                  <DateTimeValue value={incidentDateDisplay} />
                ) : 'Not recorded'}
              </dd>
            </div>
            <div>
              <dt>{insuredSubjectLabel}</dt>
              <dd>{readable(insuredSubject)}</dd>
            </div>
            <div>
              <dt>Preferred contact</dt>
              <dd>{humanize(contactPreference)}</dd>
            </div>
            <div>
              <dt>Evidence</dt>
              <dd><StatusBadge label={evidence.label} tone={evidence.tone} /></dd>
            </div>
            <div>
              <dt>Payout details</dt>
              <dd>
                <StatusBadge
                  label={claim.payment_destination_id ? 'Saved' : 'Not saved'}
                  tone={claim.payment_destination_id ? 'success' : 'warning'}
                />
              </dd>
            </div>
          </dl>
        </section>

        {submissionError && (
          <section className="agreement-submission-error" role="alert">
            <h2>{submissionError.title}</h2>
            <p>{submissionError.message}</p>
          </section>
        )}

        <section className="agreement-confirmation" aria-labelledby="confirm-submit-heading">
          <header>
            <h2 id="confirm-submit-heading">Confirm and submit</h2>
            <p>Your claim can’t be edited after submission.</p>
          </header>
          <p className="agreement-display-copy">{agreement.display_copy}</p>

          {alreadyAccepted ? (
            <p className="agreement-confirmed-state" role="status">
              Agreement confirmed. Claim submission can be retried without recording a second acceptance.
            </p>
          ) : (
            <div className="agreement-confirmation-list">
              {agreement.confirmations.map((confirmation) => (
                <label className="agreement-confirmation-option" key={confirmation.key}>
                  <input
                    type="checkbox"
                    checked={confirmations[confirmation.key] === true}
                    onChange={(event) => {
                      setConfirmationState((current) => ({
                        scope: confirmationScope,
                        values: {
                          ...(current.scope === confirmationScope ? current.values : {}),
                          [confirmation.key]: event.target.checked,
                        },
                      }))
                    }}
                    disabled={busy}
                  />
                  <span>{confirmation.label}</span>
                </label>
              ))}
            </div>
          )}
        </section>

        <footer className="agreement-actions">
          <button
            className="secondary-button agreement-back"
            type="button"
            onClick={onReviewInformation}
            disabled={busy}
          >
            Back
          </button>
          <button
            className="primary-button agreement-submit"
            type="button"
            disabled={busy || !submissionProgress.available || (!alreadyAccepted && !requiredComplete)}
            onClick={() => onSubmit(confirmations)}
          >
            {submitting
              ? 'Submitting…'
              : alreadyAccepted
                ? 'Retry claim submission'
                : 'Submit claim'}
          </button>
        </footer>
      </article>
    </div>
  )
}
