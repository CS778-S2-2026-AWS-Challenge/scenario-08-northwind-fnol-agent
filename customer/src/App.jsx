import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ApiRequestError,
  confirmClaimFields,
  createClaim,
  createExternalClaim,
  grantAssessorConsent,
  getAuthenticatedAccount,
  hasClaimantAccessToken,
  getClaim,
  getClaimMessages,
  getClaimEvidence,
  getRuntimeCapabilities,
  listClaims,
  loginClaimant,
  logoutClaimant,
  requestId,
  requestHumanSupport,
  promoteAnonymousClaim,
  requestAssessorRouting,
  registerClaimant,
  requestEvidenceUpload,
  uploadEvidenceContent,
  completeEvidenceUpload,
  resumeClaimSession,
  startClaimSession,
  streamClaimUpdates,
  submitClaimMessage,
  setClaimantAccessToken,
  updateAccountPreferences,
  updateAccountProfile,
  updateClaimField,
} from './api.js'
import './App.css'
import './styles/frontend-refactor.css'
import MessageComposer from './components/MessageComposer.jsx'
import ExternalServiceAction from './components/ExternalServiceAction.jsx'

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

const DYNAMIC_SELECTION_LABELS = {
  required_now: 'Needed now',
  candidate_now: 'Helpful now',
  pending_later: 'Needed later',
}

