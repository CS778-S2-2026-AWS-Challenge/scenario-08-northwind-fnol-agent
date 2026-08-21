import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ApiRequestError,
  confirmClaimFields,
  createClaim,
  createExternalClaim,
  getClaim,
  getClaimMessages,
  listClaims,
  requestId,
  requestHumanSupport,
  resumeClaimSession,
  submitClaimMessage,
  updateClaimField,
} from './api.js'
import './App.css'

const FIELD_LABELS = {
  'incident.description': 'What happened',
  'incident.location': 'Incident location',
  'loss.description': 'Damage or loss',
}

const INPUT_LABELS = {
  describe_incident: 'Incident description',
  provide_incident_location: 'Incident location',
  describe_loss: 'Damage or loss',
}

const HANDOFF_STATUS_LABELS = {
  queued: 'Queued',
  accepted: 'Accepted by Northwind support',
  in_progress: 'Support conversation in progress',
}

const FIELD_SOURCE_LABELS = {
  claimant: 'Provided by you',
  inference: 'Suggested from your description',
  image: 'Suggested from your image',
  document: 'Suggested from your document',
  policy: 'From your policy information',
  claim_history: 'From your previous claim information',
  staff: 'Provided by Northwind support',
}

function fieldLabel(fieldCode) {
  return FIELD_LABELS[fieldCode] || fieldCode.split('.').at(-1).replaceAll('_', ' ')
}

function fieldStatusLabel(status) {
  if (status === 'confirmed') return 'Confirmed'
  if (status === 'pending_generation') return 'Pending'
  return 'Check this'
}

function fieldSourceLabel(source) {
  return FIELD_SOURCE_LABELS[source] || 'Source recorded by Northwind'
}

function fieldValueText(field) {
  if (
    field.status === 'pending_generation'
    && (field.value === null || field.value === undefined || field.value === '')
  ) {
    return 'Expected later'
  }
  return String(field.value ?? '')
}

function messageText(message) {
  return message?.content?.type === 'text' ? message.content.text : ''
}

function mergeFields(current, changes) {
  return changes.reduce(
    (fields, change) => ({ ...fields, [change.field_code]: change.field }),
    current,
  )
}

