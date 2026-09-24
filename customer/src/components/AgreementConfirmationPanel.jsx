import { useState } from 'react'

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

export default function AgreementConfirmationPanel({
  claim,
  busy,
  status,
  onSubmit,
  onReviewInformation,
  onReturnToConversation,
}) {
  const externalClaim = claim?.external_claim
  const agreement = claim?.submission_agreement
  const alreadyAccepted = claim?.primary_action?.action_code === 'claimant.create_claim'
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
    return (
      <section className="claim-history-state" aria-labelledby="claim-submitted-heading">
        <h2 id="claim-submitted-heading">Claim submitted</h2>
        <dl>
          <div>
            <dt>Claim reference</dt>
            <dd>{readable(externalClaim.claim_number)}</dd>
          </div>
          <div>
            <dt>Creation status</dt>
            <dd>{readable(externalClaim.creation_status)}</dd>
          </div>
          <div>
            <dt>Next step</dt>
            <dd>{readable(externalClaim.next_step)}</dd>
          </div>
          <div>
            <dt>Expected by</dt>
            <dd>{readable(externalClaim.expected_by)}</dd>
          </div>
        </dl>
        <button
          className="primary-button"
          type="button"
          onClick={onReturnToConversation}
        >
          Back to conversation
        </button>
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
  const submitting = status === 'creating-claim'

  return (
    <section className="claim-history-state" aria-labelledby="agreement-heading">
      <h2 id="agreement-heading">Final claim confirmation</h2>

      <dl>
        <div>
          <dt>Claim type</dt>
          <dd>{readable(claim.incident_type)}</dd>
        </div>
        <div>
          <dt>Incident date</dt>
          <dd>{readable(fieldValue(claim, 'incident.occurred_at'))}</dd>
        </div>
        <div>
          <dt>Insured item or property</dt>
          <dd>{readable(insuredSubject)}</dd>
        </div>
        <div>
          <dt>Evidence</dt>
          <dd>{readable(claim.evidence_summary?.state || claim.evidence_summary?.status)}</dd>
        </div>
        <div>
          <dt>Preferred contact</dt>
          <dd>{readable(contactPreference)}</dd>
        </div>
        <div>
          <dt>Payout details</dt>
          <dd>{claim.payment_destination_id ? 'Saved' : 'Not saved'}</dd>
        </div>
      </dl>

      <button
        className="secondary-button"
        type="button"
        onClick={onReviewInformation}
        disabled={busy}
      >
        Review information
      </button>

      <hr />

      <h3>Agreement</h3>
      <p>{agreement.display_copy}</p>

      {alreadyAccepted ? (
        <p role="status">
          Agreement confirmed. Claim submission can be retried without recording a second acceptance.
        </p>
      ) : (
        agreement.confirmations.map((confirmation) => (
          <label key={confirmation.key}>
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
            {' '}
            {confirmation.label}
          </label>
        ))
      )}

      <div>
        <button
          className="primary-button"
          type="button"
          disabled={busy || (!alreadyAccepted && !requiredComplete)}
          onClick={() => onSubmit(confirmations)}
        >
          {submitting
            ? 'Submitting…'
            : alreadyAccepted
              ? 'Retry claim submission'
              : 'Submit claim'}
        </button>
      </div>
    </section>
  )
}
