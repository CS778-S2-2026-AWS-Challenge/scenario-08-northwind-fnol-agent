import { BadgeCheck, BadgeX } from 'lucide-react'
import { useEffect, useId, useRef, useState } from 'react'
import { failureReference } from '../failure.js'
import { formatDateTime, words } from '../format.js'
import { translate as t } from '../i18n.js'
import ConfirmDialog from './ConfirmDialog.jsx'

const MAX_EXPLANATION_LENGTH = 1000

export function ClaimDecisionControls({ action, onDecision }) {
  const [mode, setMode] = useState(null)
  const [approvalExplanation, setApprovalExplanation] = useState('')
  const [rejectionExplanation, setRejectionExplanation] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [retryReady, setRetryReady] = useState(false)
  const [retryBlocked, setRetryBlocked] = useState(false)
  const approveTriggerRef = useRef(null)
  const rejectTriggerRef = useRef(null)
  const attemptRef = useRef(null)
  const errorId = useId()
  const hintId = useId()
  const eligible = action?.action_code === 'claim.record_decision'
    && action.target_type === 'claim'
    && action.target_ref
    && action.availability === 'confirmation_required'
    && Number.isInteger(action.based_on_revision)

  useEffect(() => {
    if (!mode || !attemptRef.current) return
    if (
      action?.target_ref !== attemptRef.current.claimId
      || action?.based_on_revision !== attemptRef.current.revision
      || action?.availability !== 'confirmation_required'
    ) {
      setMode(null)
      setApprovalExplanation('')
      setRejectionExplanation('')
      setBusy(false)
      setError('')
      setRetryReady(false)
      setRetryBlocked(false)
      attemptRef.current = null
    }
  }, [action?.availability, action?.based_on_revision, action?.target_ref, mode])

  if (!eligible) return null

  function begin(decision) {
    setMode(decision)
    setApprovalExplanation('')
    setRejectionExplanation('')
    setBusy(false)
    setError('')
    setRetryReady(false)
    setRetryBlocked(false)
    attemptRef.current = {
      claimId: action.target_ref,
      decision,
      key: crypto.randomUUID(),
      payload: null,
      revision: action.based_on_revision,
      sent: false,
    }
  }

  function reset(force = false) {
    if (busy && !force) return
    setMode(null)
    setApprovalExplanation('')
    setRejectionExplanation('')
    setError('')
    setRetryReady(false)
    setRetryBlocked(false)
    attemptRef.current = null
  }

  function changeExplanation(setter, value) {
    if (attemptRef.current?.sent) {
      attemptRef.current = {
        ...attemptRef.current,
        key: crypto.randomUUID(),
        payload: null,
        sent: false,
      }
      setRetryReady(false)
      setRetryBlocked(false)
    }
    setter(value)
    setError('')
  }

  async function submit() {
    if (busy || retryBlocked || !attemptRef.current) return
    const attempt = attemptRef.current
    if (
      attempt.claimId !== action.target_ref
      || attempt.revision !== action.based_on_revision
    ) {
      reset()
      return
    }

    let payload = attempt.payload
    if (!retryReady) {
      const explanation = (mode === 'approved'
        ? approvalExplanation
        : rejectionExplanation).trim()
      if (mode === 'rejected' && !explanation) {
        setError(t('Enter a public rejection explanation.'))
        return
      }
      payload = {
        decision: mode,
        ...(explanation ? { claimant_explanation: explanation } : {}),
      }
      attempt.payload = payload
    }

    attempt.sent = true
    setBusy(true)
    setError('')
    try {
      await onDecision(
        action,
        payload,
        attempt.key,
        attempt.claimId,
      )
      if (attemptRef.current !== attempt) return
      setBusy(false)
      reset(true)
    } catch (nextError) {
      if (attemptRef.current !== attempt) return
      setBusy(false)
      if (nextError?.decisionRequiresNewConfirmation) {
        reset(true)
        return
      }
      setRetryReady(Boolean(nextError?.decisionRetryAllowed))
      setRetryBlocked(Boolean(nextError?.decisionRetryBlocked))
      setError(decisionErrorMessage(nextError))
    }
  }

  const rejecting = mode === 'rejected'
  const inputLocked = busy || retryReady || retryBlocked
  const explanation = rejecting ? rejectionExplanation : approvalExplanation
  const setExplanation = rejecting ? setRejectionExplanation : setApprovalExplanation
  const returnFocusRef = rejecting ? rejectTriggerRef : approveTriggerRef

  return (
    <div className="claim-decision-actions">
      <button ref={approveTriggerRef} className="button button--primary" type="button" disabled={busy} onClick={() => begin('approved')}>
        {t('Approve Claim')}
      </button>
      <button ref={rejectTriggerRef} className="button button--secondary" type="button" disabled={busy} onClick={() => begin('rejected')}>
        {t('Reject Claim')}
      </button>
      <ConfirmDialog
        open={Boolean(mode)}
        title={t(rejecting ? 'Reject this Claim?' : 'Approve this Claim?')}
        description={action.confirmation?.message || t('This final Claim decision cannot be changed in this version.')}
        cancelLabel={t('Cancel')}
        confirmLabel={t(retryReady
          ? rejecting ? 'Retry same rejection' : 'Retry same approval'
          : rejecting ? 'Reject Claim' : 'Approve Claim')}
        busyLabel={t(rejecting ? 'Rejecting...' : 'Approving...')}
        busy={busy}
        confirmDisabled={retryBlocked}
        danger={rejecting}
        dialogClassName="claim-decision-dialog"
        returnFocusRef={returnFocusRef}
        onCancel={reset}
        onConfirm={submit}
      >
        <label htmlFor={`${hintId}-input`}>
          <span id={`${hintId}-label`}>{t(rejecting ? 'Public rejection explanation' : 'Public approval explanation (optional)')}</span>
          <textarea
            id={`${hintId}-input`}
            value={explanation}
            maxLength={MAX_EXPLANATION_LENGTH}
            rows={8}
            disabled={inputLocked}
            required={rejecting}
            aria-labelledby={`${hintId}-label`}
            aria-invalid={Boolean(error) && !retryReady && !retryBlocked}
            aria-describedby={`${hintId}${error ? ` ${errorId}` : ''}`}
            onChange={(event) => changeExplanation(setExplanation, event.target.value)}
          />
          <small id={hintId}>{t('This text may be shown to the claimant.')}</small>
        </label>
        {retryReady && <p className="claim-decision-retry" role="status">{t('The latest Claim is still eligible. Retrying will reuse the same request key and exact decision.')}</p>}
        {error && <p id={errorId} className="form-error" role="alert">{error}</p>}
      </ConfirmDialog>
    </div>
  )
}