const DYNAMIC_VALUE_LABELS = {
  missing: 'Not provided yet',
  proposed: 'Suggested from your report',
  confirmed: 'Confirmed',
  disputed: 'Needs correction',
  pending_generation: 'Expected later',
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

function dynamicSelectionLabel(selectionState) {
  return DYNAMIC_SELECTION_LABELS[selectionState] || 'Relevant to your claim'
}

function dynamicValueLabel(valueState, field) {
  if (field && valueState === 'missing') return 'Not provided yet'
  return DYNAMIC_VALUE_LABELS[valueState] || 'Recorded'
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

function evidenceFileStatusLabel(fileStatus, status) {
  if (fileStatus === 'awaiting_upload') return 'Upload incomplete'
  if (fileStatus === 'processing') return 'Processing'
  if (fileStatus === 'failed') return 'Processing failed'
  if (fileStatus === 'ready') return 'Ready'
  if (fileStatus) return fileStatus
  return status === 'received' ? 'Received' : status
}

function mergeFields(current, changes) {
  return changes.reduce(
    (fields, change) => ({ ...fields, [change.field_code]: change.field }),
    current,
  )
}

function claimProgress(nextStep, form) {
  const status = nextStep?.status
  const stages = {
    describe_incident: { current: 1, total: 3, label: 'Describe the incident' },
    provide_incident_location: { current: 2, total: 3, label: 'Add the key details' },
    confirmation_required: { current: 2, total: 3, label: 'Check the details' },
    ready_to_create: { current: 3, total: 3, label: 'Ready to create' },
    claim_created: { current: 3, total: 3, label: 'Claim submitted' },
  }
  const fallback = Object.keys(form).length > 0
    ? { current: 2, total: 3, label: 'Add the key details' }
    : stages.describe_incident
  const stage = stages[status] || fallback
  return {
    ...stage,
    saved: Object.values(form).filter((field) => field.status === 'confirmed').length,
  }
}

function App() {
  const initialPage = (() => {
    const path = globalThis.location?.pathname || '/'
    if (path === '/auth/login') return 'login'
    if (path === '/auth/register') return 'register'
    if (path === '/account') return 'account'
    if (path === '/how-it-works') return 'how-it-works'
    return 'home'
  })()
  const [page, setPageState] = useState(initialPage)
  const [account, setAccount] = useState(null)
  const [authStatus, setAuthStatus] = useState('idle')
  const [authError, setAuthError] = useState('')
  const [claimType, setClaimType] = useState('motor')
  const [draft, setDraft] = useState('')
  const [claim, setClaim] = useState(null)
  const [sessionId, setSessionId] = useState(null)
  const [messages, setMessages] = useState([])
  const [form, setForm] = useState({})
  const [dynamicForm, setDynamicForm] = useState(null)
  const [nextStep, setNextStep] = useState(null)
  const [status, setStatus] = useState('idle')
  const [error, setError] = useState('')
  const [editingField, setEditingField] = useState(null)
  const [editValue, setEditValue] = useState('')
  const [handoff, setHandoff] = useState(null)
  const [savedReports, setSavedReports] = useState(null)
  const [detailsOpen, setDetailsOpen] = useState(true)
  const [mobileView, setMobileView] = useState('chat')
  const [workspaceView, setWorkspaceView] = useState('chat')
  const [runtimeCapabilities, setRuntimeCapabilities] = useState({ claim_types: ['motor', 'home', 'contents'], models: [] })
  const [selectedModel, setSelectedModel] = useState('')
  const [attachments, setAttachments] = useState([])
  const [evidenceItems, setEvidenceItems] = useState([])
  const [evidenceSyncNotice, setEvidenceSyncNotice] = useState('')
  const [evidencePollingKey, setEvidencePollingKey] = useState(0)
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
  const latestEvidenceRevision = useRef(0)
  const latestEvidenceItems = useRef([])
  const evidenceHasLocalMutation = useRef(false)
  const evidenceClaimId = useRef(null)
  const hasStarted = claim !== null

  useEffect(() => {
    if (!hasClaimantAccessToken()) return
    getAuthenticatedAccount()
      .then((currentAccount) => setAccount(currentAccount))
      .catch(() => setClaimantAccessToken(null))
  }, [])

  useEffect(() => {
    if (account && (page === 'login' || page === 'register')) {
      setPage('home', { replace: true })
    }
  // setPage is a stable local navigation helper; keep this guard tied to auth state.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account, page])

  function routeForPage(nextPage) {
    if (nextPage === 'login') return '/auth/login'
    if (nextPage === 'register') return '/auth/register'
    if (nextPage === 'account') return '/account'
    if (nextPage === 'how-it-works') return '/how-it-works'
    if (claim?.claim_id) return `/claims/${claim.claim_id}`
    return '/'
  }

  function setPage(nextPage, { replace = false } = {}) {
    setPageState(nextPage)
    const nextPath = routeForPage(nextPage)
    if (globalThis.location?.pathname !== nextPath) {
      globalThis.history?.[replace ? 'replaceState' : 'pushState']({ northwindRoute: nextPage }, '', nextPath)
    }
  }

  function pageForPath(pathname) {
    if (pathname === '/auth/login') return 'login'
    if (pathname === '/auth/register') return 'register'
    if (pathname === '/account') return account ? 'account' : 'login'
    if (pathname === '/how-it-works') return hasStarted ? 'home' : 'how-it-works'
    if (pathname.startsWith('/claims/')) return claim?.claim_id ? 'home' : 'home'
    return 'home'
  }

  useEffect(() => {
    const onPopState = () => {
      const path = globalThis.location?.pathname || '/'
      const nextPage = pageForPath(path)
      setPageState(nextPage)
      const canonicalPath = nextPage === 'home' && claim?.claim_id
        ? `/claims/${claim.claim_id}`
        : routeForPage(nextPage)
      if (path !== canonicalPath) {
        globalThis.history?.replaceState({ northwindRoute: nextPage }, '', canonicalPath)
      }
    }
    globalThis.addEventListener?.('popstate', onPopState)
    return () => globalThis.removeEventListener?.('popstate', onPopState)
  // The handlers intentionally read the latest route state when this effect is rebound.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account, claim?.claim_id, hasStarted, page])

  useEffect(() => {
    const expectedPath = page === 'login'
      ? '/auth/login'
      : page === 'register'
        ? '/auth/register'
        : page === 'account'
          ? '/account'
          : page === 'how-it-works'
            ? '/how-it-works'
            : claim?.claim_id ? `/claims/${claim.claim_id}` : '/'
    if (globalThis.location?.pathname !== expectedPath) {
      globalThis.history?.replaceState({ northwindRoute: page }, '', expectedPath)
    }
  }, [page, claim?.claim_id])

  const isBusy = [
    'starting',
    'sending',
    'confirming',
    'saving',
    'requesting-support',
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
  const inputLabel = INPUT_LABELS[nextStep?.status] || 'Add more information'
  const progress = useMemo(() => claimProgress(nextStep, form), [nextStep, form])
  const visibleDynamicFields = useMemo(
    () => (dynamicForm?.fields || []).filter(
      (field) => !['inactive', 'system_owned'].includes(field.selection_state),
    ),
    [dynamicForm],
  )
  const serviceConsentChecked = externalServiceInteraction.claimId === claim?.claim_id
    && externalServiceInteraction.consentChecked
  const serviceError = externalServiceInteraction.claimId === claim?.claim_id
    ? externalServiceInteraction.error
    : null

  function attachmentForEvidence(evidence, current = {}) {
    const fileStatus = evidence.file_status || evidence.status
    const status = fileStatus === 'awaiting_upload'
      ? 'failed'
      : fileStatus === 'processing' || fileStatus === 'failed'
        ? fileStatus
        : 'uploaded'
    const statusLabel = evidenceFileStatusLabel(fileStatus, evidence.status) || 'Uploaded'
    const canCheckStatus = fileStatus === 'failed'
      && current.retryFile
      && current.retryAttempt
    return {
      ...current,
      id: current.id || evidence.evidence_id,
      evidenceId: evidence.evidence_id,
      name: evidence.original_filename || evidence.kind,
      status,
      statusLabel,
      ...(canCheckStatus
        ? {
          retry: () => handleFileSelected(current.retryFile, current.retryAttempt),
          retryLabel: 'Check status',
        }
        : fileStatus === 'failed'
          ? {}
          : { retry: null, retryLabel: null }),
    }
  }

  function syncEvidenceProjection(response) {
    const responseRevision = Number(response.revision || 0)
    if (responseRevision && responseRevision < latestEvidenceRevision.current) return false
    if (!response.items?.length && (latestEvidenceItems.current.length || evidenceHasLocalMutation.current)) return false
    latestEvidenceRevision.current = Math.max(latestEvidenceRevision.current, responseRevision)
    const items = response.items || []
    latestEvidenceItems.current = items
    setEvidenceItems(items)
    setClaim((current) => current ? { ...current, revision: response.revision } : current)
    setAttachments((current) => {
      const currentByEvidenceId = new Map(
        current.filter((item) => item.evidenceId).map((item) => [item.evidenceId, item]),
      )
      if (items.length === 0 && current.some((item) => item.status === 'uploading' || item.retry || item.retryFile)) {
        return current
      }
      if (current.some((item) => item.status === 'uploading')) {
        return current.map((item) => {
          const evidence = items.find((candidate) => candidate.evidence_id === item.evidenceId)
          return evidence ? attachmentForEvidence(evidence, item) : item
        })
      }
      return items.map((item) => attachmentForEvidence(item, currentByEvidenceId.get(item.evidence_id)))
    })
    return true
  }

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

  useEffect(() => {
    if (claim?.revision) {
      latestRevision.current = Math.max(latestRevision.current, claim.revision)
    }
  }, [claim?.revision])

  useEffect(() => {
    if (!claim?.claim_id || !sessionId) return undefined
    const controller = new AbortController()
    let active = true
    let reconnectDelay = 1000

    async function applyLiveUpdate(event) {
      if (!active || event.claim_revision <= latestRevision.current) return
      const [currentClaim, conversation] = await Promise.all([
        getClaim(claim.claim_id),
        getClaimMessages(claim.claim_id, sessionId),
      ])
      if (!active) return
      latestRevision.current = currentClaim.revision
      setClaim(currentClaim)
      setForm(currentClaim.form)
      setDynamicForm(currentClaim.dynamic_form || null)
      setNextStep(currentClaim.customer_next_step)
      setHandoff(currentClaim.handoff || null)
      setMessages(conversation.items)
      reconnectDelay = 1000
    }

    async function connect() {
      while (active && !controller.signal.aborted) {
        try {
          await streamClaimUpdates({
            claimId: claim.claim_id,
            sessionId,
            afterRevision: latestRevision.current,
            signal: controller.signal,
            onEvent: applyLiveUpdate,
          })
        } catch (streamFailure) {
          if (!active || controller.signal.aborted) return
          if (
            streamFailure instanceof ApiRequestError
            && streamFailure.code === 'INVALID_EVENT_CURSOR'
            && streamFailure.currentRevision
          ) {
            latestRevision.current = streamFailure.currentRevision
          }
        }
        if (!active || controller.signal.aborted) return
        await new Promise((resolve) => globalThis.setTimeout(resolve, reconnectDelay))
        reconnectDelay = Math.min(reconnectDelay * 2, 8000)
      }
    }

    connect()
    return () => {
      active = false
      controller.abort()
    }
  }, [claim?.claim_id, sessionId])

  useEffect(() => {
    if (!account) return undefined
    let active = true
    listClaims()
      .then((response) => {
        if (active) setSavedReports(response.items.filter((item) => item.can_resume))
      })
      .catch(() => {
        if (active) setSavedReports(null)
      })
    return () => { active = false }
  }, [account])

  useEffect(() => {
    let active = true
    getRuntimeCapabilities()
      .then((capabilities) => {
        if (!active) return
        setRuntimeCapabilities(capabilities)
        setSelectedModel(capabilities.models?.[0]?.id || '')
      })
      .catch(() => {})
    return () => { active = false }
  }, [])

  useEffect(() => {
    if (!claim?.claim_id) {
      evidenceClaimId.current = null
      latestEvidenceRevision.current = 0
      latestEvidenceItems.current = []
      evidenceHasLocalMutation.current = false
      setEvidenceItems([])
      setAttachments([])
      setEvidencePollingKey(0)
      return undefined
    }
    if (evidenceClaimId.current !== claim.claim_id) {
      evidenceClaimId.current = claim.claim_id
      latestEvidenceRevision.current = 0
      latestEvidenceItems.current = []
      evidenceHasLocalMutation.current = false
    }
    let active = true
    getClaimEvidence(claim.claim_id)
      .then((response) => {
        if (active) {
          if (syncEvidenceProjection(response)) setEvidenceSyncNotice('')
          if ((response.items || []).some((item) => item.file_status === 'processing')) {
            setEvidencePollingKey((current) => current + 1)
          }
        }
      })
      .catch(() => {})
    return () => { active = false }
  // The projection updater only uses stable React setters and is intentionally local to this view.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [claim?.claim_id])

  useEffect(() => {
    if (!claim?.claim_id || !evidencePollingKey) {
      return undefined
    }
    let active = true
    let timer
    let delay = 1500
    const maxDelay = 12000
    const schedule = () => {
      timer = globalThis.setTimeout(sync, delay)
    }
    async function sync() {
      try {
        const response = await getClaimEvidence(claim.claim_id)
        if (!active) return
        const applied = syncEvidenceProjection(response)
        if (applied) setEvidenceSyncNotice('')
        delay = 1500
        if (!applied || (response.items || []).some((item) => item.file_status === 'processing')) schedule()
      } catch {
        if (!active) return
        setEvidenceSyncNotice('We could not check the latest file status because the connection was interrupted. We will keep trying to reconnect.')
        delay = Math.min(delay * 2, maxDelay)
        schedule()
      }
    }
    schedule()
    return () => {
      active = false
      globalThis.clearTimeout(timer)
    }
  // The projection updater only uses stable React setters and is intentionally local to this view.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [claim?.claim_id, evidencePollingKey])

  async function handleFileSelected(file, existingAttempt = null) {
    if (isBusy) return
    if (!hasClaimantAccessToken()) {
      setError('Sign in before uploading a file. Your anonymous conversation is still available, and you can resume it after signing in.')
      setStatus('error')
      return
    }
    setError('')
    const attempt = existingAttempt || {
      localId: requestId('file'),
      claimKey: requestId('claim'),
      uploadKey: requestId('evidence-upload'),
      completeKey: requestId('evidence-complete'),
    }
    const localId = attempt.localId
    setAttachments((current) => existingAttempt
      ? current.map((item) => item.id === localId
        ? { ...item, status: 'uploading', statusLabel: 'Uploading…', retry: null }
        : item)
      : [...current, { id: localId, name: file.name, status: 'uploading', statusLabel: 'Uploading…' }])
    try {
      let activeClaim = claim
      if (!activeClaim) {
        const created = await createClaim({ idempotencyKey: attempt.claimKey, incidentType: claimType })
        activeClaim = created.claim
        setClaim(activeClaim)
        setSessionId(created.session.session_id)
        setForm(activeClaim.form)
        setDynamicForm(activeClaim.dynamic_form || null)
        setNextStep(activeClaim.customer_next_step)
      }
      if (existingAttempt) {
        const authoritative = await getClaimEvidence(activeClaim.claim_id)
        syncEvidenceProjection(authoritative)
        setEvidenceSyncNotice('')
        const observed = (authoritative.items || []).find(
          (item) => item.evidence_id === attempt.evidenceId,
        )
        if (observed && observed.file_status !== 'awaiting_upload') {
          if (observed.file_status === 'processing') {
            setEvidencePollingKey((current) => current + 1)
          }
          setAttachments((current) => current.map((item) => item.id === localId
            ? attachmentForEvidence(observed, {
              ...item,
              retry: observed.file_status === 'failed'
                ? () => handleFileSelected(file, attempt)
                : null,
              retryLabel: observed.file_status === 'failed' ? 'Check status' : null,
            })
            : item))
          setStatus('idle')
          return
        }
      }
      const requested = await requestEvidenceUpload({
        claimId: activeClaim.claim_id,
        revision: activeClaim.revision,
        file,
        kind: file.type.startsWith('image/') ? 'incident_photo' : 'other_document',
        idempotencyKey: attempt.uploadKey,
      })
      evidenceHasLocalMutation.current = true
      latestEvidenceRevision.current = requested.revision
      attempt.evidenceId = requested.evidence_id
      setClaim((current) => current ? { ...current, revision: requested.revision } : current)
      await uploadEvidenceContent({ upload: requested.upload, file })
      const checksumBuffer = await globalThis.crypto.subtle.digest('SHA-256', await file.arrayBuffer())
      const checksum = `sha256:${Array.from(new Uint8Array(checksumBuffer), (byte) => byte.toString(16).padStart(2, '0')).join('')}`
      const completed = await completeEvidenceUpload({
        claimId: activeClaim.claim_id,
        evidenceId: requested.evidence_id,
        revision: requested.revision,
        checksum,
        idempotencyKey: attempt.completeKey,
      })
      latestEvidenceRevision.current = completed.revision
      attempt.evidenceId = completed.evidence.evidence_id
      latestEvidenceItems.current = [completed.evidence]
      setEvidencePollingKey((current) => current + 1)
      setClaim((current) => current ? { ...current, revision: completed.revision } : current)
      setEvidenceItems((current) => [...current.filter((item) => item.evidence_id !== completed.evidence.evidence_id), completed.evidence])
      setAttachments((current) => current.map((item) => item.id === localId
        ? attachmentForEvidence(completed.evidence, {
          ...item,
          retryFile: file,
          retryAttempt: attempt,
        })
        : item))
      setStatus('idle')
    } catch (requestError) {
      setAttachments((current) => current.map((item) => item.id === localId
        ? { ...item, status: 'failed', statusLabel: requestError.message || 'Upload failed', retry: () => handleFileSelected(file, attempt) }
        : item))
      showError(requestError)
    }
  }

  async function refreshAfterConflict() {
    if (!claim) return
    const current = await getClaim(claim.claim_id)
    setClaim(current)
    setForm(current.form)
    setDynamicForm(current.dynamic_form || null)
    setNextStep(current.customer_next_step)
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
    event.preventDefault()
    const text = draft.trim()
    if (!text || isBusy) return

    setError('')
    setFailedMessage(null)
    setStatus(hasStarted ? 'sending' : 'starting')
    let messageWasSubmitted = Boolean(claim)
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
      setPendingMessage({ text })
      let activeClaim = claim
      let activeSessionId = sessionId
      if (!activeClaim) {
        const created = await createClaim({ idempotencyKey: operation.claimKey })
        activeClaim = created.claim
        activeSessionId = created.session.session_id
        setClaim(created.claim)
        setSessionId(activeSessionId)
        setForm(created.claim.form)
        setDynamicForm(created.claim.dynamic_form || null)
        setNextStep(created.claim.customer_next_step)
        messageWasSubmitted = true
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
      setDynamicForm(turn.dynamic_form || null)
      setClaim((current) => ({ ...current, revision: turn.claim_revision }))
      if (turn.decision) setNextStep(turn.decision.customer_next_step)
      if (turn.handoff) setHandoff(turn.handoff)
      setDraft('')
      pendingSubmission.current = null
      setPendingMessage(null)
      setFailedMessage(null)
      setStatus('idle')
    } catch (requestError) {
      setPendingMessage(null)
      const knownRejection = requestError instanceof ApiRequestError
        && requestError.status >= 400
        && requestError.status < 500
      if (messageWasSubmitted) {
        setFailedMessage({
          text,
          sender: 'You',
          message: knownRejection
            ? 'We could not send that message. Please try again.'
            : 'We could not confirm delivery. Please try again.',
        })
      }
      showError(requestError)
    }
  }

  async function startNewChat() {
    if (isBusy) return
    const hasConversationContent = messages.length > 0
      || Object.keys(form).length > 0
      || attachments.length > 0
      || Boolean(handoff)
    if (claim && !hasConversationContent) {
      setDraft('')
      setError('')
      setFailedMessage(null)
      setWorkspaceView('chat')
      setMobileView('chat')
      return
    }
    setError('')
    setFailedMessage(null)
    setStatus('starting')
    try {
      if (claim && hasConversationContent) {
        const session = await startClaimSession({ claimId: claim.claim_id, intent: 'new' })
        const refreshedClaim = await getClaim(claim.claim_id)
        setClaim(refreshedClaim)
        setForm(refreshedClaim.form)
        setDynamicForm(refreshedClaim.dynamic_form || null)
        setNextStep(refreshedClaim.customer_next_step)
        setSessionId(session.session_id)
        setMessages([])
        setResumeContext(null)
        setHandoff(null)
        setWorkspaceView('chat')
        setMobileView('chat')
        setDraft('')
        setStatus('idle')
        return
      }
      const created = await createClaim({ idempotencyKey: requestId('claim'), incidentType: claimType || null })
      setClaim(created.claim)
      setSessionId(created.session.session_id)
      setMessages([])
      setForm(created.claim.form)
      setDynamicForm(created.claim.dynamic_form || null)
      setNextStep(created.claim.customer_next_step)
      setHandoff(null)
      setEvidenceItems([])
      setAttachments([])
      setWorkspaceView('chat')
      setMobileView('chat')
      setDraft('')
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
        setDynamicForm(current.dynamic_form || null)
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
      setDynamicForm(current.dynamic_form || null)
      setNextStep(current.customer_next_step)
      setHandoff(current.handoff || null)
      setResumeContext(session.resume)
      setSavedReports(null)
      setStatus('idle')
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
      if (claim?.claim_id && !account) {
        try {
          const promoted = await promoteAnonymousClaim(claim.claim_id)
          setClaim(promoted)
          setForm(promoted.form)
          setDynamicForm(promoted.dynamic_form || null)
          setNextStep(promoted.customer_next_step)
        } catch (promotionError) {
          if (!(promotionError instanceof ApiRequestError && promotionError.status === 404)) throw promotionError
        }
      }
      setAccount(await getAuthenticatedAccount())
      if (!claim) {
        const created = await createClaim({ idempotencyKey: requestId('claim'), incidentType: claimType || null })
        setClaim(created.claim)
        setSessionId(created.session.session_id)
        setForm(created.claim.form)
        setDynamicForm(created.claim.dynamic_form || null)
        setNextStep(created.claim.customer_next_step)
      }
      setWorkspaceView('chat'); setPage('home'); setAuthStatus('idle')
    } catch (requestError) {
      setClaimantAccessToken(null)
      setAuthError(requestError.message)
      setAuthStatus('idle')
    }
  }

  async function signUp(event) {
    event.preventDefault()
    const formData = new FormData(event.currentTarget)
    const password = String(formData.get('password') || '')
    const confirmPassword = String(formData.get('confirm_password') || '')
    if (password !== confirmPassword) {
      setAuthError('Passwords do not match.')
      return
    }
    setAuthStatus('loading'); setAuthError('')
    try {
      const session = await registerClaimant({
        display_name: formData.get('display_name'),
        email: formData.get('email'),
        password,
      })
      setClaimantAccessToken(session.access_token)
      if (claim?.claim_id && !account) {
        try {
          const promoted = await promoteAnonymousClaim(claim.claim_id)
          setClaim(promoted)
          setForm(promoted.form)
          setDynamicForm(promoted.dynamic_form || null)
          setNextStep(promoted.customer_next_step)
        } catch (promotionError) {
          if (!(promotionError instanceof ApiRequestError && promotionError.status === 404)) throw promotionError
        }
      }
      setAccount(await getAuthenticatedAccount())
      if (!claim) {
        const created = await createClaim({ idempotencyKey: requestId('claim'), incidentType: claimType || null })
        setClaim(created.claim)
        setSessionId(created.session.session_id)
        setForm(created.claim.form)
        setDynamicForm(created.claim.dynamic_form || null)
        setNextStep(created.claim.customer_next_step)
      }
      setWorkspaceView('chat'); setPage('home'); setAuthStatus('idle')
    } catch (requestError) {
      setClaimantAccessToken(null)
      setAuthError(requestError.message)
      setAuthStatus('idle')
    }
  }

  async function signOut() {
    setAuthStatus('loading'); setAuthError('')
    try { await logoutClaimant() } catch (requestError) { setAuthError(requestError.message) }
    setAccount(null)
    setSavedReports(null)
    setClaim(null)
    setSessionId(null)
    setMessages([])
    setForm({})
    setDynamicForm(null)
    setNextStep(null)
    setHandoff(null)
    setAttachments([])
    setEvidenceItems([])
    setResumeContext(null)
    setWorkspaceView('chat')
    setMobileView('chat')
    setPage('home', { replace: true })
    setAuthStatus('idle')
  }

  async function openSavedClaims() {
    setPage('home')
    await loadSavedReports()
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

  const isUrgentSupport = handoff?.support_need === 'urgent'

  return (
    <div className={`customer-app ${!hasStarted && page === 'home' ? 'entry-shell' : ''}`}>
      <header className={`product-header ${hasStarted && !['login', 'register'].includes(page) ? 'is-intake-header' : ''}`}>
        <a className="brand" href="/" onClick={(event) => { event.preventDefault(); setPage('home') }} aria-label="Northwind home">
          <span className="brand-mark">N</span>
          <span>Northwind Insurance</span>
        </a>
        {!hasStarted && page !== 'home' && page !== 'how-it-works' && (
          <button className="login-button" type="button" onClick={() => setPage(account ? 'account' : 'login')}>
            {account ? 'My account' : 'Log in'}
          </button>
        )}
        {hasStarted && !['login', 'register'].includes(page) && (
          <div className="header-actions">
            <button className="aux-link" type="button" onClick={() => setPage('home')}>Use the traditional web form</button>
            <button className="support-button" type="button" onClick={requestSupport} disabled={isBusy || Boolean(handoff)}>
              {status === 'requesting-support' ? 'Opening staff assistance...' : 'Staff Assistance'}
            </button>
          </div>
        )}
      </header>

      {!hasStarted && page === 'how-it-works' ? (
        <main className="how-it-works-page">
          <section className="how-it-works-card" aria-labelledby="how-it-works-title">
            <button className="back-link" type="button" onClick={() => setPage('home')}>← Back</button>
            <p className="eyebrow">A calmer way to start</p>
            <h1 id="how-it-works-title">How this works</h1>
            <p>Tell us what happened in your own words. You do not need to know the right insurance terms or follow a fixed questionnaire.</p>
            <p>Our claims assistant keeps track of the details, asks only for what is still needed, and explains the next step clearly. You can start without an account and log in later if you want to save your progress.</p>
          </section>
        </main>
      ) : !hasStarted && page === 'account' && account ? (
        <main className="auth-page auth-page-account">
          <section className="login-card account-card" aria-labelledby="account-title">
            <button className="back-link" type="button" onClick={() => setPage('home')}>← Back to claims</button>
            <p className="eyebrow">Northwind account</p>
            <h1 id="account-title">Your account</h1>
            <p className="prototype-note" role="note">Manage your profile and communication preferences.</p>
            <form className="login-form" onSubmit={saveProfile}>
              <label htmlFor="account-name">Display name</label>
              <input id="account-name" name="display_name" defaultValue={account.profile.display_name} required />
              <label htmlFor="account-email">Email address</label>
              <input id="account-email" value={account.profile.email} readOnly />
              <label htmlFor="account-phone">Phone</label>
              <input id="account-phone" name="phone" defaultValue={account.profile.phone} />
              <button className="primary-button" disabled={authStatus !== 'idle'}>Save profile</button>
            </form>
            <form className="login-form" onSubmit={savePreferences}>
              <label><input name="email" type="checkbox" defaultChecked={account.preferences.email} /> Email updates</label>
              <label><input name="sms" type="checkbox" defaultChecked={account.preferences.sms} /> SMS updates</label>
              <button className="secondary-button" disabled={authStatus !== 'idle'}>Save preferences</button>
            </form>
            {authError && <p className="backend-status is-error" role="alert">{authError}</p>}
            <button className="secondary-button" type="button" onClick={openSavedClaims} disabled={isBusy}>
              View saved claims
            </button>
            <button className="secondary-button" type="button" onClick={signOut} disabled={authStatus !== 'idle'}>Log out</button>
          </section>
        </main>
      ) : (page === 'login' || page === 'register') ? (
        <main className="auth-page auth-page-login">
          <section className="login-card" aria-labelledby="login-title">
            <button className="back-link" type="button" onClick={() => setPage('home')}>← Back to claims</button>
            <p className="eyebrow">Your Northwind account</p>
            {page === 'login' ? (
              <>
                <h1 id="login-title">Welcome back</h1>
                <p className="login-intro">Sign in to view an existing claim or continue a saved claim.</p>
                <form className="login-form" onSubmit={signIn}>
                  <label htmlFor="customer-email">Email address</label>
                  <input id="customer-email" name="email" type="email" autoComplete="email" required />
                  <label htmlFor="customer-password">Password</label>
                  <input id="customer-password" name="password" type="password" autoComplete="current-password" required />
                  <button className="primary-button login-submit" type="submit" disabled={authStatus !== 'idle'}>{authStatus === 'loading' ? 'Logging in…' : 'Log in'}</button>
                  {authError && <p className="backend-status is-error" role="alert">{authError}</p>}
                </form>
                <p className="auth-switch">New to Northwind? <button className="text-link" type="button" onClick={() => { setAuthError(''); setPage('register') }}>Create an account</button></p>
              </>
            ) : (
              <>
                <h1 id="login-title">Create your account</h1>
                <p className="login-intro">Save your claim progress and return when you are ready.</p>
                <form className="login-form" onSubmit={signUp}>
                  <label htmlFor="customer-name">Your name</label>
                  <input id="customer-name" name="display_name" autoComplete="name" required />
                  <label htmlFor="customer-register-email">Email address</label>
                  <input id="customer-register-email" name="email" type="email" autoComplete="email" required />
                  <label htmlFor="customer-register-password">Password</label>
                  <input id="customer-register-password" name="password" type="password" autoComplete="new-password" minLength="8" required />
                  <label htmlFor="customer-confirm-password">Confirm password</label>
                  <input id="customer-confirm-password" name="confirm_password" type="password" autoComplete="new-password" minLength="8" required />
                  <button className="primary-button login-submit" type="submit" disabled={authStatus !== 'idle'}>{authStatus === 'loading' ? 'Creating account…' : 'Create account'}</button>
                  {authError && <p className="backend-status is-error" role="alert">{authError}</p>}
                </form>
                <p className="auth-switch">Already have an account? <button className="text-link" type="button" onClick={() => { setAuthError(''); setPage('login') }}>Log in</button></p>
              </>
            )}
            <button className="secondary-button start-without-login" type="button" onClick={() => setPage('home')}>
              Start a claim without logging in
            </button>
            <div className="employee-access">
              <span>Northwind team member?</span>
              <a href="http://127.0.0.1:8002/">Employee access</a>
            </div>
          </section>
        </main>
      ) : !hasStarted ? (
        <main className="entry-page">
          <section className="entry-hero" aria-labelledby="entry-title">
            <div className="entry-content">
              <p className="entry-brand-line" id="entry-title">Understand insurance. Understand you better.</p>
              <p className="entry-intro">Tell us what happened — we&apos;ll take it from there.</p>
              <section id="claims" className="claim-starter" aria-labelledby="claim-starter-title">
                <h1 id="claim-starter-title">Tell us what happened</h1>
                <MessageComposer
                  draft={draft}
                  setDraft={setDraft}
                  onSubmit={sendMessage}
                  inputLabel="Incident description"
                  busy={isBusy}
                  buttonLabel={status === 'starting' ? 'Starting claim...' : failedMessage ? 'Retry claim message' : 'Start claim'}
                  error={error}
                  placeholder="Tell us what happened…"
                  claimType={claimType}
                  setClaimType={setClaimType}
                  claimTypes={runtimeCapabilities.claim_types}
                  models={runtimeCapabilities.models}
                  selectedModel={selectedModel}
                  setSelectedModel={setSelectedModel}
                  attachments={attachments}
                  onFileSelected={handleFileSelected}
                />
                <div className="entry-hint-row">
                  <span>Press Enter to start, or ask anything about a claim</span>
                  <button className="text-link" type="button" onClick={() => setPage('how-it-works')}>How it works</button>
                </div>
                {failedMessage && (
                  <article className="message message-claimant is-failed">
                    <p className="message-author">{failedMessage.sender}</p>
                    <p>{failedMessage.text}</p>
                    <p className="message-state">{failedMessage.message}</p>
                  </article>
                )}
              </section>
              <div className="entry-secondary-actions">
                <button className="text-link entry-login-link" type="button" onClick={() => setPage(account ? 'account' : 'login')}>
                  {account ? 'My account' : 'Log in'}
                </button>
                {!account && <button className="text-link" type="button" onClick={() => setPage('register')}>Create an account</button>}
                {account && savedReports?.length > 0 && <button className="text-link" type="button" onClick={() => loadSavedReports()} disabled={isBusy}>
                  {status === 'loading-reports' ? 'Loading claims...' : 'Resume a claim'}
                </button>}
              </div>
              {savedReports !== null && (
                <section className="saved-reports" aria-labelledby="saved-reports-title">
                  <h2 id="saved-reports-title">Claims in progress</h2>
                  {savedReports.length === 0 ? (
                    <p>No claims in progress need your attention.</p>
                  ) : (
                    <ul>
                      {savedReports.map((report) => (
                        <li key={report.claim_id}>
                          <div>
                            <strong>{report.incident_type || 'Incident report'}</strong>
                            <span>{report.customer_next_step.summary}</span>
                          </div>
                          <button className="secondary-button" type="button" onClick={() => resumeSavedReport(report.claim_id)} disabled={isBusy}>
                            {status === 'resuming' ? 'Resuming...' : 'Resume claim'}
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </section>
              )}
            </div>
          </section>
        </main>
      ) : (
        <main className={`intake-page ${detailsOpen ? 'details-open' : 'details-closed'}`}>
          <nav className="mobile-intake-tabs" aria-label="Claim workspace sections">
            {[
              ['history', 'History'],
              ['chat', 'Chat'],
              ['details', 'Details'],
            ].map(([view, label]) => (
              <button key={view} type="button" aria-selected={mobileView === view} onClick={() => setMobileView(view)}>
                {label}
              </button>
            ))}
          </nav>
          <aside className={`intake-history mobile-view-${mobileView}`} aria-label="Conversation history">
            <div className="history-actions" aria-label="Claim tools">
              <button type="button" onClick={startNewChat} disabled={isBusy}>New chat</button>
              <button type="button" onClick={() => setWorkspaceView('privacy')}>Privacy policy</button>
              <button type="button" onClick={() => setWorkspaceView('history')}>Claim history</button>
              <button type="button" onClick={() => setWorkspaceView('files')}>Uploaded files</button>
            </div>
            <div className="intake-history-label">Conversation history</div>
            <div className="intake-history-list">
              <button className="intake-history-item is-active" type="button" aria-current="page">
                <span className="intake-history-title">Current claim</span>
                <span className="intake-history-meta">{claim.incident_type || 'New report'} · {claim.claim_id}</span>
              </button>
            </div>
            <div className="intake-history-bottom">
              <button className="intake-profile" type="button" onClick={() => {
                if (account) { setWorkspaceView('account'); setPage('account') }
                else setPage('login')
              }}>
                <span className="intake-profile-avatar">{account?.profile?.display_name?.slice(0, 2).toUpperCase() || 'YU'}</span>
                <span className="intake-profile-copy">
                  <span>{account?.profile?.display_name || 'Log in to save your chat'}</span>
                  <small>{account?.profile?.email || 'Account and preferences'}</small>
                </span>
              </button>
            </div>
          </aside>
          <section className={`conversation-panel mobile-view-${mobileView} ${workspaceView !== 'chat' ? 'is-utility' : ''}`} aria-labelledby="conversation-title">
            <div className="workspace-utility-page" hidden={workspaceView === 'chat'}>
              <button className="back-link" type="button" onClick={() => { setWorkspaceView('chat'); setPage('home') }}>← Back to conversation</button>
              <h1>{workspaceView === 'privacy' ? 'Privacy policy' : workspaceView === 'history' ? 'Claim history' : workspaceView === 'account' ? 'Your account' : 'Uploaded files'}</h1>
              <p>{workspaceView === 'privacy' ? 'We only use the information needed to handle your claim and show you what has been recorded.' : workspaceView === 'history' ? 'Your claim conversations will appear here as they are saved.' : workspaceView === 'account' ? 'Manage your profile and communication preferences.' : 'Files you share for this claim appear here with their upload and processing status.'}</p>
              {workspaceView === 'account' && account && (
                <div className="workspace-account-content">
                  <form className="login-form" onSubmit={saveProfile}>
                    <label htmlFor="workspace-account-name">Display name</label>
                    <input id="workspace-account-name" name="display_name" defaultValue={account.profile.display_name} required />
                    <label htmlFor="workspace-account-email">Email address</label>
                    <input id="workspace-account-email" value={account.profile.email} readOnly />
                    <label htmlFor="workspace-account-phone">Phone</label>
                    <input id="workspace-account-phone" name="phone" defaultValue={account.profile.phone} />
                    <button className="primary-button" disabled={authStatus !== 'idle'}>Save profile</button>
                  </form>
                  <form className="login-form" onSubmit={savePreferences}>
                    <label><input name="email" type="checkbox" defaultChecked={account.preferences.email} /> Email updates</label>
                    <label><input name="sms" type="checkbox" defaultChecked={account.preferences.sms} /> SMS updates</label>
                    <button className="secondary-button" disabled={authStatus !== 'idle'}>Save preferences</button>
                  </form>
                  <button className="secondary-button" type="button" onClick={signOut} disabled={authStatus !== 'idle'}>Log out</button>
                  {authError && <p className="backend-status is-error" role="alert">{authError}</p>}
                </div>
              )}
              {workspaceView === 'files' && (
                evidenceItems.length > 0 ? (
                  <ul className="uploaded-files-list">
                    {evidenceItems.map((item) => (
                      <li key={item.evidence_id} className="uploaded-file-row">
                        <div><strong>{item.original_filename || item.kind}</strong><span>{item.media_type || 'File'} · {item.file_status || item.status}</span></div>
                        <span className="file-status">{evidenceFileStatusLabel(item.file_status, item.status)}</span>
                      </li>
                    ))}
                  </ul>
                ) : attachments.length > 0 ? (
                  <ul className="uploaded-files-list">
                    {attachments.map((item) => (
                      <li key={item.id} className="uploaded-file-row">
                        <div><strong>{item.name}</strong><span>Claim evidence</span></div>
                        <span className="file-status">{item.statusLabel}</span>
                      </li>
                    ))}
                  </ul>
                ) : <p className="empty-details">No files have been uploaded for this claim.</p>
              )}
            </div>
            <div className="conversation-heading">
              <div>
                <div className="claim-status">{claim.incident_type || 'Claim'} · {handoff ? 'Support requested' : 'In progress'}</div>
                <h1 id="conversation-title">{claim.claim_id}</h1>
              </div>
            </div>

            <section
              className="journey-progress"
              aria-label={`Claim progress: Step ${progress.current} of ${progress.total}, ${progress.label}`}
            >
              <div className="journey-progress-heading">
                <span>Step {progress.current} of {progress.total}</span>
                <strong>{progress.label}</strong>
              </div>
              <div className="progress-track" aria-hidden="true">
                <span
                  className="progress-fill"
                  style={{ '--progress-width': `${(progress.current / progress.total) * 100}%` }}
                />
              </div>
              <p>{progress.saved} {progress.saved === 1 ? 'detail' : 'details'} saved from your conversation.</p>
            </section>

            <div className="message-list" aria-live="polite">
              {messages.map((message) => message.actor === 'claimant' ? (
                <article className="msg-user" key={message.message_id}>
                  <div>
                    <div className="user-bubble">{messageText(message)}</div>
                    <div className="msg-meta">{new Date(message.created_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</div>
                  </div>
                </article>
              ) : (
                <article className="msg-agent" key={message.message_id}>
                  <div className="agent-bar" />
                  <div className="agent-body">
                    <div className="agent-label">Claims assistant</div>
                    <div className="agent-text"><p>{messageText(message)}</p><button className="listen-message" type="button" onClick={() => { if (globalThis.speechSynthesis) { globalThis.speechSynthesis.cancel(); globalThis.speechSynthesis.speak(new SpeechSynthesisUtterance(messageText(message))) } }}>Listen</button></div>
                  </div>
                </article>
              ))}
              {status === 'sending' && pendingMessage && (
                <article className="message message-claimant is-pending" aria-label="Message sending">
                  <p className="message-author">You</p>
                  <p>{pendingMessage.text}</p>
                  <p className="message-state">Sending…</p>
                </article>
              )}
              {failedMessage && (
                <article className="message message-claimant is-failed" role="alert">
                  <p className="message-author">{failedMessage.sender}</p>
                  <p>{failedMessage.text}</p>
                  <p className="message-state">{failedMessage.message}</p>
                </article>
              )}
            </div>

            {resumeContext && (
              <section className="resume-summary" aria-labelledby="resume-summary-title">
                <p className="transfer-label">Claim resumed</p>
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
                className={`transfer-state ${isUrgentSupport ? 'is-urgent' : ''}`}
                aria-live="assertive"
                aria-labelledby="transfer-title"
              >
                <p className="transfer-label">
                  {isUrgentSupport ? 'Urgent support' : 'Human support'}
                </p>
                <h2 id="transfer-title">
                  {isUrgentSupport
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
                    <dt>Your claim</dt>
                    <dd>Saved with the details already provided</dd>
                  </div>
                </dl>
                <p>Your message will be saved for Northwind support. You can continue here, or ask for human help again if you need it.</p>
              </section>
            )}

            {handoff?.status === 'in_progress' && (
              <section className="transfer-state" role="status" aria-labelledby="active-support-title">
                <p className="transfer-label">Staff assistance</p>
                <h2 id="active-support-title">You are connected with Northwind</h2>
                <p className="handoff-status">Status: {HANDOFF_STATUS_LABELS[handoff.status]}</p>
                <p>{nextStep?.summary || 'A claims professional is continuing this conversation with you.'}</p>
                <dl>
                  <div>
                    <dt>Conversation</dt>
                    <dd>New staff messages appear here automatically</dd>
                  </div>
                  <div>
                    <dt>Your claim</dt>
                    <dd>Saved with the details already provided</dd>
                  </div>
                </dl>
              </section>
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

            {evidenceSyncNotice && (
              <p className="backend-status" role="status">
                <span className="status-dot" />
                <span>{evidenceSyncNotice}</span>
              </p>
            )}

            <MessageComposer
              draft={draft}
              setDraft={setDraft}
              onSubmit={sendMessage}
              inputLabel={inputLabel}
              busy={isBusy}
              hint={proposedFields.length > 0
                ? 'You can keep describing the incident or correct a detail while these suggestions are waiting for review.'
                : null}
              buttonLabel={status === 'sending' ? 'Sending...' : failedMessage ? 'Retry message' : 'Send'}
              error={error}
              variant="workspace"
              claimType={claimType}
              setClaimType={setClaimType}
              claimTypes={runtimeCapabilities.claim_types}
              models={runtimeCapabilities.models}
              selectedModel={selectedModel}
              setSelectedModel={setSelectedModel}
              attachments={attachments}
              onFileSelected={handleFileSelected}
            />
          </section>

          {!detailsOpen && workspaceView === 'chat' && (
            <button className="details-reopen" type="button" onClick={() => setDetailsOpen(true)} aria-label="Show claim details" title="Show claim details">‹</button>
          )}
          <aside className={`claim-panel intake-details-panel mobile-view-${mobileView} ${detailsOpen && workspaceView === 'chat' ? 'is-open' : 'is-collapsed'} ${workspaceView !== 'chat' ? 'is-hidden' : ''}`} aria-labelledby="claim-details-title">
            <div className="claim-panel-heading">
              <div>
                <p className="eyebrow">Structured report</p>
                <h2 id="claim-details-title">What we have so far</h2>
                <p className="panel-subtitle">Review or correct anything here</p>
              </div>
              <div className="details-panel-actions">
                <span className="revision-label">Revision {claim.revision}</span>
                <button
                  className="details-toggle"
                  type="button"
                  aria-expanded={detailsOpen}
                  aria-controls="claim-details-body"
                  onClick={() => setDetailsOpen((open) => !open)}
                >
                  {detailsOpen ? 'Collapse' : 'Details'}
                </button>
              </div>
            </div>
            <div id="claim-details-body" hidden={!detailsOpen}>
            {dynamicForm && (
              <section className="dynamic-form-summary" aria-labelledby="dynamic-form-title" aria-live="polite">
                <div className="dynamic-form-heading">
                  <div>
                    <p className="eyebrow">Current claim path</p>
                    <h2 id="dynamic-form-title">
                      {dynamicForm.selected_family
                        ? `${dynamicForm.selected_family[0].toUpperCase()}${dynamicForm.selected_family.slice(1)} claim details`
                        : 'Claim details'}
                    </h2>
                  </div>
                  <span className="dynamic-form-revision">Updated with revision {dynamicForm.claim_revision}</span>
                </div>
                {visibleDynamicFields.length === 0 ? (
                  <p className="dynamic-form-empty">No additional details are needed for the current step.</p>
                ) : (
                  <ul className="dynamic-form-fields">
                    {visibleDynamicFields.map((item) => {
                      const storedField = form[item.field_code]
                      return (
                        <li className="dynamic-form-field" key={item.field_code}>
                          <div className="dynamic-form-field-heading">
                            <span>{fieldLabel(item.field_code)}</span>
                            <span className={`dynamic-selection dynamic-selection-${item.selection_state}`}>
                              {dynamicSelectionLabel(item.selection_state)}
                            </span>
                          </div>
                          <p className="dynamic-form-value">
                            {storedField ? fieldValueText(storedField) : dynamicValueLabel(item.value_state)}
                          </p>
                          <p className="dynamic-form-meta">
                            {dynamicValueLabel(item.value_state, storedField)}
                            {storedField?.source ? ` · ${fieldSourceLabel(storedField.source)}` : ''}
                          </p>
                          <p className="dynamic-form-reason">{item.reason}</p>
                        </li>
                      )
                    })}
                  </ul>
                )}
              </section>
            )}
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
              <section className="confirmation-bar" aria-labelledby="confirmation-title">
                <p className="confirmation-kicker">Review before we continue</p>
                <h2 id="confirmation-title">Check these details</h2>
                <ul className="confirmation-list">
                  {proposedFields.map(([fieldCode]) => (
                    <li key={fieldCode}>{fieldLabel(fieldCode)} needs your review.</li>
                  ))}
                </ul>
                <p>Use the conversation to correct anything in your own words, or edit a detail here.</p>
                <button
                  className="primary-button"
                  type="button"
                  onClick={confirmProposedFields}
                  disabled={isBusy}
                >
                  {status === 'confirming' ? 'Confirming...' : 'Confirm details'}
                </button>
              </section>
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
            </div>
          </aside>
        </main>
      )}
    </div>
  )
}
export default App