function App() {
  const [draft, setDraft] = useState('')
  const [claim, setClaim] = useState(null)
  const [sessionId, setSessionId] = useState(null)
  const [messages, setMessages] = useState([])
  const [form, setForm] = useState({})
  const [nextStep, setNextStep] = useState(null)
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState('')
  const [editingField, setEditingField] = useState(null)
  const [editValue, setEditValue] = useState('')
  const [handoff, setHandoff] = useState(null)
  const [savedReports, setSavedReports] = useState(null)
  const [resumeContext, setResumeContext] = useState(null)
  const pendingSubmission = useRef(null)
  const pendingConfirmation = useRef(null)
  const pendingSupportRequest = useRef(null)
  const pendingClaimCreation = useRef(null)
  const latestRevision = useRef(0)

  const isBusy = [
    'starting',
    'sending',
    'confirming',
    'saving',
    'requesting-support',
    'refreshing',
    'creating-claim',
    'loading-reports',
    'resuming',
  ].includes(status)
  const proposedFields = useMemo(
    () => Object.entries(form).filter(([, field]) => field.status === 'proposed'),
    [form],
  )
  const confirmedFields = useMemo(
    () => Object.entries(form).filter(([, field]) => field.status === 'confirmed'),
    [form],
  )
  const hasStarted = claim !== null
  const inputLabel = INPUT_LABELS[nextStep?.status] || 'Add more information'

  useEffect(() => {
    if (claim?.revision) {
      latestRevision.current = Math.max(latestRevision.current, claim.revision)
    }
  }, [claim?.revision])

  async function refreshAfterConflict() {
    if (!claim) return
    const current = await getClaim(claim.claim_id)
    setClaim(current)
    setForm(current.form)
    setNextStep(current.customer_next_step)
  }

  const refreshClaimStatus = useCallback(async ({ silent = false } = {}) => {
    if (!claim) return
    if (!silent) {
      setError('')
      setStatus('refreshing')
    }
    try {
      const current = await getClaim(claim.claim_id)
      if (current.revision < latestRevision.current) return
      latestRevision.current = current.revision
      setClaim(current)
      setForm(current.form)
      setNextStep(current.customer_next_step)
      setHandoff(current.handoff || null)
      if (current.customer_next_step?.status === 'staff_update') setHandoff(null)
      if (sessionId) {
      const latest = await getClaimMessages(claim.claim_id, sessionId)
        setMessages(latest.items)
      }
      if (!silent) setStatus('idle')
    } catch (requestError) {
      if (!silent) {
        setError(requestError.message || 'We could not refresh your report. Please try again.')
        setStatus('error')
      }
    }
  }, [claim, sessionId])

  function showError(requestError) {
    if (requestError instanceof ApiRequestError && requestError.code === 'REVISION_CONFLICT') {
      setError('Your report changed while this page was open. We refreshed it; review the latest details and try again.')
      refreshAfterConflict().catch(() => {})
    } else {
      setError(requestError.message || 'We could not complete that request. Please try again.')
    }
    setStatus('error')
  }

  async function sendMessage(event) {
    event.preventDefault()
    const text = draft.trim()
    if (!text || isBusy || proposedFields.length > 0) return

    setError('')
    setStatus(hasStarted ? 'sending' : 'starting')
    try {
      if (pendingSubmission.current?.text !== text) {
        pendingSubmission.current = {
          text,
          claimKey: requestId('claim'),
          turnKey: requestId('turn'),
          clientMessageId: requestId('message'),
        }
      }
      const operation = pendingSubmission.current
      let activeClaim = claim
      let activeSessionId = sessionId
      if (!activeClaim) {
        const created = await createClaim({ idempotencyKey: operation.claimKey })
        activeClaim = created.claim
        activeSessionId = created.session.session_id
        setClaim(created.claim)
        setSessionId(activeSessionId)
        setForm(created.claim.form)
        setNextStep(created.claim.customer_next_step)
      }

      const turn = await submitClaimMessage({
        claimId: activeClaim.claim_id,
        sessionId: activeSessionId,
        revision: activeClaim.revision,
        text,
        idempotencyKey: operation.turnKey,
        clientMessageId: operation.clientMessageId,
      })
      setMessages((current) => [
        ...current,
        turn.claimant_message,
        ...(turn.agent_message ? [turn.agent_message] : []),
      ])
      setForm((current) => mergeFields(current, turn.form_changes))
      setClaim((current) => ({ ...current, revision: turn.claim_revision }))
      if (turn.decision) setNextStep(turn.decision.customer_next_step)
      if (turn.handoff) setHandoff(turn.handoff)
      setDraft('')
      pendingSubmission.current = null
      setStatus('idle')
    } catch (requestError) {
      showError(requestError)
    }
  }

  async function confirmProposedFields() {
    if (!claim || proposedFields.length === 0 || isBusy) return
    setError('')
    setStatus('confirming')
    try {
      const fieldCodes = proposedFields.map(([fieldCode]) => fieldCode)
      const fingerprint = `${claim.revision}:${fieldCodes.join(',')}`
      if (pendingConfirmation.current?.fingerprint !== fingerprint) {
        pendingConfirmation.current = {
          fingerprint,
          idempotencyKey: requestId('confirmation'),
        }
      }
      const response = await confirmClaimFields({
        claimId: claim.claim_id,
        revision: claim.revision,
        fieldCodes,
        idempotencyKey: pendingConfirmation.current.idempotencyKey,
      })
      setForm((current) => ({ ...current, ...response.confirmed_fields }))
      setClaim((current) => ({ ...current, revision: response.revision }))
      setNextStep(response.customer_next_step)
      pendingConfirmation.current = null
      setStatus('idle')
    } catch (requestError) {
      showError(requestError)
    }
  }

  function beginEdit(fieldCode, value) {
    setEditingField(fieldCode)
    setEditValue(String(value ?? ''))
    setError('')
  }

  async function saveFieldCorrection(fieldCode, field) {
    const value = editValue.trim()
    if (!claim || !value || isBusy) return
    if (value === String(field.value)) {
      setEditingField(null)
      return
    }

    setError('')
    setStatus('saving')
    try {
      const update = await updateClaimField({
        claimId: claim.claim_id,
        revision: claim.revision,
        fieldCode,
        value,
        status: field.status === 'proposed' ? 'proposed' : 'confirmed',
        reason: 'The claimant corrected this detail in the review form.',
      })
      let revision = update.revision
      let updatedForm = { ...form, ...update.updated_fields }
      let updatedNextStep = update.customer_next_step

      if (field.status === 'proposed') {
        const confirmation = await confirmClaimFields({
          claimId: claim.claim_id,
          revision,
          fieldCodes: [fieldCode],
        })
        revision = confirmation.revision
        updatedForm = { ...updatedForm, ...confirmation.confirmed_fields }
        updatedNextStep = confirmation.customer_next_step
      }

      setForm(updatedForm)
      setClaim((current) => ({ ...current, revision }))
      setNextStep(updatedNextStep)
      setEditingField(null)
      setStatus('idle')
    } catch (requestError) {
      showError(requestError)
    }
  }

  async function requestSupport() {
    if (!claim || isBusy || handoff) return
    setError('')
    setStatus('requesting-support')
    try {
      if (!pendingSupportRequest.current) {
        pendingSupportRequest.current = { idempotencyKey: requestId('support') }
      }
      const response = await requestHumanSupport({
        claimId: claim.claim_id,
        revision: claim.revision,
        idempotencyKey: pendingSupportRequest.current.idempotencyKey,
      })
      setClaim((current) => ({ ...current, revision: response.revision }))
      setNextStep(response.customer_next_step)
      setHandoff(response.handoff)
      pendingSupportRequest.current = null
      setStatus('idle')
    } catch (requestError) {
      showError(requestError)
    }
  }

  async function createConfirmedClaim() {
    if (!claim || isBusy || nextStep?.status !== 'ready_to_create') return
    setError('')
    setStatus('creating-claim')
    try {
      if (!pendingClaimCreation.current) {
        pendingClaimCreation.current = { idempotencyKey: requestId('claim-creation') }
      }
      const response = await createExternalClaim({
        claimId: claim.claim_id,
        revision: claim.revision,
        idempotencyKey: pendingClaimCreation.current.idempotencyKey,
      })
      setClaim((current) => ({
        ...current,
        revision: response.revision,
        external_claim: response.external_claim,
      }))
      setNextStep(response.customer_next_step)
      pendingClaimCreation.current = null
      setStatus('idle')
    } catch (requestError) {
      showError(requestError)
    }
  }

  async function loadSavedReports() {
    if (isBusy) return
    setError('')
    setStatus('loading-reports')
    try {
      const reportsByClaimId = new Map()
      const seenCursors = new Set()
      let cursor

      do {
        const response = await listClaims({ cursor })
        for (const item of response.items) {
          if (item.can_resume && !reportsByClaimId.has(item.claim_id)) {
            reportsByClaimId.set(item.claim_id, item)
          }
        }

        const nextCursor = response.page?.next_cursor || null
        if (nextCursor && seenCursors.has(nextCursor)) {
          throw new ApiRequestError(
            'We could not finish loading your saved reports. Please try again.',
            { code: 'INVALID_PAGINATION' },
          )
        }
        if (nextCursor) seenCursors.add(nextCursor)
        cursor = nextCursor
      } while (cursor)

      setSavedReports([...reportsByClaimId.values()])
      setStatus('idle')
    } catch (requestError) {
      showError(requestError)
    }
  }

  async function resumeSavedReport(claimId) {
    if (isBusy) return
    setError('')
    setStatus('resuming')
    try {
      const session = await resumeClaimSession({ claimId })
      const current = await getClaim(claimId)
      const conversation = await getClaimMessages(claimId, session.session_id)
      latestRevision.current = current.revision
      setClaim(current)
      setSessionId(session.session_id)
      setMessages(conversation.items)
      setForm(current.form)
      setNextStep(current.customer_next_step)
      setHandoff(current.handoff || null)
      setResumeContext(session.resume)
      setSavedReports(null)
      setStatus('idle')
    } catch (requestError) {
      showError(requestError)
    }
  }

  return (
    <div className="customer-app">
      <header className="product-header">
        <a className="brand" href="/" aria-label="Northwind home">
          <span className="brand-mark">N</span>
          <span>Northwind</span>
        </a>
        {hasStarted && (
          <div className="header-actions">
            <span className="draft-label">Draft report</span>
            <button
              className="support-button"
              type="button"
              onClick={requestSupport}
              disabled={isBusy || Boolean(handoff)}
            >
              {status === 'requesting-support' ? 'Requesting support...' : 'Request human support'}
            </button>
          </div>
        )}
      </header>

      {!hasStarted ? (
        <main className="entry-page">
          <section className="entry-main">
            <div className="entry-content">
              <p className="eyebrow">Start a new claim</p>
              <h1>Tell us what happened in your own words</h1>
              <p className="entry-intro">
                You do not need to use insurance terms. Start with the details you know now.
              </p>
              <MessageComposer
                draft={draft}
                setDraft={setDraft}
                onSubmit={sendMessage}
                inputLabel="Incident description"
                busy={isBusy}
                buttonLabel={status === 'starting' ? 'Starting report...' : 'Continue claim'}
                error={error}
              />
              <div className="resume-entry">
                <button
                  className="secondary-button"
                  type="button"
                  onClick={loadSavedReports}
                  disabled={isBusy}
                >
                  {status === 'loading-reports' ? 'Loading reports...' : 'Resume a saved report'}
                </button>
                {savedReports !== null && (
                  <section className="saved-reports" aria-labelledby="saved-reports-title">
                    <h2 id="saved-reports-title">Saved reports</h2>
                    {savedReports.length === 0 ? (
                      <p>No saved reports are available to resume.</p>
                    ) : (
                      <ul>
                        {savedReports.map((report) => (
                          <li key={report.claim_id}>
                            <div>
                              <strong>{report.incident_type || 'Incident report'}</strong>
                              <span>{report.customer_next_step.summary}</span>
                            </div>
                            <button
                              className="secondary-button"
                              type="button"
                              onClick={() => resumeSavedReport(report.claim_id)}
                              disabled={isBusy}
                            >
                              {status === 'resuming' ? 'Resuming...' : 'Resume report'}
                            </button>
                          </li>
                        ))}
                      </ul>
                    )}
                  </section>
                )}
              </div>
            </div>
          </section>
          <HelpfulDetails />
        </main>
      ) : (
        <main className="intake-page">
          <section className="conversation-panel" aria-labelledby="conversation-title">
            <div className="conversation-heading">
              <p className="eyebrow">Your report</p>
              <h1 id="conversation-title">Let&apos;s build the details together</h1>
              {handoff?.status !== 'in_progress' && <p>{nextStep?.summary}</p>}
            </div>

            <div className="message-list" aria-live="polite">
              {messages.map((message) => (
                <article className={`message message-${message.actor}`} key={message.message_id}>
                  <p className="message-author">{message.actor === 'claimant' ? 'You' : 'Northwind'}</p>
                  <p>{messageText(message)}</p>
                </article>
              ))}
            </div>

            {resumeContext && (
              <section className="resume-summary" aria-labelledby="resume-summary-title">
                <p className="transfer-label">Report resumed</p>
                <h2 id="resume-summary-title">Continue where you left off</h2>
                {resumeContext.summary && <p>{resumeContext.summary}</p>}
                {resumeContext.pending_items.length > 0 && (
                  <dl>
                    <div>
                      <dt>Pending</dt>
                      <dd>{resumeContext.pending_items.join(', ')}</dd>
                    </div>
                  </dl>
                )}
                {resumeContext.prior_commitments.length > 0 && (
                  <p>{resumeContext.prior_commitments.join(' ')}</p>
                )}
              </section>
            )}

            {handoff && ['queued', 'accepted'].includes(handoff.status) && (
              <section
                className={`transfer-state ${handoff.priority === 'urgent' ? 'is-urgent' : ''}`}
                aria-live="assertive"
                aria-labelledby="transfer-title"
              >
                <p className="transfer-label">
                  {handoff.priority === 'urgent' ? 'Urgent support' : 'Human support'}
                </p>
                <h2 id="transfer-title">
                  {handoff.priority === 'urgent'
                    ? 'Normal intake has paused'
                    : handoff.status === 'queued'
                      ? 'Your support request is queued'
                      : 'Northwind support is handling your request'}
                </h2>
                <p className="handoff-status">Status: {HANDOFF_STATUS_LABELS[handoff.status] || handoff.status}</p>
                <p>{handoff.summary}</p>
                <dl>
                  <div>
                    <dt>Next owner</dt>
                    <dd>Northwind support</dd>
                  </div>
                  <div>
                    <dt>Your report</dt>
                    <dd>Saved with the details already provided</dd>
                  </div>
                </dl>
                <p>Your message will be saved for Northwind support. Start with @agent when you need an Agent response.</p>
                <button
                  className="secondary-button refresh-button"
                  type="button"
                  onClick={() => refreshClaimStatus()}
                  disabled={isBusy}
                >
                  {status === 'refreshing' ? 'Refreshing...' : 'Refresh status'}
                </button>
              </section>
            )}

            {handoff?.status === 'in_progress' && (
              <div className="system-notice" role="status">
                A Northwind staff member is now assisting you.
              </div>
            )}

            {!handoff && nextStep?.status === 'staff_update' && (
              <section className="staff-update" role="status" aria-labelledby="staff-update-title">
                <p className="transfer-label">Northwind update</p>
                <h2 id="staff-update-title">Your support request has been reviewed</h2>
                <p>{nextStep.summary}</p>
              </section>
            )}

            {claim.external_claim && (
              <section className="claim-created" role="status" aria-labelledby="claim-created-title">
                <p className="transfer-label">Claim created</p>
                <h2 id="claim-created-title">{claim.external_claim.claim_number}</h2>
                <dl>
                  <div><dt>Route</dt><dd>{claim.external_claim.route}</dd></div>
                  <div><dt>Next step</dt><dd>{claim.external_claim.next_step}</dd></div>
                  <div>
                    <dt>Expected by</dt>
                    <dd>{new Date(claim.external_claim.expected_by).toLocaleString()}</dd>
                  </div>
                </dl>
              </section>
            )}

            <MessageComposer
              draft={draft}
              setDraft={setDraft}
              onSubmit={sendMessage}
              inputLabel={inputLabel}
              busy={isBusy}
              disabled={proposedFields.length > 0 && !handoff}
              disabledNote={
                handoff
                  ? 'Your message will be saved for Northwind support. Start with @agent when you need an Agent response.'
                  : 'Confirm or correct the details before continuing.'
              }
              buttonLabel={status === 'sending' ? 'Sending...' : 'Send'}
              error={error}
            />
          </section>

          <aside className="claim-panel" aria-labelledby="claim-details-title">
            <div className="claim-panel-heading">
              <div>
                <p className="eyebrow">Structured report</p>
                <h2 id="claim-details-title">Claim details</h2>
              </div>
              <span className="revision-label">Revision {claim.revision}</span>
            </div>

            {Object.keys(form).length === 0 ? (
              <p className="empty-details">Details from your conversation will appear here.</p>
            ) : (
              <div className="field-list">
                {Object.entries(form).map(([fieldCode, field]) => (
                  <div className="claim-field" key={fieldCode}>
                    <div className="field-heading">
                      <span>{fieldLabel(fieldCode)}</span>
                      <span className={`field-status status-${field.status}`}>
                        {fieldStatusLabel(field.status)}
                      </span>
                    </div>
                    {editingField === fieldCode ? (
                      <div className="field-editor">
                        <textarea
                          aria-label={`Correct ${fieldLabel(fieldCode)}`}
                          value={editValue}
                          onChange={(event) => setEditValue(event.target.value)}
                          rows="3"
                        />
                        <div className="field-actions">
                          <button
                            className="secondary-button"
                            type="button"
                            onClick={() => setEditingField(null)}
                            disabled={isBusy}
                          >
                            Cancel
                          </button>
                          <button
                            className="primary-button compact-button"
                            type="button"
                            onClick={() => saveFieldCorrection(fieldCode, field)}
                            disabled={!editValue.trim() || isBusy}
                          >
                            {status === 'saving' ? 'Saving...' : 'Save correction'}
                          </button>
                        </div>
                      </div>
                    ) : (
                      <>
                        <p className="field-value">{fieldValueText(field)}</p>
                        <p className="field-source">{fieldSourceLabel(field.source)}</p>
                        <button
                          className="text-button"
                          type="button"
                          onClick={() => beginEdit(fieldCode, field.value)}
                          disabled={isBusy}
                        >
                          Edit
                        </button>
                      </>
                    )}
                  </div>
                ))}
              </div>
            )}

            {proposedFields.length > 0 && editingField === null && (
              <div className="confirmation-bar">
                <p>Check the highlighted details before continuing.</p>
                <button
                  className="primary-button"
                  type="button"
                  onClick={confirmProposedFields}
                  disabled={isBusy}
                >
                  {status === 'confirming' ? 'Confirming...' : 'Confirm details'}
                </button>
              </div>
            )}

            {confirmedFields.length > 0 && proposedFields.length === 0 && (
              <div className="next-step" role="status">
                <span>Next</span>
                <p>{nextStep?.summary}</p>
                {nextStep?.status === 'ready_to_create' && !claim.external_claim && (
                  <button
                    className="primary-button"
                    type="button"
                    onClick={createConfirmedClaim}
                    disabled={isBusy}
                  >
                    {status === 'creating-claim' ? 'Creating claim...' : 'Create claim'}
                  </button>
                )}
              </div>
            )}
          </aside>
        </main>
      )}
    </div>
  )
}