export function ClaimDecisionSummary({ decision }) {
  if (!decision) return null
  const approved = decision.decision === 'approved'
  const Icon = approved ? BadgeCheck : BadgeX
  return (
    <section className={`claim-decision-summary claim-decision-summary--${approved ? 'approved' : 'rejected'}`} aria-labelledby="claim-decision-summary-title">
      <Icon aria-hidden="true" />
      <div>
        <p className="eyebrow">{t('Recorded Claim decision')}</p>
        <h2 id="claim-decision-summary-title">{t(approved ? 'Claim approved' : 'Claim rejected')}</h2>
        <p>{decision.claimant_explanation}</p>
        <small>{t('Recorded {date}', { date: formatDateTime(decision.decided_at) })} · {words(decision.decision)}</small>
      </div>
    </section>
  )
}

function decisionErrorMessage(error) {
  const reference = failureReference(error)
  let message
  if (error?.code === 'VALIDATION_ERROR') message = error.message || t('The public explanation was not accepted. Review it and try again.')
  else if (error?.code === 'IDEMPOTENCY_CONFLICT') message = t('This request key no longer matches the original decision. Cancel and start a new approval or rejection after reviewing the current Claim.')
  else if (error?.decisionRetryAllowed) message = t('The decision was not found after refreshing the Claim. You may retry this exact operation with the same request key.')
  else if (error?.decisionRetryBlocked) message = t('The decision outcome is unclear and the latest Claim could not be loaded. Cancel and refresh the Claim before taking another action.')
  else message = error?.message || t('The decision could not be recorded. Review the current Claim before trying again.')
  return [message, reference].filter(Boolean).join(' ')
}
