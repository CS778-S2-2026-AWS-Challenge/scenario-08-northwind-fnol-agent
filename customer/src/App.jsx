import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  ApiRequestError,
  confirmClaimFields,
  createClaim,
  createExternalClaim,
  grantAssessorConsent,
  getAuthenticatedAccount,
  getClaim,
  getClaimMessages,
  hasClaimantAccessToken,
  hasStartupClaimantAccessToken,
  listClaims,
  loginClaimant,
  logoutClaimant,
  requestId,
  requestHumanSupport,
  requestAssessorRouting,
  resumeClaimSession,
  submitClaimMessage,
  setClaimantAccessToken,
  updateAccountPreferences,
  updateAccountProfile,
  updateClaimField,
} from './api.js'
import './App.css'
import GuidedMotorClaim from './GuidedMotorClaim.jsx'
import northwindValley from './assets/northwind-valley.jpg'

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

const CLAIM_MATERIALS = {
  motor: [
    ['Policy or client number', 'Helpful for finding your cover quickly.'],
    ['Incident details', 'The date, time, location and a short account of what happened.'],
    ['Vehicle and driver details', 'Registration plates and contact details, if available.'],
    ['Photos or video', 'Damage and the wider scene, when it is safe to take them.'],
  ],
  home: [
    ['Policy or client number', 'Helpful for finding your cover quickly.'],
    ['Incident details', 'When it happened, what caused it and the affected areas.'],
    ['Photos or video', 'Clear views of the damage and likely source, when safe.'],
    ['Emergency work records', 'Invoices or reports for urgent work already completed.'],
  ],
  contents: [
    ['Policy or client number', 'Helpful for finding your cover quickly.'],
    ['Affected items', 'The brand, model, age and what happened to each item.'],
    ['Proof of ownership', 'Receipts, photos or account statements, if available.'],
    ['Photos of damage', 'Clear images of affected items and the surrounding area.'],
  ],
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

function conversationTitle(form, incidentType) {
  const description = form['incident.description']?.value
  if (description) {
    const text = String(description).trim()
    return `Incident: ${text.length > 42 ? `${text.slice(0, 42).trim()}…` : text}`
  }
  return incidentType ? `${incidentType} claim` : 'New incident report'
}

function savedConversationTitle(report) {
  const type = report.incident_type
    ? `${report.incident_type[0].toUpperCase()}${report.incident_type.slice(1)} incident`
    : 'Incident report'
  const updatedAt = new Date(report.updated_at)
  if (Number.isNaN(updatedAt.getTime())) return type
  const date = new Intl.DateTimeFormat('en-NZ', {
    day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit',
  }).format(updatedAt)
  return `${type} · ${date}`
}

function shortClaimReference(claimId) {
  return `Report ${String(claimId).split('_').pop().slice(-6).toUpperCase()}`
}

function mergeFields(current, changes) {
  return changes.reduce(
    (fields, change) => ({ ...fields, [change.field_code]: change.field }),
    current,
  )
}

function App() {
  const [page, setPage] = useState('home')
  const [account, setAccount] = useState(null)
  const [authStatus, setAuthStatus] = useState('idle')
  const [authError, setAuthError] = useState('')
  const [authReturnToClaim, setAuthReturnToClaim] = useState(false)
  const [claimType, setClaimType] = useState('motor')
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
  const [externalServiceInteraction, setExternalServiceInteraction] = useState({
    claimId: null,
    consentChecked: false,
    error: null,
  })
  const [failedMessage, setFailedMessage] = useState(null)
  const [pendingMessage, setPendingMessage] = useState(null)
  const pendingSubmission = useRef(null)
  const pendingConfirmation = useRef(null)
  const pendingSupportRequest = useRef(null)
  const pendingClaimCreation = useRef(null)
  const pendingExternalService = useRef(null)
  const latestRevision = useRef(0)
  const historyAutoLoadAttempted = useRef(false)
  const messageListRef = useRef(null)
  const followLatestMessage = useRef(true)

  const navigateTo = useCallback((nextPage, { replace = false } = {}) => {
    const method = replace ? 'replaceState' : 'pushState'
    window.history[method]({ northwindPage: nextPage }, '', window.location.href)
    setPage(nextPage)
  }, [])

  useEffect(() => {
    if (!window.history.state?.northwindPage) {
      window.history.replaceState({ northwindPage: 'home' }, '', window.location.href)
    }
    const handlePopState = (event) => {
      const targetPage = event.state?.northwindPage || 'home'
      if (targetPage === 'home') resetActiveReportState()
      setPage(targetPage)
    }
    window.addEventListener('popstate', handlePopState)
    return () => window.removeEventListener('popstate', handlePopState)
  }, [])

  function resetActiveReportState() {
    setDraft('')
    setClaim(null)
    setSessionId(null)
    setMessages([])
    setForm({})
    setNextStep(null)
    setHandoff(null)
    setResumeContext(null)
    setError('')
    setFailedMessage(null)
    setPendingMessage(null)
    setStatus('idle')
    latestRevision.current = 0
  }

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
    'granting-service-consent',
    'requesting-assessor',
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
  const serviceConsentChecked = externalServiceInteraction.claimId === claim?.claim_id
    && externalServiceInteraction.consentChecked
  const serviceError = externalServiceInteraction.claimId === claim?.claim_id
    ? externalServiceInteraction.error
    : null

  function setServiceConsentChecked(consentChecked) {
    setExternalServiceInteraction((current) => ({
      claimId: claim?.claim_id || null,
      consentChecked,
      error: current.claimId === claim?.claim_id ? current.error : null,
    }))
  }

  function setServiceError(serviceErrorValue) {
    setExternalServiceInteraction((current) => ({
      claimId: claim?.claim_id || null,
      consentChecked: current.claimId === claim?.claim_id ? current.consentChecked : false,
      error: serviceErrorValue,
    }))
  }

  const claimTypePrompts = {
    motor: 'For example: Another car reversed into mine while it was parked.',
    home: 'For example: A pipe burst overnight and damaged the kitchen floor.',
    contents: 'For example: My laptop and camera were stolen from my apartment.',
  }

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

  useEffect(() => {
    if (!claim || !sessionId) return undefined
    const refreshVisibleConversation = () => {
      if (document.visibilityState === 'visible') {
        refreshClaimStatus({ silent: true })
      }
    }
    window.addEventListener('focus', refreshVisibleConversation)
    document.addEventListener('visibilitychange', refreshVisibleConversation)
    return () => {
      window.removeEventListener('focus', refreshVisibleConversation)
      document.removeEventListener('visibilitychange', refreshVisibleConversation)
    }
  }, [claim, sessionId, refreshClaimStatus])

  useEffect(() => {
    if (!hasStarted || !followLatestMessage.current) return
    const list = messageListRef.current
    if (!list) return
    list.scrollTo?.({ top: list.scrollHeight, behavior: 'smooth' })
  }, [hasStarted, messages.length, pendingMessage, failedMessage])

  function trackConversationScroll(event) {
    const list = event.currentTarget
    followLatestMessage.current = list.scrollHeight - list.scrollTop - list.clientHeight < 96
  }

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
    event?.preventDefault()
    const text = draft.trim()
    if (!text || isBusy) return

    if (!hasClaimantAccessToken()) {
      setAuthReturnToClaim(true)
      setAuthError('Sign in to securely save your report and conversation.')
      navigateTo('login')
      return
    }

    followLatestMessage.current = true
    setError('')
    setFailedMessage(null)
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
      setPendingMessage({ text, audience: 'Northwind claim team' })
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
      setPendingMessage(null)
      setFailedMessage(null)
      setStatus('idle')
      if (account) {
        setSavedReports(null)
        historyAutoLoadAttempted.current = false
      }
      if (!hasStarted) navigateTo('conversation')
    } catch (requestError) {
      setPendingMessage(null)
      const knownRejection = requestError instanceof ApiRequestError
        && requestError.status >= 400
        && requestError.status < 500
      setFailedMessage({
        text,
        sender: 'You',
        audience: 'Northwind claim team',
        delivery: knownRejection ? 'Rejected before delivery' : 'Delivery outcome unknown',
        retry: knownRejection ? 'Correct the issue and retry' : 'Retry to confirm delivery safely',
      })
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
        external_service_action: response.external_service_action,
      }))
      setNextStep(response.customer_next_step)
      pendingClaimCreation.current = null
      setStatus('idle')
    } catch (requestError) {
      showError(requestError)
    }
  }

  async function requestVehicleAssessment() {
    const action = claim?.external_service_action
    if (!claim || !action?.can_request || isBusy) return
    if (action.status === 'consent_required' && !serviceConsentChecked) return

    setServiceError(null)
    if (pendingExternalService.current?.claimId !== claim.claim_id) {
      pendingExternalService.current = {
        claimId: claim.claim_id,
        consentKey: requestId('assessor-consent'),
        routeKey: requestId('assessor-routing'),
      }
    }
    const operation = pendingExternalService.current
    let revision = claim.revision
    try {
      if (action.status === 'consent_required') {
        setStatus('granting-service-consent')
        const consent = await grantAssessorConsent({
          claimId: claim.claim_id,
          revision,
          idempotencyKey: operation.consentKey,
        })
        revision = consent.revision
        latestRevision.current = revision
        setClaim((current) => ({
          ...current,
          revision,
          external_service_action: consent.action,
        }))
        setNextStep(consent.customer_next_step)
      }

      setStatus('requesting-assessor')
      const routed = await requestAssessorRouting({
        claimId: claim.claim_id,
        revision,
        idempotencyKey: operation.routeKey,
      })
      latestRevision.current = routed.revision
      setClaim((current) => ({
        ...current,
        revision: routed.revision,
        external_service_action: routed.action,
      }))
      setNextStep(routed.customer_next_step)
      pendingExternalService.current = null
      setServiceConsentChecked(false)
      setStatus('idle')
    } catch (requestError) {
      try {
        const current = await getClaim(claim.claim_id)
        const currentAction = current.external_service_action
        latestRevision.current = current.revision
        setClaim(current)
        setForm(current.form)
        setNextStep(current.customer_next_step)
        setHandoff(current.handoff || null)
        if (['assigned', 'queued'].includes(currentAction?.status)) {
          pendingExternalService.current = null
          setServiceConsentChecked(false)
          setServiceError(null)
          setStatus('idle')
          return
        }
      } catch {
        // Keep the original request error when authoritative state cannot be restored.
      }
      setServiceError({
        message: requestError.message || 'We could not send the assessment request.',
        retryable: Boolean(requestError.retryable),
      })
      if (requestError instanceof ApiRequestError && requestError.code === 'REVISION_CONFLICT') {
        refreshAfterConflict().catch(() => {})
      }
      setStatus('idle')
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

  useEffect(() => {
    if (
      page !== 'home'
      || (!account && !hasStartupClaimantAccessToken())
      || savedReports !== null
      || historyAutoLoadAttempted.current
    ) return

    historyAutoLoadAttempted.current = true
    loadSavedReports()
    // Loading is intentionally attempted once per signed-in homepage visit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account, page, savedReports])

  async function resumeSavedReport(claimId) {
    if (isBusy) return
    followLatestMessage.current = true
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
      setStatus('idle')
      navigateTo('conversation')
    } catch (requestError) {
      showError(requestError)
    }
  }

  async function signIn(event) {
    event.preventDefault()
    const formData = new FormData(event.currentTarget)
    setAuthStatus('loading'); setAuthError('')
    try {
      const session = await loginClaimant({
        email: formData.get('email'),
        password: formData.get('password'),
      })
      setClaimantAccessToken(session.access_token)
      historyAutoLoadAttempted.current = false
      setAccount(await getAuthenticatedAccount())
      const shouldContinueClaim = authReturnToClaim
      navigateTo(shouldContinueClaim ? 'home' : 'account', { replace: shouldContinueClaim })
      setAuthReturnToClaim(false)
      setAuthStatus('idle')
      if (shouldContinueClaim) await sendMessage()
    } catch (requestError) {
      setClaimantAccessToken(null)
      setAuthError(requestError.message)
      setAuthStatus('idle')
    }
  }

  async function signOut() {
    setAuthStatus('loading'); setAuthError('')
    try { await logoutClaimant() } catch (requestError) { setAuthError(requestError.message) }
    historyAutoLoadAttempted.current = false
    setSavedReports(null)
    setAccount(null); navigateTo('home', { replace: true }); setAuthStatus('idle')
  }

  async function openSavedClaims() {
    navigateTo('home')
    await loadSavedReports()
  }

  function startNewReport() {
    navigateTo('home')
    resetActiveReportState()
  }

  async function saveProfile(event) {
    event.preventDefault()
    const formData = new FormData(event.currentTarget)
    setAuthStatus('saving'); setAuthError('')
    try {
      setAccount(await updateAccountProfile({
        display_name: formData.get('display_name'), phone: formData.get('phone'),
      }))
    } catch (requestError) { setAuthError(requestError.message) }
    finally { setAuthStatus('idle') }
  }

  async function savePreferences(event) {
    event.preventDefault()
    const formData = new FormData(event.currentTarget)
    setAuthStatus('saving'); setAuthError('')
    try {
      setAccount(await updateAccountPreferences({
        email: formData.get('email') === 'on', sms: formData.get('sms') === 'on',
      }))
    } catch (requestError) { setAuthError(requestError.message) }
    finally { setAuthStatus('idle') }
  }

  return (
    <div className="customer-app">
      <header className="product-header">
        <a className="brand" href="/" onClick={(event) => { event.preventDefault(); hasStarted ? startNewReport() : navigateTo('home') }} aria-label="Northwind home">
          <span className="brand-mark">N</span>
          <span>Northwind Insurance</span>
        </a>
        {!hasStarted && page === 'home' && (
          <nav className="public-nav" aria-label="Main navigation">
            <a href="#claims">Claims</a>
            <a href="#how-it-works">How it works</a>
            <button className="login-button" type="button" onClick={() => navigateTo(account ? 'account' : 'login')}>
              {account ? 'My account' : 'Log in'}
            </button>
          </nav>
        )}
        {hasStarted && (
          <div className="header-actions">
            <button className="conversation-back" type="button" onClick={startNewReport} aria-label="Back">← Back</button>
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

      {!hasStarted && page === 'guided-motor' ? (
        <GuidedMotorClaim
          initialDescription={draft}
          onExit={(description) => {
            setDraft(description)
            navigateTo('home')
          }}
        />
      ) : !hasStarted && page === 'account' && account ? (
        <main className="account-page">
          <div className="account-shell">
            <button className="back-link account-back" type="button" onClick={() => navigateTo('home')}>← Back to claims</button>
            <section className="account-hero" aria-labelledby="account-title">
              <div className="account-avatar" aria-hidden="true">
                {account.profile.display_name?.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0]).join('').toUpperCase() || 'NW'}
              </div>
              <div className="account-identity">
                <p className="eyebrow">Your Northwind space</p>
                <h1 id="account-title">Your account</h1>
                <p>Welcome back, <strong>{account.profile.display_name}</strong>.</p>
                <span>{account.profile.email}</span>
              </div>
              <button className="account-claims-button" type="button" onClick={openSavedClaims} disabled={isBusy}>
                <span aria-hidden="true">◇</span>
                View claim conversations
                <span aria-hidden="true">→</span>
              </button>
            </section>

            <div className="development-banner" role="note">
              <span className="development-icon" aria-hidden="true">i</span>
              <span><strong>Development account</strong>This account contains anonymous synthetic data and is not a production Northwind identity.</span>
            </div>

            <div className="account-dashboard">
              <section className="account-settings" aria-labelledby="profile-settings-title">
                <div className="account-section-heading">
                  <span className="account-section-icon" aria-hidden="true">○</span>
                  <div><h2 id="profile-settings-title">Personal details</h2><p>Keep your contact information up to date.</p></div>
                </div>
                <form className="login-form account-form" onSubmit={saveProfile}>
                  <div className="account-field-grid">
                    <label htmlFor="account-name">Display name
                      <input id="account-name" name="display_name" defaultValue={account.profile.display_name} required />
                    </label>
                    <label htmlFor="account-email">Email address
                      <input id="account-email" value={account.profile.email} readOnly />
                    </label>
                  </div>
                  <label htmlFor="account-phone">Phone number
                    <input id="account-phone" name="phone" defaultValue={account.profile.phone} placeholder="Add a phone number" />
                  </label>
                  <div className="account-form-actions">
                    <span>Your email is connected to this development identity.</span>
                    <button className="primary-button" disabled={authStatus !== 'idle'}>{authStatus === 'saving' ? 'Saving…' : 'Save profile'}</button>
                  </div>
                </form>
              </section>

              <aside className="account-side-column">
                <section className="account-preferences" aria-labelledby="notification-settings-title">
                  <div className="account-section-heading compact">
                    <span className="account-section-icon" aria-hidden="true">◇</span>
                    <div><h2 id="notification-settings-title">Notifications</h2><p>Choose how Northwind keeps you updated.</p></div>
                  </div>
                  <form className="login-form preference-form" onSubmit={savePreferences}>
                    <label className="preference-row">
                      <span><strong>Email updates</strong><small>Claim progress and important requests</small></span>
                      <input name="email" type="checkbox" defaultChecked={account.preferences.email} />
                    </label>
                    <label className="preference-row">
                      <span><strong>SMS updates</strong><small>Time-sensitive notifications</small></span>
                      <input name="sms" type="checkbox" defaultChecked={account.preferences.sms} />
                    </label>
                    <button className="secondary-button" disabled={authStatus !== 'idle'}>Save preferences</button>
                  </form>
                </section>
                <section className="account-session" aria-labelledby="session-title">
                  <div><span className="session-status" aria-hidden="true" /><h2 id="session-title">Signed in securely</h2></div>
                  <p>Your current session gives access only to this development account&apos;s claims.</p>
                  <button className="account-logout" type="button" onClick={signOut} disabled={authStatus !== 'idle'}>Log out</button>
                </section>
              </aside>
            </div>
            {authError && <p className="backend-status is-error account-error" role="alert">{authError}</p>}
          </div>
        </main>
      ) : !hasStarted && page === 'login' ? (
        <main className="login-page">
          <section className="login-card" aria-labelledby="login-title">
            <button className="back-link" type="button" onClick={() => navigateTo('home')}>← Back to claims</button>
            <p className="eyebrow">Your Northwind account</p>
            <h1 id="login-title">Welcome back</h1>
            <p className="login-intro">Sign in to view an existing claim or continue a saved report.</p>
            <form className="login-form" onSubmit={signIn}>
              <label htmlFor="customer-email">Email address</label>
              <input id="customer-email" name="email" type="email" autoComplete="email" />
              <label htmlFor="customer-password">Password</label>
              <input id="customer-password" name="password" type="password" autoComplete="current-password" />
              <button className="primary-button login-submit" type="submit" disabled={authStatus !== 'idle'}>{authStatus === 'loading' ? 'Logging in…' : 'Log in'}</button>
              <p className="prototype-note" role="note">Development/test login only. Accounts and displayed data are anonymous and synthetic; no production identity provider is connected.</p>
              {authError && <p className="backend-status is-error" role="alert">{authError}</p>}
            </form>
            {!authReturnToClaim && (
              <button className="secondary-button start-without-login" type="button" onClick={() => navigateTo('home')}>
                Back to claim information
              </button>
            )}
            <div className="employee-access">
              <span>Northwind team member?</span>
              <a href="http://127.0.0.1:8002/">Employee access</a>
            </div>
          </section>
        </main>
      ) : !hasStarted ? (
        <main className="entry-page">
          <section className="hero-section" aria-labelledby="hero-title">
            <img className="hero-background" src={northwindValley} alt="" aria-hidden="true" fetchPriority="high" />
            <div className="hero-content">
              <p className="eyebrow">Northwind Insurance</p>
              <h1 id="hero-title">When the unexpected happens, we&apos;re here.</h1>
              <p className="hero-intro">
                Tell us what happened and we&apos;ll guide you through your claim, one clear step at a time.
              </p>
              <a className="hero-cta" href="#claims">
                Start a claim <span aria-hidden="true">→</span>
              </a>
            </div>
            <a className="hero-scroll" href="#claims">Claim online <span aria-hidden="true">↓</span></a>
          </section>
          <div className="claim-entry-layout">
            <section className="entry-main">
              <div className="entry-content">
              <section id="claims" className="claim-starter" aria-labelledby="claim-starter-title">
                <p className="eyebrow">Start your report</p>
                <h2 id="claim-starter-title">Tell us what happened</h2>
                <p className="claim-starter-intro">Describe the incident in your own words. We&apos;ll ask only what is needed and save your progress as you go.</p>
                <MessageComposer
                  draft={draft}
                  setDraft={setDraft}
                  onSubmit={sendMessage}
                  inputLabel="Incident description"
                  busy={isBusy}
                  buttonLabel={status === 'starting' ? 'Starting report...' : failedMessage ? 'Retry claim message' : 'Continue claim'}
                  error={error}
                  placeholder={claimTypePrompts[claimType]}
                />
                {failedMessage && (
                  <article className="message message-claimant is-failed">
                    <p className="message-author">{failedMessage.sender}</p>
                    <p>{failedMessage.text}</p>
                    <p className="message-state">
                      Audience: {failedMessage.audience} · {failedMessage.delivery} · {failedMessage.retry}
                    </p>
                  </article>
                )}
                <div className="choice-divider"><span>Optional guided claim</span></div>
                <h3 id="claim-type-heading">Choose a claim type for guided help</h3>
                <fieldset className="claim-tabs" aria-label="Claim type" aria-describedby="claim-type-heading">
                  {['motor', 'home', 'contents'].map((type) => (
                    <label
                      key={type}
                      className={`claim-option ${claimType === type ? 'is-selected' : ''}`}
                    >
                      <input
                        type="radio"
                        name="claim-type"
                        value={type}
                        checked={claimType === type}
                        onChange={() => setClaimType(type)}
                      />
                      <span className="claim-tab-icon" aria-hidden="true">{type === 'motor' ? '↗' : type === 'home' ? '⌂' : '◇'}</span>
                      {type[0].toUpperCase() + type.slice(1)}
                    </label>
                  ))}
                </fieldset>
              <div className="preparation-list">
                <h3>Helpful to have ready for your {claimType} claim</h3>
                <p>These items are useful, not required. You can start above without them and add missing information later.</p>
                <ul>
                  {CLAIM_MATERIALS[claimType].map(([title, description]) => (
                    <li key={title}>
                      <span className="material-check" aria-hidden="true">✓</span>
                      <span><strong>{title}</strong><small>{description}</small></span>
                    </li>
                  ))}
                </ul>
              </div>
              {claimType === 'motor' && (
                <button className="guided-start-button" type="button" onClick={() => navigateTo('guided-motor')}>
                  Start guided Motor claim
                  <span>Three clear steps with draft saving</span>
                </button>
              )}
              {claimType !== 'motor' && (
                <p className="guided-unavailable">Guided submission is not configured for this claim type yet. You can still describe what happened above.</p>
              )}
              </section>
              <div id="how-it-works" className="trust-row" aria-label="Claim service benefits">
                <span>Securely saved</span>
                <span>Pause anytime</span>
                <span>Human help available</span>
              </div>
              </div>
            </section>
            <SavedConversationHomePanel
              reports={savedReports}
              busy={isBusy}
              onLoad={loadSavedReports}
              onResume={resumeSavedReport}
              signedIn={hasClaimantAccessToken()}
              onSignIn={() => navigateTo('login')}
              error={account && status === 'error' ? error : ''}
            />
          </div>
        </main>
      ) : (
        <main className="intake-page">
          <aside className="conversation-history" aria-label="Saved conversations">
            <div className="history-brand">
              <span className="brand-mark">N</span>
              <span><strong>Northwind</strong><small>Claims assistant</small></span>
            </div>
            <button className="new-report-button" type="button" onClick={startNewReport}>
              <span aria-hidden="true">＋</span> New report
            </button>
            <div className="history-section-heading">
              <span>Your conversations</span>
              <button type="button" onClick={loadSavedReports} disabled={isBusy} aria-label="Refresh saved conversations">↻</button>
            </div>
            <nav className="history-list" aria-label="Claim conversations">
              {claim && (
                <button className="history-item is-active" type="button">
                  <span className="history-item-title">{conversationTitle(form, claim.incident_type)}</span>
                  <small><span className="saved-indicator" aria-hidden="true" /> Saved · Current conversation</small>
                </button>
              )}
              {savedReports?.filter((report) => report.claim_id !== claim?.claim_id).map((report) => (
                <button className="history-item" type="button" key={report.claim_id} onClick={() => resumeSavedReport(report.claim_id)} disabled={isBusy}>
                  <span className="history-item-title">{report.incident_type ? `${report.incident_type} claim` : 'Incident report'}</span>
                  <small>Saved report</small>
                </button>
              ))}
            </nav>
            <p className="history-note">Messages sent after your incident description are saved securely with this claim and restored when you resume.</p>
          </aside>
          <section className="conversation-panel" aria-labelledby="conversation-title">
            <div className="conversation-heading">
              <p className="eyebrow">Your report</p>
              <h1 id="conversation-title">Let&apos;s build the details together</h1>
              {handoff?.status !== 'in_progress' && <p>{nextStep?.summary}</p>}
            </div>

            <div className="message-list" ref={messageListRef} onScroll={trackConversationScroll} aria-live="polite" aria-label="Claim conversation messages">
              {messages.map((message) => (
                <article className={`message message-${message.actor}`} key={message.message_id}>
                  <p className="message-author">{message.actor === 'claimant' ? 'You' : 'Northwind'}</p>
                  <p>{messageText(message)}</p>
                  <p className="message-state">
                    Sender: {message.actor === 'claimant' ? 'You' : 'Northwind'} · Audience: Shared claim conversation · Delivered
                  </p>
                </article>
              ))}
              {status === 'sending' && pendingMessage && (
                <article className="message message-claimant is-pending" aria-label="Message sending">
                  <p className="message-author">You</p>
                  <p>{pendingMessage.text}</p>
                  <p className="message-state">Audience: {pendingMessage.audience} · Sending…</p>
                </article>
              )}
              {failedMessage && (
                <article className="message message-claimant is-failed" role="alert">
                  <p className="message-author">{failedMessage.sender}</p>
                  <p>{failedMessage.text}</p>
                  <p className="message-state">
                    Audience: {failedMessage.audience} · {failedMessage.delivery} · {failedMessage.retry}
                  </p>
                </article>
              )}
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

            {claim.external_service_action && (
              <ExternalServiceAction
                action={claim.external_service_action}
                consentChecked={serviceConsentChecked}
                setConsentChecked={setServiceConsentChecked}
                onRequest={requestVehicleAssessment}
                status={status}
                error={serviceError}
              />
            )}

            <MessageComposer
              draft={draft}
              setDraft={setDraft}
              onSubmit={sendMessage}
              inputLabel={inputLabel}
              busy={isBusy}
              buttonLabel={status === 'sending' ? 'Sending...' : failedMessage ? 'Retry message' : 'Send'}
              error={error}
            />
            <button
              className="secondary-button refresh-button"
              type="button"
              onClick={() => refreshClaimStatus()}
              disabled={isBusy}
            >
              {status === 'refreshing' ? 'Refreshing conversation...' : 'Refresh conversation'}
            </button>
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

function ExternalServiceAction({
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
        <div>
          <dt>Service</dt>
          <dd>{action.service_name}</dd>
        </div>
        <div>
          <dt>Provider</dt>
          <dd>{action.provider}</dd>
        </div>
      </dl>

      <h3>What Northwind will share</h3>
      <ul className="shared-data-list">
        {action.shared_data_summary.map((item) => <li key={item}>{item}</li>)}
      </ul>

      {needsConsent && (
        <label className="service-consent">
          <input
            type="checkbox"
            checked={consentChecked}
            onChange={(event) => setConsentChecked(event.target.checked)}
            disabled={isBusy}
          />
          <span>
            I give Northwind permission to share only these details for this assessment request.
          </span>
        </label>
      )}

      {isBusy && (
        <div className="service-progress" role="status">
          <span className="status-dot" />
          <span>
            {isRecordingConsent
              ? 'Recording your permission...'
              : 'Sending the assessment request...'}
          </span>
        </div>
      )}

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
          <strong>
            {action.status === 'assigned'
              ? 'Assessor assigned'
              : 'Request accepted into the assessor queue'}
          </strong>
          <p>{routing.next_step}</p>
          <dl>
            {routing.assessor_reference && (
              <div><dt>Assessor reference</dt><dd>{routing.assessor_reference}</dd></div>
            )}
            {routing.queue_reference && (
              <div><dt>Queue reference</dt><dd>{routing.queue_reference}</dd></div>
            )}
            {routing.expected_by && (
              <div>
                <dt>Expected by</dt>
                <dd>{new Date(routing.expected_by).toLocaleString()}</dd>
              </div>
            )}
          </dl>
          {routing.limitations.map((limitation) => (
            <p className="service-limitation" key={limitation}>{limitation}</p>
          ))}
        </div>
      )}

      {action.can_request && (!error || error.retryable) && (
        <button
          className="primary-button"
          type="button"
          onClick={onRequest}
          disabled={isBusy || (needsConsent && !consentChecked)}
        >
          {isRecordingConsent
            ? 'Recording permission...'
            : isRequesting
              ? 'Sending request...'
              : error?.retryable
                ? 'Retry assessment request'
                : needsConsent
                  ? 'Agree and request assessor'
                  : 'Request assessor'}
        </button>
      )}
    </section>
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
  placeholder = 'Write the details you know...',
}) {
  return (
    <form className="report-box" onSubmit={onSubmit}>
      <label htmlFor="incident-input">{inputLabel}</label>
      <textarea
        id="incident-input"
        className="report-text"
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        placeholder={placeholder}
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

function SavedConversationHomePanel({ reports, busy, onLoad, onResume, signedIn, onSignIn, error }) {
  return (
    <aside className="entry-side home-history" aria-labelledby="home-history-title">
      <div className="side-content">
        <div className="home-history-header">
          <div>
            <p className="side-label">Claim history</p>
            <h2 id="home-history-title">Your conversations</h2>
          </div>
          {signedIn && (
            <button className="history-refresh" type="button" onClick={onLoad} disabled={busy} aria-label="Refresh conversation history">↻</button>
          )}
        </div>
        {!signedIn ? (
          <div className="history-signed-out">
            <span className="history-bubble" aria-hidden="true">•••</span>
            <p>Sign in to see and continue your securely saved claim conversations.</p>
            <button className="history-sign-in" type="button" onClick={onSignIn}>Sign in <span aria-hidden="true">→</span></button>
          </div>
        ) : error && reports === null ? (
          <div className="history-empty history-error" role="alert">
            <p>{error}</p>
            <button type="button" onClick={onLoad} disabled={busy}>Try again</button>
          </div>
        ) : reports === null ? (
          <div className="history-loading" role="status" aria-label="Loading conversations">
            <span /><span /><span />
          </div>
        ) : reports.length === 0 ? (
          <div className="history-empty">
            <span className="history-bubble" aria-hidden="true">＋</span>
            <p>No conversations yet. Your first claim will appear here automatically.</p>
          </div>
        ) : (
          <>
            <p className="history-group-label">Recent</p>
            <nav className="home-history-list" aria-label="Saved claim conversations">
              {reports.map((report) => (
                <button type="button" key={report.claim_id} onClick={() => onResume(report.claim_id)} disabled={busy} aria-label={`Resume ${savedConversationTitle(report)}`}>
                  <span className="history-list-icon" aria-hidden="true">◇</span>
                  <span className="history-list-copy">
                    <strong>{savedConversationTitle(report)}</strong>
                    <small>{report.customer_next_step.summary}</small>
                    <small className="history-list-reference">{shortClaimReference(report.claim_id)}</small>
                  </span>
                  <span className="history-list-arrow" aria-hidden="true">›</span>
                </button>
              ))}
            </nav>
          </>
        )}
        <p className="history-privacy"><span aria-hidden="true">●</span> Conversations are saved securely</p>
      </div>
    </aside>
  )
}

export default App