function MessageComposer({
  draft,
  setDraft,
  onSubmit,
  inputLabel,
  busy,
  disabled = false,
  disabledNote = 'Confirm or correct the details before continuing.',
  buttonLabel,
  error,
}) {
  return (
    <form className="report-box" onSubmit={onSubmit}>
      <label htmlFor="incident-input">{inputLabel}</label>
      <textarea
        id="incident-input"
        className="report-text"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        placeholder="Write the details you know..."
        rows="4"
        disabled={busy || disabled}
      />
      {disabled && <p className="composer-note">{disabledNote}</p>}
      {error && (
        <div className="backend-status is-error" role="alert">
          <span className="status-dot" />
          <span>{error}</span>
        </div>
      )}
      <div className="report-actions">
        <button
          className="primary-button"
          type="submit"
          disabled={!draft.trim() || busy || disabled}
        >
          {buttonLabel}
        </button>
      </div>
    </form>
  )
}

function HelpfulDetails() {
  return (
    <aside className="entry-side" aria-labelledby="helpful-details-title">
      <div className="side-content">
        <p className="side-label">When available</p>
        <h2 id="helpful-details-title">Helpful details to include</h2>
        <ul className="detail-list">
          <li>When and where the incident happened</li>
          <li>Who or what was involved</li>
          <li>Any damage, injuries, or immediate safety concerns</li>
        </ul>
      </div>
    </aside>
  )
}

export default App
