import { useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react'
import {
  ApiRequestError,
  acceptClaimAgreement,
  confirmClaimFields,
  createClaim,
  createExternalClaim,
  createPaymentDestination,
  decideExternalServiceOffer,
  grantAssessorConsent,
  getAuthenticatedAccount,
  hasClaimantAccessToken,
  getClaim,
  getClaimMessages,
  getClaimEvidence,
  getRuntimeCapabilities,
  listClaims,
  listPaymentDestinations,
  loginClaimant,
  logoutClaimant,
  pauseClaimSession,
  requestId,
  requestHumanSupport,
  promoteAnonymousClaim,
  requestAssessorRouting,
  registerClaimant,
  requestEvidenceUpload,
  uploadEvidenceContent,
  completeEvidenceUpload,
  resumeClaimSession,
  streamRealtimeEvents,
  submitClaimMessage,
  selectClaimPayoutContact,
  setClaimantAccessToken,
  updateClaimField,
} from './api.js'
import './App.css'
import './styles/frontend-refactor.css'
import MessageComposer from './components/MessageComposer.jsx'
import {
  AgentMessageRow,
  ClaimantMessageAttachments,
  ClaimantMessageRow,
  ConversationStart,
  StaffMessageRow,
} from './components/ConversationMessages.jsx'
import RecordedFactsCard from './components/RecordedFactsCard.jsx'
import { fieldLabel, fieldSourceLabel, fieldStatusLabel, fieldValueText } from './claimFieldPresentation.js'
import { evidenceFileStatusLabel, messageText } from './messagePresentation.js'
import { factCardsByAgentMessage, notedProgress } from './recordedFacts.js'
import { modelAttachmentCompatibility } from './attachmentModelCompatibility.js'
import ExternalServiceAction from './components/ExternalServiceAction.jsx'
import ExternalServicesPage from './components/ExternalServicesPage.jsx'
import EvidenceHistory from './components/EvidenceHistory.jsx'
import ClaimHistory, { ClaimFeatureDirectory } from './components/ClaimHistory.jsx'
import ClaimDocuments from './components/ClaimDocuments.jsx'
import ClaimReviewPanel, {
  ClaimNextStepsPanel,
  ClaimSummaryProgress,
} from './components/ClaimReviewPanel.jsx'
import { claimReviewRequirements } from './claimReviewProjection.js'
import AgreementConfirmationPanel from './components/AgreementConfirmationPanel.jsx'
import PayoutContactPanel from './components/PayoutContactPanel.jsx'
import {
  isDefinitiveSubmissionRefusal,
  submissionFailure,
  submissionReconciliationFailure,
} from './claimSubmissionFeedback.js'
import ClaimAutoFillPanel from './components/ClaimAutoFillPanel.jsx'
import ConversationHistorySidebar from './components/ConversationHistorySidebar.jsx'
import {
  AgentTurnPlaceholder,
} from './components/AgentTurnActivity.jsx'
import { completeTurnProgress, reduceTurnProgress } from './agentTurnProgress.js'
import UserProfile from './components/UserProfile.jsx'
import PrivacyPage from './privacy/PrivacyPage.jsx'
import './styles/profile-shell.css'
import './styles/profile-records.css'
import './styles/profile-assets.css'
import './styles/profile-responsive.css'
import './styles/claim-history.css'
import { profilePathForSection, profileSectionFromPath } from './profileRoutes.js'
import { historyClaimIdFromPath, pageForPath, routeForPage as routeForAppPage } from './appRoutes.js'
import { claimHeading, claimStartedLabel } from './claimHeading.js'
import { claimantModelChoices } from './modelProducts.js'
import { captureComposerRect, playComposerHandoff } from './composerHandoff.js'
import ClaimEntryPage from './components/ClaimEntryPage.jsx'
import ClaimantAvatar from './components/ClaimantAvatar.jsx'
import { buildConversationTimeline, mergeMessagesById, orderMessages } from './conversationTimeline.js'
import useProfileController from './profile/useProfileController.js'
import useClaimAutoFillEditor from './profile/useClaimAutoFillEditor.js'
import { WORKBENCH_URL } from './runtimeConfig.js'
import {
  forgetAnonymousConversation,
  readAnonymousConversationHistory,
  rememberAnonymousConversation,
} from './anonymousConversationHistory.js'
import {
  ConversationActionCard,
  ConversationEvent,
  ConversationInfoPanel,
} from './components/ConversationContext.jsx'

const PERMANENT_ANONYMOUS_RESUME_FAILURES = new Set([
  'AUTHENTICATION_REQUIRED',
  'ACCESS_DENIED',
  'RESOURCE_NOT_FOUND',
  'INVALID_STATE_TRANSITION',
])

function isPermanentAnonymousResumeFailure(requestError) {
  return requestError instanceof ApiRequestError
    && (
      PERMANENT_ANONYMOUS_RESUME_FAILURES.has(requestError.code)
      || [401, 403, 404].includes(requestError.status)
    )
}

const INPUT_LABELS = {
  describe_incident: 'Incident description',
  provide_incident_location: 'Incident location',
  describe_loss: 'Damage or loss',
}

const SUPPORT_HANDOFF_TYPES = new Set(['human_support', 'urgent_support'])
const PROFILE_NAME_PREVIEW_LENGTH = 14
const PROFILE_EMAIL_PREVIEW_LENGTH = 17
const MIDDLE_ELLIPSIS_SEPARATORS = new Set(['.', '-', '_'])

function middleEllipsis(value, maxLength) {
  const characters = Array.from(value)
  if (characters.length <= maxLength) return value

  const visibleCharacters = maxLength - 1
  const startLength = Math.ceil(visibleCharacters / 2)
  const endLength = Math.floor(visibleCharacters / 2)
  const start = characters.slice(0, startLength)
  const end = characters.slice(-endLength)
  while (MIDDLE_ELLIPSIS_SEPARATORS.has(start.at(-1))) start.pop()
  while (MIDDLE_ELLIPSIS_SEPARATORS.has(end[0])) end.shift()
  return `${start.join('')}…${end.join('')}`
}

function middleEllipsisLayoutParts(value, maxLength) {
  const characters = Array.from(value)
  if (characters.length <= maxLength) {
    return { start: value, end: '', truncated: false }
  }

  const endLength = Math.floor((maxLength - 1) / 2)
  return {
    start: characters.slice(0, -endLength).join(''),
    end: characters.slice(-endLength).join(''),
    truncated: true,
  }
}

function assistancePresentation({ handoff, nextStep, requesting, reviewingReply, completed }) {
  if (requesting || ['requested', 'queued'].includes(handoff?.status)) {
    return {
      key: 'waiting',
      title: 'Waiting for staff',
      description: 'Your request has been sent. You can continue adding information while you wait.',
    }
  }
  if (completed) {
    return {
      key: 'completed',
      title: 'Staff assistance completed',
      description: nextStep?.responsible_party === 'claimant'
        ? 'You can continue your claim below.'
        : 'No action needed from you right now.',
    }
  }
  if (handoff && nextStep?.responsible_party === 'claimant' && !reviewingReply) {
    return {
      key: 'response_needed',
      title: 'Your response is needed',
      description: 'Northwind staff has asked for more information.',
    }
  }
  if (handoff && reviewingReply) {
    return {
      key: 'reply_sent',
      title: 'Your reply was sent',
      description: 'Waiting for the next claim update.',
    }
  }
  if (handoff?.status === 'accepted') {
    return {
      key: 'staff_assistance_accepted',
      title: 'Staff assistance accepted',
      description: 'Northwind has accepted your assistance request.',
    }
  }
  if (handoff?.status === 'in_progress') {
    return {
      key: 'staff_assistance_in_progress',
      title: 'Staff assistance in progress',
      description: 'Northwind reports that your assistance request is in progress.',
    }
  }
  return null
}

const CLAIMANT_ACTION_KINDS = Object.freeze({
  'claimant.create_claim': 'create-claim',
  'claimant.review_details': 'review-details',
  'claimant.review_payout_contact': 'payout-contact',
  'claimant.review_agreement': 'review-agreement',
  'claimant.request_assessment': 'external-service',
  'claimant.retry_assessment': 'external-service',
  'claimant.track_assessment': 'external-service',
  'claimant.await_staff_review': 'external-service',
  'claimant.await_reconciliation': 'external-service',
})
const REQUESTABLE_EXTERNAL_ACTIONS = new Set([
  'claimant.request_assessment',
  'claimant.retry_assessment',
])

function conversationActionFromProjection(claim) {
  const projection = claim?.primary_action
  if (!projection || Number(projection.claim_revision) !== Number(claim?.revision)) return null

  const kind = CLAIMANT_ACTION_KINDS[projection.action_code]
  if (!kind || (kind !== 'external-service' && !projection.available)) return null

  return {
    kind,
    identity: projection.action_id,
    requiredItems: Array.isArray(projection.required_inputs)
      ? projection.required_inputs
      : [],
  }
}

function isSendableComposerAttachment(attachment) {
  if (attachment.status === 'staged') {
    return Boolean(attachment.stagedFile && attachment.uploadAttempt)
  }
  return (
    (attachment.status === 'uploaded' || attachment.status === 'processing')
    && Boolean(attachment.evidenceId || attachment.uploadAttempt?.evidenceId)
  )
}

function attachmentSubmissionSignature(text, attachments, modelProfileId) {
  return JSON.stringify({
    text,
    modelProfileId,
    attachments: attachments.map((attachment) => (
      attachment.evidenceId
      || attachment.uploadAttempt?.evidenceId
      || attachment.id
      || attachment.name
    )),
  })
}

async function fetchClaimHistory({ signal } = {}) {
  const claimsById = new Map()
  const seenCursors = new Set()
  let cursor

  do {
    const response = await listClaims({ cursor, signal })
    for (const item of response.items) claimsById.set(item.claim_id, item)
    const nextCursor = response.page?.next_cursor || null
    if (nextCursor && seenCursors.has(nextCursor)) {
      throw new ApiRequestError(
        'Northwind returned an invalid Claim-history page. Try loading the history again.',
        { code: 'INVALID_PAGINATION' },
      )
    }
    if (nextCursor) seenCursors.add(nextCursor)
    cursor = nextCursor
  } while (cursor)

  return [...claimsById.values()]
}

function mergeFields(current, changes) {
  return changes.reduce(
    (fields, change) => ({ ...fields, [change.field_code]: change.field }),
    current,
  )
}

function mergeContentsItems(current, changes) {
  const incomingById = new Map(changes.map((item) => [item.item_id, item]))
  const merged = current.map((item) => incomingById.get(item.item_id) || item)
  const currentIds = new Set(current.map((item) => item.item_id))
  return [
    ...merged,
    ...changes.filter((item) => !currentIds.has(item.item_id)),
  ]
}

function App() {
  const initialProfileSection = profileSectionFromPath(globalThis.location?.pathname)
  const initialDraftWorkspaceActive = globalThis.location?.pathname === '/claims/new'
  const initialPage = pageForPath(globalThis.location?.pathname || '/', {
    authenticated: hasClaimantAccessToken(),
  })
  const [page, setPageState] = useState(initialPage)
  const [profileSection, setProfileSection] = useState(initialProfileSection)
  const [account, setAccount] = useState(null)
  const [authStatus, setAuthStatus] = useState('idle')
  const [authError, setAuthError] = useState('')
  const [paymentDestinationState, setPaymentDestinationState] = useState({
    claimId: null,
    status: 'idle',
    items: [],
    error: '',
  })
  const [claimType, setClaimType] = useState('')
  const [draft, setDraft] = useState('')
  const [claim, setClaim] = useState(null)
  const [sessionId, setSessionId] = useState(null)
  const [messages, setMessages] = useState([])
  const [form, setForm] = useState({})
  const [contentsItems, setContentsItems] = useState([])
  const [dynamicForm, setDynamicForm] = useState(null)
  const [nextStep, setNextStep] = useState(null)
  const [status, setStatus] = useState('idle')
  const [autoFillBusy, setAutoFillBusy] = useState(false)
  const [error, setError] = useState('')
  const [agreementSubmissionError, setAgreementSubmissionError] = useState(null)
  const [editingField, setEditingField] = useState(null)
  const [editValue, setEditValue] = useState('')
  const [handoff, setHandoff] = useState(null)
  const [assistanceReplyReview, setAssistanceReplyReview] = useState(null)
  const [claimHistory, setClaimHistory] = useState(() => (
    hasClaimantAccessToken() ? null : readAnonymousConversationHistory()
  ))
  const [claimHistoryError, setClaimHistoryError] = useState('')
  const [conversationHistoryOpen, setConversationHistoryOpen] = useState(false)
  const [selectedHistoryClaimId, setSelectedHistoryClaimId] = useState(() => (
    historyClaimIdFromPath(globalThis.location?.pathname)
  ))
  const [detailsOpen, setDetailsOpen] = useState(true)
  const [detailsTab, setDetailsTab] = useState('summary')
  const [mobileView, setMobileView] = useState('chat')
  const [workspaceView, setWorkspaceView] = useState('chat')
  const [workspaceActive, setWorkspaceActive] = useState(initialDraftWorkspaceActive)
  const [draftWorkspaceActive, setDraftWorkspaceActive] = useState(initialDraftWorkspaceActive)
  const [profileReturnClaimId, setProfileReturnClaimId] = useState(null)
  const profileController = useProfileController({
    account,
    setAccount,
    enabled: page === 'account',
  })
  const autoFillEditor = useClaimAutoFillEditor({
    account,
    onSave: profileController.saveAutoFillPreferences,
  })
  const [runtimeCapabilities, setRuntimeCapabilities] = useState({
    claim_types: ['motor', 'home', 'contents'],
    models: [],
    default_model_profile_id: null,
  })
  const [selectedModel, setSelectedModel] = useState('')
  const [attachments, setAttachments] = useState([])
  const [evidenceItems, setEvidenceItems] = useState([])
  const [evidenceLoadStatus, setEvidenceLoadStatus] = useState('idle')
  const [evidenceSyncNotice, setEvidenceSyncNotice] = useState('')
  const [realtimeHealth, setRealtimeHealth] = useState('healthy')
  const [resumeContext, setResumeContext] = useState(null)
  const [expandedConversationPanels, setExpandedConversationPanels] = useState({})
  const [externalCapabilitiesOpen, setExternalCapabilitiesOpen] = useState(false)
  const [externalServiceInteraction, setExternalServiceInteraction] = useState({
    claimId: null,
    consentChecked: false,
    error: null,
  })
  const [offerConsentChecks, setOfferConsentChecks] = useState({})
  const [offerErrors, setOfferErrors] = useState({})
  const [failedMessage, setFailedMessage] = useState(null)
  const [arrivingFromEntry, setArrivingFromEntry] = useState(false)
  const composerHandoffFrom = useRef(null)
  // A failed retry of an already saved message belongs on that message, not as a new
  // unconfirmed bubble at the end of the conversation (#1025).
  const [recoveryFailure, setRecoveryFailure] = useState(null)
  const [pendingMessage, setPendingMessage] = useState(null)
  const [activeTurnProgress, setActiveTurnProgress] = useState(null)
  const [messageActivities, setMessageActivities] = useState({})
  const activeTurnProgressRef = useRef(null)
  const pendingSubmission = useRef(null)
  const pendingConfirmation = useRef(null)
  const pendingSupportRequest = useRef(null)
  const pendingAgreementAcceptance = useRef(null)
  const pendingClaimCreation = useRef(null)
  const pendingExternalService = useRef(null)
  const pendingSessionPause = useRef(null)
  const deferredSessionPauses = useRef(new Map())
  const sessionPauseGeneration = useRef(0)
  const pendingMessageReconciliation = useRef(null)
  const messageReconciliationGeneration = useRef(0)
  const workspaceGeneration = useRef(0)
  const claimantIdentityGeneration = useRef(0)
  const latestRevision = useRef(0)
  const latestRevisionClaimId = useRef(null)
  const activeClaimRef = useRef(claim)
  const activeSessionIdRef = useRef(sessionId)
  const accountRef = useRef(account)
  const workspaceViewRef = useRef(workspaceView)
  const realtimeCursor = useRef(null)
  const realtimeSeenEventIds = useRef(new Set())
  const messagesRequestGeneration = useRef(0)
  const claimTransitionRef = useRef(null)
  const latestEvidenceRevision = useRef(0)
  const latestEvidenceItems = useRef([])
  const evidenceHasLocalMutation = useRef(false)
  const evidenceClaimId = useRef(null)
  const evidenceUploadControllers = useRef(new Map())
  const evidencePreviewFiles = useRef(new Map())
  const attachmentsRef = useRef(attachments)
  const cancelledAttachmentIds = useRef(new Set())
  const dismissedComposerEvidenceIds = useRef(new Set())
  const detailsTabRefs = useRef({})
  const conversationPanelRef = useRef(null)
  const messageListRef = useRef(null)
  const externalCapabilitiesDialogRef = useRef(null)
  const externalCapabilitiesHeadingRef = useRef(null)
  const externalCapabilitiesTriggerRef = useRef(null)
  const restoreCapabilityTriggerFocus = useRef(false)
  const followLatestMessages = useRef(true)
  const forceLatestMessages = useRef(false)
  const confirmedClaimProjections = useRef(new Map())
  const messagesRef = useRef(messages)
  useEffect(() => {
    pendingAgreementAcceptance.current = null
    pendingClaimCreation.current = null
  }, [claim?.claim_id])

  activeClaimRef.current = claim
  activeSessionIdRef.current = sessionId
  accountRef.current = account
  workspaceViewRef.current = workspaceView
  attachmentsRef.current = attachments
  messagesRef.current = messages
  const realtimePrincipal = account ? 'authenticated' : claim?.claim_id ? 'anonymous' : 'none'
  const realtimeSyncNotice = realtimeHealth === 'stale'
    ? 'Live updates need to be resynchronised. Some claim information may be out of date while we restore the latest status.'
    : realtimeHealth === 'reconnecting'
      ? 'Live updates are reconnecting. Some claim information may be out of date while we restore the latest status.'
      : ''
  const hasStarted = claim !== null
  const isWorkspaceActive = workspaceActive && (hasStarted || draftWorkspaceActive)
  const savedReports = claimHistory === null
    ? null
    : claimHistory
  const conversationReports = claim
    ? claimHistory?.some((item) => item.claim_id === claim.claim_id)
      ? claimHistory
        .map((item) => item.claim_id === claim.claim_id ? claim : item)
      : [claim, ...(savedReports || [])]
    : (savedReports || [])
  const homepageConversationReports = claim ? conversationReports : (savedReports || [])
  const selectedHistoryClaim = claimHistory?.find((item) => item.claim_id === selectedHistoryClaimId)
    || (claim?.claim_id === selectedHistoryClaimId ? claim : null)
  function currentClaimantIdentityKey() {
    const authenticated = hasClaimantAccessToken()
    let identityKey = `account:${accountRef.current?.customer_id || ''}`
    if (!authenticated) {
      try {
        identityKey = `anonymous:${globalThis.sessionStorage?.getItem('northwind.anonymousSession') || ''}`
      } catch { identityKey = 'anonymous:' }
    }
    return [claimantIdentityGeneration.current, identityKey].join(':')
  }

  function currentPauseContextKey() {
    return [
      currentClaimantIdentityKey(),
      globalThis.location?.pathname || '/',
      workspaceViewRef.current,
      activeClaimRef.current?.claim_id || '',
      activeSessionIdRef.current || '',
    ].join(':')
  }

  function sessionPauseRecoveryKey(identityKey, claimId) {
    return `${identityKey}:${claimId}`
  }

  function isSessionPauseIdentityCurrent(operation) {
    return operation?.identityKey === currentClaimantIdentityKey()
  }

  function rememberDeferredSessionPause(operation) {
    if (!isSessionPauseIdentityCurrent(operation)) return false
    const existing = deferredSessionPauses.current.get(operation.recoveryKey)
    if (existing && existing !== operation && existing.generation > operation.generation) return false
    deferredSessionPauses.current.set(operation.recoveryKey, operation)
    return true
  }

  function forgetDeferredSessionPause(operation) {
    if (deferredSessionPauses.current.get(operation?.recoveryKey) === operation) {
      deferredSessionPauses.current.delete(operation.recoveryKey)
    }
  }

  function isSessionPauseCurrent(operation) {
    return operation
      && pendingSessionPause.current === operation
      && sessionPauseGeneration.current === operation.generation
      && currentPauseContextKey() === operation.contextKey
  }

  function beginMessageReconciliation(currentClaim, currentSessionId) {
    messageReconciliationGeneration.current += 1
    const operation = {
      generation: messageReconciliationGeneration.current,
      workspaceGeneration: workspaceGeneration.current,
      identityKey: currentClaimantIdentityKey(),
      claimId: currentClaim?.claim_id || null,
      sessionId: currentSessionId || null,
      contextKey: currentPauseContextKey(),
    }
    pendingMessageReconciliation.current = operation
    return operation
  }

  function isMessageReconciliationCurrent(operation) {
    return operation
      && pendingMessageReconciliation.current === operation
      && messageReconciliationGeneration.current === operation.generation
      && workspaceGeneration.current === operation.workspaceGeneration
      && currentClaimantIdentityKey() === operation.identityKey
      && activeClaimRef.current?.claim_id === operation.claimId
      && activeSessionIdRef.current === operation.sessionId
      && currentPauseContextKey() === operation.contextKey
  }

  function finishMessageReconciliation(operation) {
    if (pendingMessageReconciliation.current === operation) {
      pendingMessageReconciliation.current = null
    }
  }

  function invalidateSessionPause({ identityChanged = false } = {}) {
    const operation = pendingSessionPause.current
    const hadPendingPause = Boolean(operation)
    if (identityChanged) {
      claimantIdentityGeneration.current += 1
      deferredSessionPauses.current.clear()
      messageReconciliationGeneration.current += 1
      pendingMessageReconciliation.current = null
      pendingSubmission.current = null
    } else if (operation) {
      rememberDeferredSessionPause(operation)
    }
    sessionPauseGeneration.current += 1
    pendingSessionPause.current = null
    if (hadPendingPause) setStatus((current) => current === 'pausing-session' ? 'idle' : current)
  }

  useEffect(() => {
    workspaceGeneration.current += 1
    const operation = pendingSessionPause.current
    if (operation && !isSessionPauseCurrent(operation)) invalidateSessionPause()
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account?.customer_id, claim?.claim_id, draftWorkspaceActive, page, sessionId, workspaceActive, workspaceView])

  function rememberClaimInHistory(createdClaim) {
    if (!hasClaimantAccessToken()) {
      setClaimHistory(rememberAnonymousConversation(createdClaim))
      setClaimHistoryError('')
      return
    }
    confirmedClaimProjections.current.set(createdClaim.claim_id, createdClaim)
    setClaimHistory((current) => [
      createdClaim,
      ...(current || []).filter((item) => item.claim_id !== createdClaim.claim_id),
    ])
    setClaimHistoryError('')
  }

  function replaceClaimHistory(items) {
    const merged = new Map(items.map((item) => [item.claim_id, item]))
    for (const [claimId, createdClaim] of confirmedClaimProjections.current) {
      if (!merged.has(claimId)) merged.set(claimId, createdClaim)
    }
    setClaimHistory([...merged.values()])
  }

  useEffect(() => {
    if (!hasClaimantAccessToken()) return
    getAuthenticatedAccount()
      .then((currentAccount) => setAccount(currentAccount))
      .catch(() => {
        setClaimantAccessToken(null)
        setClaimHistory(readAnonymousConversationHistory())
        if (
          ['/profile', '/account', '/files'].includes(globalThis.location?.pathname)
          || globalThis.location?.pathname?.startsWith('/profile/')
          || globalThis.location?.pathname?.startsWith('/account/claims')
        ) {
          setPageState('login')
          globalThis.history?.replaceState({ northwindRoute: 'login' }, '', '/auth/login')
        }
      })
  }, [])

  useEffect(() => {
    if (account && (page === 'login' || page === 'register')) {
      setPage('home', { replace: true })
    }
  // setPage is a stable local navigation helper; keep this guard tied to auth state.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account, page])

  useEffect(() => {
    if (isWorkspaceActive || page !== 'home') setConversationHistoryOpen(false)
  }, [isWorkspaceActive, page])

  useEffect(() => {
    if (
      !conversationHistoryOpen
      || !account
      || claimHistory !== null
      || claimHistoryError
      || status === 'loading-reports'
    ) return
    loadSavedReports().catch(() => {})
  // loadSavedReports is a local command; this effect reacts only to sidebar/data state.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [account, claimHistory, claimHistoryError, conversationHistoryOpen, status])

  useEffect(() => {
    if (conversationPanelRef.current) conversationPanelRef.current.scrollTop = 0
  }, [workspaceView])

  useLayoutEffect(() => {
    if (!isWorkspaceActive) return
    const fromRect = composerHandoffFrom.current
    composerHandoffFrom.current = null
    playComposerHandoff(conversationPanelRef.current?.querySelector('.workspace-composer'), fromRect)
  }, [isWorkspaceActive])

  const claimantModels = useMemo(() => claimantModelChoices(runtimeCapabilities.models, {
    selectedModelId: selectedModel,
    defaultModelId: runtimeCapabilities.default_model_profile_id,
  }), [runtimeCapabilities, selectedModel])

  function routeForPage(nextPage) {
    return routeForAppPage(nextPage, {
      profileSection,
      historyClaimId: selectedHistoryClaimId,
      workspaceActive: isWorkspaceActive,
      draftWorkspace: draftWorkspaceActive,
      claimId: claim?.claim_id,
    })
  }

  function setPage(nextPage, { replace = false } = {}) {
    setProfileReturnClaimId(null)
    setPageState(nextPage)
    if (nextPage === 'account') setProfileSection(null)
    const nextPath = nextPage === 'account' ? '/profile' : routeForPage(nextPage)
    if (globalThis.location?.pathname !== nextPath) {
      globalThis.history?.[replace ? 'replaceState' : 'pushState']({ northwindRoute: nextPage }, '', nextPath)
    }
  }

  useEffect(() => {
    const onPopState = () => {
      const path = globalThis.location?.pathname || '/'
      const nextProfileSection = profileSectionFromPath(path)
      const nextPage = pageForPath(path, { authenticated: Boolean(account) })
      const opensDraftWorkspace = path === '/claims/new'
      setDraftWorkspaceActive(opensDraftWorkspace)
      setWorkspaceActive(opensDraftWorkspace || (path.startsWith('/claims/') && Boolean(claim)))
      setProfileReturnClaimId(
        nextPage === 'account' ? globalThis.history?.state?.profileReturnClaimId || null : null,
      )
      setProfileSection(nextProfileSection)
      setSelectedHistoryClaimId(historyClaimIdFromPath(path))
      setPageState(nextPage)
      const canonicalPath = ['claim-history', 'claim-features', 'claim-evidence'].includes(nextPage)
        ? path
        : nextPage === 'account'
          ? profilePathForSection(nextProfileSection)
          : nextPage === 'home' && path === '/claims/new'
            ? '/claims/new'
            : nextPage === 'home' && path.startsWith('/claims/') && claim?.claim_id
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
    const expectedPath = routeForPage(page)
    if (globalThis.location?.pathname !== expectedPath) {
      globalThis.history?.replaceState({ northwindRoute: page }, '', expectedPath)
    }
  // routeForPage reads exactly the route state listed here.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [draftWorkspaceActive, isWorkspaceActive, page, claim?.claim_id, profileSection, selectedHistoryClaimId])

  const claimOperationBusy = [
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
    'saving-payment-destination',
    'saving-payout-contact',
    'pausing-session',
  ].includes(status)
  const isBusy = claimOperationBusy || autoFillBusy
  const proposedFields = useMemo(
    () => Object.entries(form).filter(([, field]) => field.status === 'proposed'),
    [form],
  )
  const proposedContentsItems = useMemo(
    () => contentsItems.filter((item) => item.status === 'proposed'),
    [contentsItems],
  )
  const inputLabel = INPUT_LABELS[nextStep?.status] || 'Add more information'
  const factCards = useMemo(() => factCardsByAgentMessage(messages, form), [messages, form])
  const latestFactCardId = [...factCards.keys()].at(-1) || null
  const recordedProgress = useMemo(() => notedProgress(dynamicForm), [dynamicForm])
  const serviceConsentChecked = externalServiceInteraction.claimId === claim?.claim_id
    && externalServiceInteraction.consentChecked
  const serviceError = externalServiceInteraction.claimId === claim?.claim_id
    ? externalServiceInteraction.error
    : null
  const reviewingAssistanceReply = Boolean(
    assistanceReplyReview
    && assistanceReplyReview.claimId === claim?.claim_id
    && assistanceReplyReview.handoffId === handoff?.handoff_id,
  )
  const completedAssistance = !handoff
    && claim?.resolved_support_handoff?.status === 'resolved'
    && SUPPORT_HANDOFF_TYPES.has(claim.resolved_support_handoff.type)
    ? claim.resolved_support_handoff
    : null
  const assistanceState = useMemo(() => assistancePresentation({
    handoff,
    nextStep,
    requesting: status === 'requesting-support',
    reviewingReply: reviewingAssistanceReply,
    completed: Boolean(completedAssistance),
  }), [
    completedAssistance,
    handoff,
    nextStep,
    reviewingAssistanceReply,
    status,
  ])
  const conversationTimeline = useMemo(
    () => buildConversationTimeline(messages, resumeContext),
    [messages, resumeContext],
  )
  const isNewConversationEmpty = !claim
    && conversationTimeline.length === 0
    && !pendingMessage
    && !failedMessage
  const lastAgentMessageId = useMemo(() => (
    [...conversationTimeline]
      .reverse()
      .find((item) => item.kind === 'message' && item.message.actor === 'agent')
      ?.message.message_id || null
  ), [conversationTimeline])
  const conversationAction = useMemo(
    () => conversationActionFromProjection(claim),
    [claim],
  )
  const messageExternalServiceActions = useMemo(
    () => messages.flatMap((message) => (
      Array.isArray(message.message_actions) ? message.message_actions : []
    )),
    [messages],
  )
  const conversationActionKind = conversationAction?.kind || null
  // The latest "Just noted" card replaces the "Review claim details" prompt only
  // when every detail the prompt asks about is on that open card. Otherwise the
  // prompt stays: details on folded earlier cards, contents items, a fact with
  // two conflicting answers, or a whole-claim summary the claimant is checking.
  const latestCardCodes = new Set((factCards.get(latestFactCardId) || []).map((fact) => fact.fieldCode))
  const visibleConversationActionKind = (
    conversationActionKind === 'review-details'
    && conversationAction.requiredItems.length > 0
    && conversationAction.requiredItems.every((fieldCode) => latestCardCodes.has(fieldCode))
  )
    ? null
    : conversationActionKind
  const accountCustomerId = account?.customer_id || null
  const accountRevision = account?.revision || null

  useEffect(() => {
    if (conversationActionKind !== 'payout-contact' || !claim?.claim_id) {
      setPaymentDestinationState({
        claimId: null,
        status: 'idle',
        items: [],
        error: '',
      })
      return undefined
    }
    if (!accountCustomerId) {
      setPaymentDestinationState({
        claimId: claim.claim_id,
        status: 'idle',
        items: [],
        error: '',
      })
      return undefined
    }

    let active = true
    const controller = new AbortController()
    setPaymentDestinationState((current) => ({
      claimId: claim.claim_id,
      status: 'loading',
      items: current.claimId === claim.claim_id ? current.items : [],
      error: '',
    }))
    Promise.all([
      getAuthenticatedAccount(),
      listPaymentDestinations({ limit: 100, signal: controller.signal }),
    ])
      .then(([currentAccount, destinations]) => {
        if (!active) return
        setAccount(currentAccount)
        setPaymentDestinationState({
          claimId: claim.claim_id,
          status: 'ready',
          items: destinations.items || [],
          error: '',
        })
      })
      .catch((requestError) => {
        if (!active || requestError?.name === 'AbortError') return
        setPaymentDestinationState({
          claimId: claim.claim_id,
          status: 'error',
          items: [],
          error: requestError.message || 'Payout details could not be loaded.',
        })
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [accountCustomerId, accountRevision, claim?.claim_id, conversationActionKind])
  useEffect(() => {
    const dialog = externalCapabilitiesDialogRef.current
    if (!dialog) return
    if (externalCapabilitiesOpen) {
      if (!dialog.open) {
        if (typeof dialog.showModal === 'function') dialog.showModal()
        else dialog.setAttribute('open', '')
      }
      globalThis.requestAnimationFrame(() => externalCapabilitiesHeadingRef.current?.focus())
      return
    }
    if (dialog.open) {
      if (typeof dialog.close === 'function') dialog.close()
      else dialog.removeAttribute('open')
    }
    if (restoreCapabilityTriggerFocus.current) {
      restoreCapabilityTriggerFocus.current = false
      globalThis.requestAnimationFrame(() => {
        const trigger = externalCapabilitiesTriggerRef.current
        const focusTarget = trigger && !trigger.closest('[hidden]')
          ? trigger
          : detailsTabRefs.current.documents
        focusTarget?.focus()
      })
    }
  }, [externalCapabilitiesOpen])

  useEffect(() => {
    followLatestMessages.current = true
    forceLatestMessages.current = true
  }, [claim?.claim_id])

  useEffect(() => {
    const messageList = messageListRef.current
    if (!messageList || !isWorkspaceActive || workspaceView !== 'chat') return
    if (isNewConversationEmpty) {
      messageList.scrollTop = 0
      followLatestMessages.current = true
      forceLatestMessages.current = false
      return
    }
    if (!followLatestMessages.current && !forceLatestMessages.current) return
    messageList.scrollTop = messageList.scrollHeight
    followLatestMessages.current = true
    forceLatestMessages.current = false
  }, [
    assistanceState,
    attachments,
    claim?.external_claim,
    conversationActionKind,
    conversationTimeline,
    draft,
    error,
    evidenceSyncNotice,
    failedMessage,
    isNewConversationEmpty,
    isWorkspaceActive,
    pendingMessage,
    selectedModel,
    status,
    workspaceView,
  ])

  useEffect(() => {
    setAssistanceReplyReview((current) => {
      if (!current) return current
      if (
        current.claimId !== claim?.claim_id
        || current.handoffId !== handoff?.handoff_id
      ) return null
      if (!current.messageId) return current
      const replyIndex = messages.findIndex((message) => message.message_id === current.messageId)
      if (replyIndex < 0) return current
      return messages.slice(replyIndex + 1).some((message) => message.actor === 'staff')
        ? null
        : current
    })
  }, [claim?.claim_id, handoff?.handoff_id, messages])

  function rememberClaimRevision(revision) {
    const numericRevision = Number(revision || 0)
    latestRevision.current = Math.max(latestRevision.current, numericRevision)
    return numericRevision
  }

  function setClaimRevision(revision, primaryAction = null) {
    const numericRevision = rememberClaimRevision(revision)
    setClaim((current) => current
      ? {
        ...current,
        revision: Math.max(Number(current.revision || 0), numericRevision),
        ...(Number(primaryAction?.claim_revision) === numericRevision
          ? { primary_action: primaryAction }
          : {}),
      }
      : current)
  }

  function currentTurnRevision(turn) {
    return turn.current_claim_revision ?? turn.claim_revision
  }

  function beginMessagesReadback() {
    messagesRequestGeneration.current += 1
    return messagesRequestGeneration.current
  }

  function commitMessages(nextMessages) {
    messagesRequestGeneration.current += 1
    setMessages(typeof nextMessages === 'function'
      ? (current) => orderMessages(nextMessages(current))
      : orderMessages(nextMessages))
  }

  function applyMessagesReadback(items, { generation, claimId, sessionId }) {
    if (
      generation !== messagesRequestGeneration.current
      || activeClaimRef.current?.claim_id !== claimId
      || activeSessionIdRef.current !== sessionId
    ) return false
    setMessages(orderMessages(items))
    return true
  }

  function beginClaimTransition(claimId) {
    let resolve
    const completion = new Promise((next) => { resolve = next })
    const transition = { claimId, completion, resolve }
    claimTransitionRef.current = transition
    return transition
  }

  function finishClaimTransition(transition) {
    if (!transition) return
    if (claimTransitionRef.current === transition) {
      claimTransitionRef.current = null
    }
    transition.resolve()
  }

  function replaceActiveClaimContext(currentClaim, currentSessionId, { preserveSessionPause = false } = {}) {
    if (!preserveSessionPause) invalidateSessionPause()
    activeClaimRef.current = currentClaim
    activeSessionIdRef.current = currentSessionId
    latestRevisionClaimId.current = currentClaim?.claim_id || null
    latestRevision.current = Number(currentClaim?.revision || 0)
    setDraftWorkspaceActive(false)
    setClaim(currentClaim)
    setSessionId(currentSessionId)
  }

  function applyClaimSnapshot(currentClaim, { minimumRevision = 0 } = {}) {
    if (activeClaimRef.current?.claim_id !== currentClaim?.claim_id) return false
    const responseRevision = Number(currentClaim?.revision || 0)
    const minimumAcceptedRevision = Math.max(
      Number(activeClaimRef.current?.revision || 0),
      latestRevision.current,
      Number(minimumRevision || 0),
    )
    if (responseRevision < minimumAcceptedRevision) return false
    rememberClaimRevision(responseRevision)
    activeClaimRef.current = currentClaim
    setClaim(currentClaim)
    setForm(currentClaim.form)
    setContentsItems(currentClaim.contents_items || [])
    setDynamicForm(currentClaim.dynamic_form || null)
    setNextStep(currentClaim.customer_next_step)
    setHandoff(currentClaim.handoff || null)
    return true
  }

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
      mediaType: evidence.media_type,
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

  function linkedEvidenceIds() {
    const linked = new Set()
    for (const item of messagesRef.current) {
      for (const evidenceId of item.evidence_refs || []) linked.add(evidenceId)
    }
    return linked
  }

  function syncEvidenceProjection(response) {
    const responseRevision = Number(response.revision || 0)
    const currentClaimRevision = Math.max(Number(activeClaimRef.current?.revision || 0), latestRevision.current)
    const minimumRevision = Math.max(latestEvidenceRevision.current, currentClaimRevision)
    if (responseRevision < minimumRevision) return false
    if (!response.items?.length && (latestEvidenceItems.current.length || evidenceHasLocalMutation.current)) return false
    latestEvidenceRevision.current = Math.max(latestEvidenceRevision.current, responseRevision)
    const items = response.items || []
    latestEvidenceItems.current = items
    setEvidenceItems(items)
    setClaimRevision(responseRevision)
    setAttachments((current) => {
      const currentByEvidenceId = new Map(
        current.filter((item) => item.evidenceId).map((item) => [item.evidenceId, item]),
      )
      if (items.length === 0 && current.some((item) => item.status === 'uploading' || item.retry || item.retryFile)) {
        return current
      }
      // Runtime also tracks bookkeeping placeholders for documents the
      // claimant does not have yet (file_status "not_available"): a police
      // report the reference number is still awaited for, a repair quote
      // nobody has requested. They carry no real file, so they must never
      // enter the composer tray as if ready to ride the next message; the
      // "Next steps" is where a claimant sees those.
      const hasRealContent = (item) => (item.file_status || item.status) !== 'not_available'
      if (current.some((item) => item.status === 'uploading')) {
        return current.map((item) => {
          const evidence = items.find((candidate) => candidate.evidence_id === item.evidenceId)
          return evidence && hasRealContent(evidence) ? attachmentForEvidence(evidence, item) : item
        })
      }
      // Evidence already carried by a message in this conversation is
      // historical: it already rode a send, so it must never resurface in
      // the composer tray and auto-attach itself to an unrelated future
      // message just because it is still visible in the Claim Evidence
      // projection. The message history is the durable record of which
      // Evidence has actually been sent; dismissedComposerEvidenceIds alone
      // is an in-memory hint that does not survive a claim switch or reload.
      const alreadyLinked = linkedEvidenceIds()
      return items
        .filter((item) => hasRealContent(item))
        .filter((item) => !dismissedComposerEvidenceIds.current.has(item.evidence_id))
        .filter((item) => !alreadyLinked.has(item.evidence_id))
        .map((item) => attachmentForEvidence(item, currentByEvidenceId.get(item.evidence_id)))
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
    if (!claim?.claim_id) {
      latestRevisionClaimId.current = null
      latestRevision.current = 0
      return
    }
    if (latestRevisionClaimId.current !== claim.claim_id) {
      latestRevisionClaimId.current = claim.claim_id
      latestRevision.current = Number(claim.revision || 0)
      return
    }
    latestRevision.current = Math.max(latestRevision.current, Number(claim.revision || 0))
  }, [claim?.claim_id, claim?.revision])

  useEffect(() => {
    if (realtimePrincipal === 'none') {
      realtimeCursor.current = null
      realtimeSeenEventIds.current.clear()
      setRealtimeHealth('healthy')
      return undefined
    }

    // A new claimant authentication context must not reuse replay state from
    // the previous principal. Starting without an acknowledged cursor is
    // recovered by subscribing first and taking an authoritative snapshot.
    realtimeCursor.current = null
    realtimeSeenEventIds.current.clear()
    setRealtimeHealth('healthy')

    const controller = new AbortController()
    let active = true
    let reconnectDelay = 1000
    let degradedRefreshes = 0
    let needsResyncSnapshot = false
    let needsRecoverySnapshot = false
    const maxDegradedRefreshes = 5
    const maxRecoverySnapshots = 3

    function rememberEvent(eventId) {
      if (!eventId) return
      realtimeSeenEventIds.current.add(eventId)
      while (realtimeSeenEventIds.current.size > 100) {
        const oldest = realtimeSeenEventIds.current.values().next().value
        realtimeSeenEventIds.current.delete(oldest)
      }
    }

    async function refreshFullSnapshot() {
      const transition = claimTransitionRef.current
      if (transition) {
        await transition.completion
        if (!active) return
      }

      const activeClaim = activeClaimRef.current
      const activeSessionId = activeSessionIdRef.current
      const refreshes = []
      let activeProjectionRecovered = !activeClaim?.claim_id

      if (activeClaim?.claim_id) {
        const claimId = activeClaim.claim_id
        refreshes.push((async () => {
          const messagesGeneration = activeSessionId ? beginMessagesReadback() : null
          const [currentClaim, conversation, evidence] = await Promise.all([
            getClaim(claimId),
            activeSessionId ? getClaimMessages(claimId, activeSessionId) : Promise.resolve(null),
            getClaimEvidence(claimId),
          ])
          if (
            !active
            || activeClaimRef.current?.claim_id !== claimId
            || activeSessionIdRef.current !== activeSessionId
          ) return
          const claimApplied = applyClaimSnapshot(currentClaim)
          let messagesApplied = activeSessionId === null
          if (conversation && messagesGeneration !== null) {
            messagesApplied = applyMessagesReadback(conversation.items, {
              generation: messagesGeneration,
              claimId,
              sessionId: activeSessionId,
            })
          }
          if (syncEvidenceProjection(evidence)) setEvidenceSyncNotice('')
          setEvidenceLoadStatus('ready')
          activeProjectionRecovered = Boolean(
            claimApplied
            && messagesApplied
            && activeClaimRef.current?.claim_id === claimId
            && activeSessionIdRef.current === activeSessionId
          )
        })())
      }

      if (accountRef.current) {
        refreshes.push(fetchClaimHistory({ signal: controller.signal }).then((items) => {
          if (!active) return
          replaceClaimHistory(items)
          setClaimHistoryError('')
        }))
      }
      await Promise.all(refreshes)
      return activeProjectionRecovered
    }

    async function applyRealtimeEvent(delivery) {
      if (!active) return

      if (delivery.type === 'resync_required') {
        needsResyncSnapshot = true
        needsRecoverySnapshot = false
        setRealtimeHealth('stale')
        realtimeCursor.current = null
        realtimeSeenEventIds.current.clear()
        reconnectDelay = 0
        degradedRefreshes = 0
        return
      }

      const deliveryClaimId = delivery.data?.claim_id
      const transition = claimTransitionRef.current
      if (
        transition
        && deliveryClaimId === transition.claimId
        && activeClaimRef.current?.claim_id !== deliveryClaimId
      ) {
        await transition.completion
        if (!active) return
      }

      const eventId = delivery.data?.event_id
      if (eventId && realtimeSeenEventIds.current.has(eventId)) return

      if (delivery.type === 'agent.turn.progress') {
        const activeSessionId = activeSessionIdRef.current
        if (activeSessionId && delivery.data?.session_id === activeSessionId) {
          const progressEvent = { ...delivery.data, event_type: 'agent.turn.progress', cursor: delivery.cursor }
          const expectedTurnId = pendingSubmission.current?.clientMessageId
            || activeTurnProgressRef.current?.turnId
          const next = reduceTurnProgress(activeTurnProgressRef.current, progressEvent, expectedTurnId)
          if (next !== activeTurnProgressRef.current) {
            activeTurnProgressRef.current = next
            setActiveTurnProgress(next)
          }
        }
        rememberEvent(eventId)
        reconnectDelay = 1000
        degradedRefreshes = 0
        return
      }

      if (delivery.type !== 'resources.changed') return

      const resources = new Set(delivery.data?.resources || [])
      const activeClaim = activeClaimRef.current
      const claimId = delivery.data?.claim_id
      const eventRevision = Number(delivery.data?.claim_revision || 0)
      const refreshes = []

      if (activeClaim?.claim_id === claimId) {
        const activeSessionId = activeSessionIdRef.current
        if (
          resources.has('claim')
          || resources.has('handoffs')
          || resources.has('work_items')
          || resources.has('external_tasks')
        ) {
          refreshes.push(getClaim(claimId).then((currentClaim) => {
            if (active && activeClaimRef.current?.claim_id === claimId) {
              applyClaimSnapshot(currentClaim, { minimumRevision: eventRevision })
            }
          }))
        }
        if (resources.has('messages') && activeSessionId) {
          const messagesGeneration = beginMessagesReadback()
          refreshes.push(getClaimMessages(claimId, activeSessionId).then((conversation) => {
            if (!active) return
            applyMessagesReadback(conversation.items, {
              generation: messagesGeneration,
              claimId,
              sessionId: activeSessionId,
            })
          }))
        }
        if (resources.has('evidence')) {
          refreshes.push(getClaimEvidence(claimId).then((evidence) => {
            if (active && activeClaimRef.current?.claim_id === claimId) {
              if (syncEvidenceProjection(evidence)) setEvidenceSyncNotice('')
              setEvidenceLoadStatus('ready')
            }
          }))
        }
      }

      if (accountRef.current && (resources.has('claim') || resources.has('queue'))) {
        refreshes.push(fetchClaimHistory({ signal: controller.signal }).then((items) => {
          if (!active) return
          replaceClaimHistory(items)
          setClaimHistoryError('')
        }))
      }

      await Promise.all(refreshes)
      if (!active) return
      rememberEvent(eventId)
      reconnectDelay = 1000
      degradedRefreshes = 0
    }

    async function runDegradedRefresh() {
      if (degradedRefreshes >= maxDegradedRefreshes) return
      if (globalThis.document?.visibilityState === 'hidden') return
      degradedRefreshes += 1
      try { await refreshFullSnapshot() } catch { /* later bounded retry */ }
    }

    async function connect() {
      while (active && !controller.signal.aborted) {
        const recoverOnOpen = (
          needsResyncSnapshot
          || needsRecoverySnapshot
          || realtimeCursor.current === null
        )
        const discardCursor = needsResyncSnapshot || realtimeCursor.current === null
        try {
          await streamRealtimeEvents({
            cursor: discardCursor ? null : realtimeCursor.current,
            signal: controller.signal,
            onOpen: recoverOnOpen
              ? async () => {
                // A snapshot read while the claimant's own turn lands is superseded
                // by that newer local state. That is not a connection problem, so
                // read again before treating the stream as failed.
                let projectionRecovered = false
                for (let attempt = 0; attempt < maxRecoverySnapshots && !projectionRecovered; attempt += 1) {
                  projectionRecovered = await refreshFullSnapshot()
                  if (!active || controller.signal.aborted) return
                }
                if (!projectionRecovered) {
                  throw new Error('Authoritative claimant realtime recovery snapshot was superseded.')
                }
                needsResyncSnapshot = false
                needsRecoverySnapshot = false
                if (discardCursor) {
                  realtimeCursor.current = null
                  realtimeSeenEventIds.current.clear()
                }
                reconnectDelay = 1000
                degradedRefreshes = 0
                setRealtimeHealth('healthy')
              }
              : undefined,
            onEvent: applyRealtimeEvent,
            onCursor: (cursor) => { realtimeCursor.current = cursor },
          })
          if (!active || controller.signal.aborted) return
          if (!needsResyncSnapshot) {
            needsRecoverySnapshot = true
            setRealtimeHealth('reconnecting')
            await runDegradedRefresh()
          }
        } catch (streamFailure) {
          if (!active || controller.signal.aborted) return
          if (streamFailure instanceof ApiRequestError && streamFailure.code === 'INVALID_EVENT_CURSOR') {
            needsResyncSnapshot = true
            needsRecoverySnapshot = false
            realtimeCursor.current = null
            realtimeSeenEventIds.current.clear()
            reconnectDelay = 0
            degradedRefreshes = 0
            setRealtimeHealth('stale')
          } else if (needsResyncSnapshot) {
            reconnectDelay = Math.max(reconnectDelay, 1000)
            setRealtimeHealth('stale')
          } else {
            needsRecoverySnapshot = true
            setRealtimeHealth('reconnecting')
            await runDegradedRefresh()
          }
          if (latestEvidenceItems.current.some((item) => item.file_status === 'processing')) {
            setEvidenceSyncNotice(
              'Live file status updates are temporarily disconnected. We are reconnecting; use Check status if you need to verify the file now.',
            )
          }
        }
        if (!active || controller.signal.aborted) return
        const jitter = Math.floor(Math.random() * Math.min(250, reconnectDelay / 4))
        await new Promise((resolve) => globalThis.setTimeout(resolve, reconnectDelay + jitter))
        reconnectDelay = Math.min(Math.max(reconnectDelay, 1000) * 2, 8000)
      }
    }

    connect()
    return () => {
      active = false
      controller.abort()
    }
  // Realtime callbacks read the current Claim, session, and account from refs so one
  // browser-scoped stream survives ordinary navigation without reconnect churn.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [realtimePrincipal])

  useEffect(() => {
    if (!account) return undefined
    let active = true
    const controller = new AbortController()
    fetchClaimHistory({ signal: controller.signal })
      .then((items) => {
        if (active) {
          replaceClaimHistory(items)
          setClaimHistoryError('')
        }
      })
      .catch((requestError) => {
        if (active && requestError?.name !== 'AbortError') {
          setClaimHistoryError(requestError.message || 'The Claim service did not respond.')
        }
      })
    return () => {
      active = false
      controller.abort()
    }
  }, [account])

  useEffect(() => {
    let active = true
    getRuntimeCapabilities()
      .then((capabilities) => {
        if (!active) return
        setRuntimeCapabilities(capabilities)
        setSelectedModel((current) => current || (
          capabilities.default_model_profile_id
          || capabilities.models?.find((model) => model.availability !== 'unavailable')?.id
          || capabilities.models?.[0]?.id
          || ''
        ))
      })
      .catch(() => {})
    return () => { active = false }
  }, [account?.profile?.email])

  useEffect(() => {
    if (!claim?.claim_id) {
      evidencePreviewFiles.current.clear()
      evidenceClaimId.current = null
      latestEvidenceRevision.current = 0
      latestEvidenceItems.current = []
      evidenceHasLocalMutation.current = false
      setEvidenceItems([])
      setEvidenceLoadStatus('idle')
      setAttachments([])
      return undefined
    }
    if (evidenceClaimId.current !== claim.claim_id) {
      evidencePreviewFiles.current.clear()
      evidenceClaimId.current = claim.claim_id
      latestEvidenceRevision.current = 0
      latestEvidenceItems.current = []
      evidenceHasLocalMutation.current = false
      dismissedComposerEvidenceIds.current.clear()
      setEvidenceItems([])
      setEvidenceLoadStatus('loading')
      setDetailsTab('summary')
    }
    let active = true
    getClaimEvidence(claim.claim_id)
      .then((response) => {
        if (active) {
          if (syncEvidenceProjection(response)) setEvidenceSyncNotice('')
          setEvidenceLoadStatus('ready')
        }
      })
      .catch(() => {
        if (active) setEvidenceLoadStatus('error')
      })
    return () => { active = false }
  // The projection updater only uses stable React setters and is intentionally local to this view.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [claim?.claim_id])

  useEffect(() => {
    // Evidence and message history load independently, so evidence syncing
    // before this conversation's messages have arrived would otherwise let
    // historical Evidence sit unfiltered in the composer tray until some
    // later resync happens to catch it. Pruning here on every messages
    // change closes that race: as soon as a message's evidence_refs are
    // known, any attachment still carrying that same evidenceId is already
    // sent and must leave the tray now, not whenever evidence next syncs.
    const linked = new Set()
    for (const item of messages) {
      for (const evidenceId of item.evidence_refs || []) linked.add(evidenceId)
    }
    if (linked.size === 0) return
    setAttachments((current) => {
      const filtered = current.filter((item) => !item.evidenceId || !linked.has(item.evidenceId))
      return filtered.length === current.length ? current : filtered
    })
  }, [messages])

  async function uploadAttachment(
    file,
    attempt,
    activeClaim,
    {
      existingAttachment = false,
      checkExistingEvidence = false,
      settleStatus = true,
    } = {},
  ) {
    const localId = attempt.localId
    evidenceUploadControllers.current.get(localId)?.abort()
    const uploadController = new AbortController()
    evidenceUploadControllers.current.set(localId, uploadController)
    if (attempt.evidenceId) evidencePreviewFiles.current.set(attempt.evidenceId, file)
    setAttachments((current) => existingAttachment
      ? current.map((item) => item.id === localId
        ? { ...item, previewFile: file, status: 'uploading', statusLabel: 'Uploading…', retry: null }
        : item)
      : [...current, {
        id: localId,
        name: file.name,
        previewFile: file,
        status: 'uploading',
        statusLabel: 'Uploading…',
      }])
    let uploadRevision = activeClaim.revision
    try {
      if (checkExistingEvidence) {
        const authoritative = await getClaimEvidence(activeClaim.claim_id)
        syncEvidenceProjection(authoritative)
        setEvidenceSyncNotice('')
        uploadRevision = Math.max(uploadRevision, Number(authoritative.revision || 0))
        const observed = (authoritative.items || []).find(
          (item) => item.evidence_id === attempt.evidenceId,
        )
        if (observed && observed.file_status !== 'awaiting_upload') {
          setAttachments((current) => current.map((item) => item.id === localId
            ? attachmentForEvidence(observed, {
              ...item,
              retry: observed.file_status === 'failed'
                ? () => handleFileSelected(file, attempt)
                : null,
              retryLabel: observed.file_status === 'failed' ? 'Check status' : null,
            })
            : item))
          if (settleStatus) setStatus('idle')
          return {
            revision: uploadRevision,
            succeeded: true,
            evidenceId: observed.evidence_id,
            fileStatus: observed.file_status,
            statusLabel: evidenceFileStatusLabel(observed.file_status, observed.status),
            readyForMessage: observed.file_status !== 'failed',
          }
        }
      }
      const requested = await requestEvidenceUpload({
        claimId: activeClaim.claim_id,
        revision: uploadRevision,
        file,
        kind: attempt.kind,
        evidenceId: attempt.evidenceId,
        idempotencyKey: attempt.uploadKey,
        signal: uploadController.signal,
      })
      uploadRevision = requested.revision
      evidenceHasLocalMutation.current = true
      latestEvidenceRevision.current = requested.revision
      attempt.evidenceId = requested.evidence_id
      evidencePreviewFiles.current.set(requested.evidence_id, file)
      dismissedComposerEvidenceIds.current.delete(requested.evidence_id)
      setAttachments((current) => current.map((item) => item.id === localId
        ? { ...item, evidenceId: requested.evidence_id, stagedFile: null, uploadAttempt: attempt }
        : item))
      setClaimRevision(requested.revision)
      await uploadEvidenceContent({ upload: requested.upload, file, signal: uploadController.signal })
      const fileBytes = new Uint8Array(await file.arrayBuffer())
      const checksumBuffer = await globalThis.crypto.subtle.digest('SHA-256', fileBytes)
      const checksum = `sha256:${Array.from(new Uint8Array(checksumBuffer), (byte) => byte.toString(16).padStart(2, '0')).join('')}`
      const completed = await completeEvidenceUpload({
        claimId: activeClaim.claim_id,
        evidenceId: requested.evidence_id,
        revision: requested.revision,
        checksum,
        idempotencyKey: attempt.completeKey,
        signal: uploadController.signal,
      })
      latestEvidenceRevision.current = completed.revision
      attempt.evidenceId = completed.evidence.evidence_id
      latestEvidenceItems.current = [completed.evidence]
      setClaimRevision(completed.revision)
      setEvidenceItems((current) => [...current.filter((item) => item.evidence_id !== completed.evidence.evidence_id), completed.evidence])
      setAttachments((current) => current.map((item) => item.id === localId
        ? attachmentForEvidence(completed.evidence, {
          ...item,
          stagedFile: null,
          retryFile: file,
          retryAttempt: attempt,
        })
        : item))
      if (settleStatus) setStatus('idle')
      return {
        revision: completed.revision,
        succeeded: true,
        evidenceId: completed.evidence.evidence_id,
        fileStatus: completed.evidence.file_status,
        statusLabel: evidenceFileStatusLabel(completed.evidence.file_status, completed.evidence.status),
        readyForMessage: completed.evidence.file_status !== 'failed',
      }
    } catch (requestError) {
      if (requestError?.name === 'AbortError') {
        return { revision: uploadRevision, succeeded: false, aborted: true }
      }
      setAttachments((current) => current.map((item) => item.id === localId
        ? { ...item, status: 'failed', statusLabel: requestError.message || 'Upload failed', retry: () => handleFileSelected(file, attempt) }
        : item))
      showError(requestError)
      return {
        revision: Math.max(uploadRevision, latestEvidenceRevision.current),
        succeeded: false,
        evidenceId: attempt.evidenceId,
        message: requestError?.message || 'Northwind could not upload this file.',
      }
    } finally {
      if (evidenceUploadControllers.current.get(localId) === uploadController) {
        evidenceUploadControllers.current.delete(localId)
      }
    }
  }

  async function handleFileSelected(
    file,
    existingAttempt = null,
    requestedKind = null,
    requestedEvidenceId = null,
  ) {
    if (isBusy) {
      return {
        succeeded: false,
        message: 'Another claim update is still in progress. Wait a moment, then choose Replace and try again.',
      }
    }
    if (!hasClaimantAccessToken()) {
      setError('Sign in before uploading a file. Your anonymous conversation is still available, and you can resume it after signing in.')
      setStatus('error')
      return {
        succeeded: false,
        message: 'Sign in, then choose Replace to upload this file.',
      }
    }
    setError('')
    const attempt = existingAttempt || {
      localId: requestId('file'),
      uploadKey: requestId('evidence-upload'),
      completeKey: requestId('evidence-complete'),
      kind: requestedKind || (file.type.startsWith('image/') ? 'incident_photo' : 'other_document'),
      evidenceId: requestedEvidenceId,
    }
    cancelledAttachmentIds.current.delete(attempt.localId)

    if (!isWorkspaceActive || !claim) {
      setAttachments((current) => [
        ...current,
        {
          id: attempt.localId,
          name: file.name,
          status: 'staged',
          statusLabel: 'Ready to upload after your first message is sent',
          previewFile: file,
          stagedFile: file,
          uploadAttempt: attempt,
        },
      ])
      return { succeeded: true }
    }

    return uploadAttachment(file, attempt, claim, {
      existingAttachment: Boolean(existingAttempt),
      checkExistingEvidence: Boolean(existingAttempt),
    })
  }

  function removeComposerAttachment(attachment) {
    cancelledAttachmentIds.current.add(attachment.id)
    attachmentsRef.current = attachmentsRef.current.filter((item) => item.id !== attachment.id)
    evidenceUploadControllers.current.get(attachment.id)?.abort()
    evidenceUploadControllers.current.delete(attachment.id)
    const evidenceId = attachment.evidenceId || attachment.uploadAttempt?.evidenceId
    if (evidenceId) {
      dismissedComposerEvidenceIds.current.add(evidenceId)
      evidencePreviewFiles.current.delete(evidenceId)
    }
    setAttachments((current) => current.filter((item) => item.id !== attachment.id))
  }

  function clearComposerAttachments() {
    for (const attachment of attachmentsRef.current) {
      cancelledAttachmentIds.current.add(attachment.id)
    }
    attachmentsRef.current = []
    for (const controller of evidenceUploadControllers.current.values()) controller.abort()
    evidenceUploadControllers.current.clear()
    dismissedComposerEvidenceIds.current.clear()
    setAttachments([])
  }

  function cancelComposerDraftAttachments() {
    const draftAttachmentIds = new Set(attachmentsRef.current
      .filter((item) => (
        item.status === 'staged'
        || item.status === 'uploading'
        || (item.status === 'failed' && !item.evidenceId)
      ))
      .map((item) => item.id))
    for (const attachmentId of draftAttachmentIds) {
      cancelledAttachmentIds.current.add(attachmentId)
    }
    attachmentsRef.current = attachmentsRef.current.filter(
      (item) => !draftAttachmentIds.has(item.id),
    )
    for (const controller of evidenceUploadControllers.current.values()) controller.abort()
    evidenceUploadControllers.current.clear()
    setAttachments((current) => current.filter((item) => {
      const isDraft = item.status === 'staged'
        || item.status === 'uploading'
        || (item.status === 'failed' && !item.evidenceId)
      if (isDraft && item.evidenceId) dismissedComposerEvidenceIds.current.add(item.evidenceId)
      return !isDraft
    }))
  }

  async function refreshAfterConflict() {
    if (!claim) return
    const current = await getClaim(claim.claim_id)
    applyClaimSnapshot(current)
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

  async function reconcileDeferredSessionPause(
    currentClaim,
    currentSessionId,
    reconciliationOperation,
  ) {
    if (!currentClaim?.claim_id || !currentSessionId) {
      return null
    }
    const reconciliationIsCurrent = () => (
      isMessageReconciliationCurrent(reconciliationOperation)
    )
    const recoveryKey = sessionPauseRecoveryKey(
      currentClaimantIdentityKey(),
      currentClaim.claim_id,
    )
    const operation = deferredSessionPauses.current.get(recoveryKey)
    if (!operation) return { claim: currentClaim, sessionId: currentSessionId }

    await operation.settled
    if (!reconciliationIsCurrent() || !isSessionPauseIdentityCurrent(operation)) {
      return null
    }
    if (deferredSessionPauses.current.get(recoveryKey) !== operation) {
      return { claim: currentClaim, sessionId: currentSessionId }
    }

    const latestClaim = await getClaim(currentClaim.claim_id)
    if (
      !reconciliationIsCurrent()
      || !isSessionPauseIdentityCurrent(operation)
    ) {
      return null
    }
    if (latestClaim.active_session_id === currentSessionId) {
      forgetDeferredSessionPause(operation)
      applyClaimSnapshot(latestClaim)
      return { claim: latestClaim, sessionId: currentSessionId }
    }

    const resumedSession = await resumeClaimSession({ claimId: currentClaim.claim_id })
    if (
      !reconciliationIsCurrent()
      || !isSessionPauseIdentityCurrent(operation)
    ) return null
    const authoritativeClaim = await getClaim(currentClaim.claim_id)
    if (
      !reconciliationIsCurrent()
      || !isSessionPauseIdentityCurrent(operation)
    ) return null
    const conversation = await getClaimMessages(
      currentClaim.claim_id,
      resumedSession.session_id,
    )
    if (
      !reconciliationIsCurrent()
      || !isSessionPauseIdentityCurrent(operation)
    ) {
      return null
    }

    forgetDeferredSessionPause(operation)
    replaceActiveClaimContext(authoritativeClaim, resumedSession.session_id)
    if (resumedSession.model_profile_id) setSelectedModel(resumedSession.model_profile_id)
    commitMessages(conversation.items)
    setRecoveryFailure(null)
    setForm(authoritativeClaim.form)
    setContentsItems(authoritativeClaim.contents_items || [])
    setDynamicForm(authoritativeClaim.dynamic_form || null)
    setNextStep(authoritativeClaim.customer_next_step)
    setHandoff(authoritativeClaim.handoff || null)
    setResumeContext({
      ...resumedSession.resume,
      resumed_at: resumedSession.started_at,
      resumed_after_message_id: orderMessages(conversation.items).at(-1)?.message_id || null,
      has_resume_boundary: true,
    })
    rememberClaimInHistory(authoritativeClaim)
    return { claim: authoritativeClaim, sessionId: resumedSession.session_id }
  }

  async function sendMessage(event, recoveryMessage = null) {
    event.preventDefault()
    const submittedForm = event.currentTarget
    const text = recoveryMessage ? messageText(recoveryMessage) : draft.trim()
    const recoveryEvidenceRefs = recoveryMessage?.evidence_refs || []
    const recoveryAttachments = recoveryMessage
      ? recoveryEvidenceRefs.map((evidenceId, index) => {
        const evidence = evidenceItems.find((item) => item.evidence_id === evidenceId)
        return {
          id: evidenceId,
          evidenceId,
          name: evidence?.original_filename || evidence?.kind || `Attached file ${index + 1}`,
          mediaType: evidence?.media_type,
          previewFile: evidencePreviewFiles.current.get(evidenceId),
          status: evidence?.file_status === 'processing' ? 'processing' : 'uploaded',
          statusLabel: evidence
            ? evidenceFileStatusLabel(evidence.file_status, evidence.status)
            : 'Attached',
        }
      })
      : []
    const selectedAttachments = recoveryMessage
      ? recoveryAttachments
      : attachments.filter(isSendableComposerAttachment)
    const hasUploadingAttachment = !recoveryMessage
      && attachments.some((attachment) => attachment.status === 'uploading')
    if (
      (!text && selectedAttachments.length === 0)
      || hasUploadingAttachment
      || isBusy
      || isMessageReconciliationCurrent(pendingMessageReconciliation.current)
    ) return
    const selectedModelOption = runtimeCapabilities.models.find((model) => model.id === selectedModel)
    const modelCompatibility = modelAttachmentCompatibility(selectedAttachments, selectedModelOption)
    if (!modelCompatibility.compatible) {
      setError(modelCompatibility.message)
      setStatus('error')
      return
    }
    const stagedAttachments = recoveryMessage
      ? []
      : selectedAttachments.filter((attachment) => attachment.status === 'staged')
    const submissionSignature = recoveryMessage
      ? JSON.stringify({
        clientMessageId: recoveryMessage.client_message_id,
        text,
        modelProfileId: selectedModel,
        attachments: recoveryEvidenceRefs,
      })
      : attachmentSubmissionSignature(text, selectedAttachments, selectedModel)
    const isAssistanceReply = assistanceState?.key === 'response_needed'
    let presentedAttachments = selectedAttachments

    if (recoveryMessage) {
      pendingSubmission.current = {
        signature: submissionSignature,
        text,
        claimKey: requestId('claim'),
        turnKey: requestId('turn'),
        clientMessageId: recoveryMessage.client_message_id,
        evidenceRefs: recoveryEvidenceRefs,
      }
    }
    if (!recoveryMessage && pendingSubmission.current?.signature !== submissionSignature) {
      pendingSubmission.current = {
        signature: submissionSignature,
        text,
        claimKey: requestId('claim'),
        turnKey: requestId('turn'),
        clientMessageId: requestId('message'),
      }
    }
    const operation = pendingSubmission.current
    let activeClaim = hasStarted ? claim : null
    let activeSessionId = hasStarted ? sessionId : null

    if (activeClaim && activeSessionId) {
      const reconciliationOperation = beginMessageReconciliation(activeClaim, activeSessionId)
      let reconciled
      try {
        reconciled = await reconcileDeferredSessionPause(
          activeClaim,
          activeSessionId,
          reconciliationOperation,
        )
      } catch (requestError) {
        const mayMutateCurrentWorkspace = isMessageReconciliationCurrent(
          reconciliationOperation,
        )
        finishMessageReconciliation(reconciliationOperation)
        if (mayMutateCurrentWorkspace) {
          showError(requestError)
        } else if (pendingSubmission.current === operation) {
          pendingSubmission.current = null
        }
        return
      }
      finishMessageReconciliation(reconciliationOperation)
      if (!reconciled) {
        if (pendingSubmission.current === operation) pendingSubmission.current = null
        return
      }
      activeClaim = reconciled.claim
      activeSessionId = reconciled.sessionId
    }

    forceLatestMessages.current = true
    setError('')
    setFailedMessage(null)
    setRecoveryFailure(null)
    // The message moves into the conversation as soon as it is sent; the
    // composer is restored below only if it could not be delivered.
    if (!recoveryMessage) setDraft('')
    if (!activeClaim && !isWorkspaceActive) {
      composerHandoffFrom.current = captureComposerRect(submittedForm)
      setArrivingFromEntry(true)
      setDraftWorkspaceActive(true)
      setWorkspaceActive(true)
    }
    const restoreDraft = () => {
      if (!recoveryMessage) setDraft((current) => current || text)
    }
    if (isAssistanceReply) {
      setAssistanceReplyReview({
        claimId: activeClaim.claim_id,
        handoffId: handoff.handoff_id,
        messageId: null,
      })
    }
    setStatus(activeClaim ? 'sending' : 'starting')
    let messageWasSubmitted = Boolean(activeClaim)
    try {
      activeTurnProgressRef.current = null
      setActiveTurnProgress(null)
      setPendingMessage({
        text,
        attachments: selectedAttachments.map((attachment) => attachment.status === 'staged'
          ? { ...attachment, status: 'uploading', statusLabel: 'Preparing upload…' }
          : attachment),
        turnId: operation.clientMessageId,
        retrying: Boolean(recoveryMessage),
      })
      if (!activeClaim) {
        const created = await createClaim({
          idempotencyKey: operation.claimKey,
          incidentType: claimType || null,
          modelProfileId: selectedModel,
        })
        activeClaim = created.claim
        activeSessionId = created.session.session_id
        rememberClaimInHistory(created.claim)
        replaceActiveClaimContext(created.claim, activeSessionId)
        evidenceClaimId.current = created.claim.claim_id
        latestEvidenceRevision.current = Number(created.claim.revision || 0)
        latestEvidenceItems.current = []
        evidenceHasLocalMutation.current = false
        dismissedComposerEvidenceIds.current.clear()
        if (created.session.model_profile_id) setSelectedModel(created.session.model_profile_id)
        setForm(created.claim.form)
        setContentsItems(created.claim.contents_items || [])
        setDynamicForm(created.claim.dynamic_form || null)
        setNextStep(created.claim.customer_next_step)
        commitMessages([])
        setHandoff(null)
        setEvidenceItems([])
        setResumeContext(null)
        setExpandedConversationPanels({})
        setWorkspaceView('chat')
        setMobileView('chat')
        setWorkspaceActive(true)
      }

      let turnClaim = activeClaim
      const uploadedAttachments = new Map()
      const attachmentIsStillSelected = (attachment) => (
        !cancelledAttachmentIds.current.has(attachment.id)
        && attachmentsRef.current.some((current) => current.id === attachment.id)
      )
      for (const attachment of stagedAttachments) {
        if (!attachmentIsStillSelected(attachment)) continue
        const upload = await uploadAttachment(
          attachment.stagedFile,
          attachment.uploadAttempt,
          turnClaim,
          { existingAttachment: true, settleStatus: false },
        )
        turnClaim = { ...turnClaim, revision: upload.revision }
        if (upload.aborted && !attachmentIsStillSelected(attachment)) continue
        if (!upload.succeeded || !upload.evidenceId || upload.readyForMessage === false) {
          if (isAssistanceReply) setAssistanceReplyReview(null)
          activeTurnProgressRef.current = null
          setActiveTurnProgress(null)
          setPendingMessage(null)
          restoreDraft()
          if (upload.aborted) {
            pendingSubmission.current = null
            setStatus('idle')
          } else if (upload.readyForMessage === false) {
            setError('The file could not be processed. Remove it or check its status before sending.')
            setStatus('error')
          }
          return
        }
        if (!attachmentIsStillSelected(attachment)) continue
        uploadedAttachments.set(attachment.id, {
          ...attachment,
          evidenceId: upload.evidenceId,
          status: upload.fileStatus === 'processing' ? 'processing' : 'uploaded',
          statusLabel: upload.statusLabel || 'Uploaded',
        })
      }
      presentedAttachments = recoveryMessage
        ? selectedAttachments
        : selectedAttachments
            .filter(attachmentIsStillSelected)
            .map((attachment) => uploadedAttachments.get(attachment.id) || attachment)
      const evidenceRefs = recoveryMessage
        ? [...new Set(operation.evidenceRefs || [])]
        : [...new Set(presentedAttachments
            .map((attachment) => attachment.evidenceId || attachment.uploadAttempt?.evidenceId)
            .filter(Boolean))]
      if (!text && evidenceRefs.length === 0) {
        if (isAssistanceReply) setAssistanceReplyReview(null)
        activeTurnProgressRef.current = null
        setActiveTurnProgress(null)
        setPendingMessage(null)
        pendingSubmission.current = null
        setStatus('idle')
        return
      }
      const currentSignature = recoveryMessage
        ? operation.signature
        : attachmentSubmissionSignature(text, presentedAttachments, selectedModel)
      if (!recoveryMessage && operation.signature !== currentSignature) {
        operation.turnKey = requestId('turn')
        operation.clientMessageId = requestId('message')
      }
      operation.signature = currentSignature
      setPendingMessage({
        text,
        attachments: presentedAttachments,
        turnId: operation.clientMessageId,
      })

      messageWasSubmitted = true
      const turn = await submitClaimMessage({
        claimId: activeClaim.claim_id,
        sessionId: activeSessionId,
        revision: turnClaim.revision,
        text,
        evidenceRefs,
        modelProfileId: selectedModel,
        idempotencyKey: operation.turnKey,
        clientMessageId: operation.clientMessageId,
      })
      const currentRevision = currentTurnRevision(turn)
      const historicalTurn = turn.current_claim && currentRevision > turn.claim_revision
      // Historical actions are evidence, not permission to act on today's offer.
      const responseAgentMessage = historicalTurn && turn.agent_message
        ? { ...turn.agent_message, message_actions: [] }
        : turn.agent_message
      commitMessages((current) => mergeMessagesById(current, [
        turn.claimant_message,
        ...(responseAgentMessage ? [responseAgentMessage] : []),
      ]))
      if (turn.current_claim) {
        applyClaimSnapshot(turn.current_claim, { minimumRevision: currentRevision })
        rememberClaimInHistory(turn.current_claim)
      } else {
        setForm((current) => mergeFields(current, turn.form_changes))
        setContentsItems((current) => mergeContentsItems(current, turn.contents_item_changes || []))
        setDynamicForm(turn.dynamic_form || null)
        setClaimRevision(currentRevision, turn.primary_action)
        if (turn.decision) setNextStep(turn.decision.customer_next_step)
        if (turn.handoff) setHandoff(turn.handoff)
        rememberClaimInHistory({
          ...activeClaim,
          revision: currentRevision,
          customer_next_step: turn.decision?.customer_next_step || activeClaim.customer_next_step,
          updated_at: turn.claimant_message?.created_at || activeClaim.updated_at,
        })
      }
      if (isAssistanceReply) {
        setAssistanceReplyReview({
          claimId: activeClaim.claim_id,
          handoffId: handoff.handoff_id,
          messageId: turn.claimant_message.message_id,
        })
      }
      const completedActivity = completeTurnProgress(
        activeTurnProgressRef.current,
        operation.clientMessageId,
      )
      if (turn.agent_message?.message_id) {
        setMessageActivities((current) => ({
          ...current,
          [turn.agent_message.message_id]: completedActivity,
        }))
      }
      activeTurnProgressRef.current = null
      setActiveTurnProgress(null)
      pendingSubmission.current = null
      setPendingMessage(null)
      setFailedMessage(null)
      if (historicalTurn) {
        const generation = beginMessagesReadback()
        try {
          const conversation = await getClaimMessages(activeClaim.claim_id, activeSessionId)
          applyMessagesReadback(conversation.items, {
            generation,
            claimId: activeClaim.claim_id,
            sessionId: activeSessionId,
          })
        } catch {
          if (generation === messagesRequestGeneration.current
            && activeClaimRef.current?.claim_id === activeClaim.claim_id
            && activeSessionIdRef.current === activeSessionId) {
            setError('Your message is saved, but current service actions could not be refreshed. Reopen this conversation to refresh them.')
          }
        }
      }
      if (!recoveryMessage) {
        const sentAttachmentIds = new Set(selectedAttachments.map((attachment) => attachment.id))
        const sentEvidenceRefs = new Set(evidenceRefs)
        for (const evidenceId of sentEvidenceRefs) dismissedComposerEvidenceIds.current.add(evidenceId)
        setAttachments((current) => current.filter((attachment) => (
          !sentAttachmentIds.has(attachment.id)
          && !sentEvidenceRefs.has(attachment.evidenceId || attachment.uploadAttempt?.evidenceId)
        )))
      }
      setStatus('idle')
    } catch (requestError) {
      if (isAssistanceReply) setAssistanceReplyReview(null)
      activeTurnProgressRef.current = null
      setActiveTurnProgress(null)
      setPendingMessage(null)
      restoreDraft()
      if (messageWasSubmitted) {
        const serverConfirmedFailure = requestError instanceof ApiRequestError
          && Number.isInteger(requestError.status)
        const attachmentGuidance = presentedAttachments.length > 1
          ? 'Your file uploads are preserved and remain attached. '
          : presentedAttachments.length === 1
            ? 'Your file upload is preserved and remains attached. '
            : ''
        const retryGuidance = requestError instanceof ApiRequestError && requestError.retryable
          ? 'Try the message again in a moment.'
          : requestError instanceof ApiRequestError && requestError.code === 'DEPENDENCY_FAILED'
            ? 'Retry the message, or select another available model and retry.'
            : 'Review the message and try again.'
        const failureMessage = serverConfirmedFailure
          ? `${requestError.message} ${attachmentGuidance}${retryGuidance}`
          : `We could not confirm delivery because the connection ended before the service responded. ${attachmentGuidance}Retry safely; the same request will not create a duplicate.`
        if (recoveryMessage) {
          pendingSubmission.current = null
          setRecoveryFailure({ messageId: recoveryMessage.message_id, message: failureMessage })
        } else {
          setFailedMessage({
            text,
            attachments: presentedAttachments,
            sender: 'You',
            deliveryState: serverConfirmedFailure ? 'Not sent' : 'Delivery not confirmed',
            message: failureMessage,
          })
        }
        setError('')
        if (requestError instanceof ApiRequestError && requestError.code === 'REVISION_CONFLICT') {
          refreshAfterConflict().catch(() => {})
        }
        setStatus('error')
      } else {
        showError(requestError)
      }
    }
  }

  function resetForNewChat(stayInWorkspace, pauseOperation = null) {
    if (pauseOperation && !isSessionPauseCurrent(pauseOperation)) return
    if (pauseOperation) {
      deferredSessionPauses.current.delete(pauseOperation.recoveryKey)
      pendingSessionPause.current = null
      sessionPauseGeneration.current += 1
    } else invalidateSessionPause()
    clearComposerAttachments()
    pendingSubmission.current = null
    pendingConfirmation.current = null
    pendingSupportRequest.current = null
    pendingClaimCreation.current = null
    pendingExternalService.current = null
    latestEvidenceRevision.current = 0
    latestEvidenceItems.current = []
    evidenceHasLocalMutation.current = false
    evidenceClaimId.current = null
    evidencePreviewFiles.current.clear()
    replaceActiveClaimContext(null, null, { preserveSessionPause: true })
    commitMessages([])
    setForm({})
    setContentsItems([])
    setDynamicForm(null)
    setNextStep(null)
    setHandoff(null)
    setAssistanceReplyReview(null)
    setEvidenceItems([])
    setEvidenceLoadStatus('idle')
    setEvidenceSyncNotice('')
    setResumeContext(null)
    setRecoveryFailure(null)
    setExpandedConversationPanels({})
    setExternalCapabilitiesOpen(false)
    setExternalServiceInteraction({
      claimId: null,
      consentChecked: false,
      error: null,
    })
    setSelectedHistoryClaimId(null)
    setDetailsOpen(true)
    setDetailsTab('summary')
    setWorkspaceView('chat')
    setMobileView('chat')
    setDraftWorkspaceActive(stayInWorkspace)
    setWorkspaceActive(stayInWorkspace)
    setDraft('')
    setError('')
    setFailedMessage(null)
    setPendingMessage(null)
    activeTurnProgressRef.current = null
    setActiveTurnProgress(null)
    setMessageActivities({})
    setStatus('idle')
    setPageState('home')
    const nextPath = stayInWorkspace ? '/claims/new' : '/'
    if (globalThis.location?.pathname !== nextPath) {
      globalThis.history?.pushState({ northwindRoute: 'home' }, '', nextPath)
    }
  }

  async function startNewChat({ stayInWorkspace = false } = {}) {
    if (isBusy || pendingSessionPause.current?.inFlight) return

    const currentClaim = activeClaimRef.current
    const currentSessionId = activeSessionIdRef.current
    const canResume = nextStep?.can_resume ?? currentClaim?.customer_next_step?.can_resume
    const activeSessionMatches = currentClaim?.active_session_id === undefined
      || currentClaim.active_session_id === currentSessionId
    const sessionNeedsPause = Boolean(
      currentClaim
      && currentSessionId
      && activeSessionMatches
      && canResume !== false
      && currentClaim.workflow_state !== 'created'
      && currentClaim.external_claim?.creation_status !== 'created',
    )
    if (!sessionNeedsPause) {
      resetForNewChat(stayInWorkspace)
      return
    }

    const fingerprint = `${currentClaim.claim_id}:${currentSessionId}:${currentClaim.revision}`
    const contextKey = currentPauseContextKey()
    const identityKey = currentClaimantIdentityKey()
    let pauseRequest = pendingSessionPause.current
    if (
      !pauseRequest
      || pauseRequest.fingerprint !== fingerprint
      || pauseRequest.contextKey !== contextKey
      || pauseRequest.stayInWorkspace !== stayInWorkspace
    ) {
      sessionPauseGeneration.current += 1
      let settle
      pauseRequest = {
        fingerprint,
        idempotencyKey: requestId('pause-session'),
        generation: sessionPauseGeneration.current,
        contextKey,
        identityKey,
        recoveryKey: sessionPauseRecoveryKey(identityKey, currentClaim.claim_id),
        stayInWorkspace,
        inFlight: false,
        settled: new Promise((resolve) => { settle = resolve }),
        settle,
      }
    }
    pauseRequest.inFlight = true
    pendingSessionPause.current = pauseRequest
    setError('')
    setStatus('pausing-session')

    try {
      const paused = await pauseClaimSession({
        claimId: currentClaim.claim_id,
        sessionId: currentSessionId,
        revision: currentClaim.revision,
        idempotencyKey: pauseRequest.idempotencyKey,
      })
      if (!isSessionPauseCurrent(pauseRequest)) {
        rememberDeferredSessionPause(pauseRequest)
        return
      }
      forgetDeferredSessionPause(pauseRequest)
      rememberClaimInHistory(paused.claim)
      resetForNewChat(stayInWorkspace, pauseRequest)
    } catch (requestError) {
      const mayMutateCurrentNavigation = isSessionPauseCurrent(pauseRequest)
      if (!mayMutateCurrentNavigation && !isSessionPauseIdentityCurrent(pauseRequest)) return
      pauseRequest.inFlight = false

      if (!(requestError instanceof ApiRequestError) || !Number.isInteger(requestError.status)) {
        let latestClaim = null
        try {
          latestClaim = await getClaim(currentClaim.claim_id)
        } catch {
          // Retain the current projection and original idempotency key. A retry safely
          // replays a pause that may already have reached the service.
        }
        if (!isSessionPauseIdentityCurrent(pauseRequest)) return
        if (!mayMutateCurrentNavigation) {
          if (latestClaim?.active_session_id === currentSessionId) {
            forgetDeferredSessionPause(pauseRequest)
          } else {
            rememberDeferredSessionPause(pauseRequest)
          }
          return
        }
        if (!isSessionPauseCurrent(pauseRequest)) return
        if (latestClaim) {
          const pauseWasSaved = latestClaim.active_session_id === null
            && Boolean(latestClaim.incomplete_context)
          if (pauseWasSaved) {
            rememberClaimInHistory(latestClaim)
            resetForNewChat(stayInWorkspace, pauseRequest)
            return
          }
          applyClaimSnapshot(latestClaim)
        }
        setError('We could not confirm that your progress was saved because the claim service did not respond. Your current conversation is still open. Check your connection and select New chat again; the same save request will not create a duplicate.')
        setStatus('error')
        return
      }

      if (!mayMutateCurrentNavigation) {
        forgetDeferredSessionPause(pauseRequest)
        return
      }
      if (requestError.code === 'REVISION_CONFLICT') {
        let latestClaim = null
        try {
          latestClaim = await getClaim(currentClaim.claim_id)
        } catch {
          // Keep the last visible projection when the refresh is also unavailable.
        }
        if (!isSessionPauseCurrent(pauseRequest)) return
        if (latestClaim) applyClaimSnapshot(latestClaim)
        setError('We could not save your place because this report changed in another session. Your current conversation is still open. Review the latest details and select New chat again.')
      } else {
        setError(`${requestError.message || 'We could not save your place before starting a new conversation.'} Your current conversation is still open. Review the report and select New chat again.`)
      }
      setStatus('error')
    } finally {
      pauseRequest.inFlight = false
      pauseRequest.settle?.()
    }
  }

  function confirmProposedFields() {
    return confirmFields([
      ...proposedFields.map(([fieldCode]) => fieldCode),
      ...(proposedContentsItems.length > 0 ? ['contents.items'] : []),
    ])
  }

  async function confirmFields(fieldCodes) {
    if (!claim || fieldCodes.length === 0 || isBusy) return
    setError('')
    setStatus('confirming')
    try {
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
      setContentsItems(response.confirmed_contents_items || contentsItems)
      setDynamicForm(response.dynamic_form || null)
      setClaimRevision(response.revision, response.primary_action)
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

  function saveFieldCorrection(fieldCode, field) {
    return saveFieldValue(fieldCode, field, editValue)
  }

  // Saves one corrected value; a corrected suggestion counts as checked.
  // Returns whether the value is now stored.
  async function saveFieldValue(fieldCode, field, rawValue) {
    // The card sends typed values (Yes/No as booleans); the details panel sends text.
    const value = typeof rawValue === 'string' ? rawValue.trim() : rawValue
    if (!claim || value === '' || value === null || value === undefined || isBusy) return false
    if (
      JSON.stringify(value) === JSON.stringify(field.value)
      || (typeof value === 'string' && value === fieldValueText(field))
    ) {
      setEditingField(null)
      return true
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
      let updatedDynamicForm = update.dynamic_form || null
      let updatedPrimaryAction = update.primary_action

      if (field.status === 'proposed') {
        const confirmation = await confirmClaimFields({
          claimId: claim.claim_id,
          revision,
          fieldCodes: [fieldCode],
        })
        revision = confirmation.revision
        updatedForm = { ...updatedForm, ...confirmation.confirmed_fields }
        updatedNextStep = confirmation.customer_next_step
        updatedDynamicForm = confirmation.dynamic_form || null
        updatedPrimaryAction = confirmation.primary_action
      }

      setForm(updatedForm)
      setClaimRevision(revision, updatedPrimaryAction)
      setNextStep(updatedNextStep)
      setDynamicForm(updatedDynamicForm)
      setEditingField(null)
      setStatus('idle')
      return true
    } catch (requestError) {
      showError(requestError)
      return false
    }
  }

  async function requestSupport() {
    if (!claim || isBusy || handoff) return
    setError('')
    setAssistanceReplyReview(null)
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
      setClaimRevision(response.revision, response.primary_action)
      setNextStep(response.customer_next_step)
      setHandoff(response.handoff)
      pendingSupportRequest.current = null
      setStatus('idle')
    } catch (requestError) {
      showError(requestError)
    }
  }

  async function submitAgreementAndCreate(confirmations) {
    if (!claim || isBusy || !claim.submission_agreement) return

    const actionCode = claim.primary_action?.action_code
    const canAccept = actionCode === 'claimant.review_agreement'
    const alreadyAccepted = actionCode === 'claimant.create_claim'

    if (!canAccept && !alreadyAccepted) return

    setError('')
    setAgreementSubmissionError(null)
    setStatus('creating-claim')

    let submissionStage = canAccept ? 'acceptance' : 'creation'
    let submissionRevision = claim.revision

    try {
      let revision = submissionRevision

      if (canAccept) {
        const agreement = claim.submission_agreement

        if (
          !pendingAgreementAcceptance.current
          || pendingAgreementAcceptance.current.claimId !== claim.claim_id
          || pendingAgreementAcceptance.current.revision !== claim.revision
        ) {
          pendingAgreementAcceptance.current = {
            claimId: claim.claim_id,
            revision: claim.revision,
            idempotencyKey: requestId('agreement-acceptance'),
          }
        }

        const operation = pendingAgreementAcceptance.current
        const accepted = await acceptClaimAgreement({
          claimId: claim.claim_id,
          revision: operation.revision,
          agreementId: agreement.agreement_id,
          version: agreement.version,
          confirmations,
          idempotencyKey: operation.idempotencyKey,
        })

        revision = accepted.revision
        submissionRevision = accepted.revision

        setClaim((current) => ({
          ...current,
          revision: accepted.revision,
          submission_agreement: accepted.agreement,
          primary_action: accepted.primary_action,
        }))
        setNextStep(accepted.customer_next_step)
        pendingAgreementAcceptance.current = null
        submissionStage = 'creation'
      }

      if (!pendingClaimCreation.current) {
        pendingClaimCreation.current = {
          idempotencyKey: requestId('claim-creation'),
        }
      }

      const response = await createExternalClaim({
        claimId: claim.claim_id,
        revision,
        idempotencyKey: pendingClaimCreation.current.idempotencyKey,
      })

      setClaim((current) => ({
        ...current,
        revision: response.revision,
        external_claim: response.external_claim,
        external_service_action: response.external_service_action,
        primary_action: response.primary_action,
      }))
      setNextStep(response.customer_next_step)
      pendingClaimCreation.current = null
      pendingAgreementAcceptance.current = null
      setAgreementSubmissionError(null)
      setStatus('idle')
    } catch (requestError) {
      let visibleFailure = submissionFailure(requestError)

      if (!isDefinitiveSubmissionRefusal(requestError)) {
        try {
          const currentClaim = await getClaim(claim.claim_id)
          const snapshotApplied = applyClaimSnapshot(currentClaim, {
            minimumRevision: submissionRevision,
          })

          if (!snapshotApplied) {
            visibleFailure = submissionReconciliationFailure()
          } else if (currentClaim.external_claim?.creation_status === 'created') {
            pendingClaimCreation.current = null
            pendingAgreementAcceptance.current = null
            setAgreementSubmissionError(null)
            setError('')
            setStatus('idle')
            return
          } else if (
            submissionStage === 'acceptance'
            && currentClaim.primary_action?.action_code === 'claimant.create_claim'
          ) {
            pendingAgreementAcceptance.current = null
            setAgreementSubmissionError(null)
            setError('')
            setStatus('idle')
            return
          } else {
            const expectedPendingAction = submissionStage === 'acceptance'
              ? 'claimant.review_agreement'
              : 'claimant.create_claim'
            if (currentClaim.primary_action?.action_code !== expectedPendingAction) {
              visibleFailure = submissionReconciliationFailure()
            }
          }
        } catch {
          visibleFailure = submissionReconciliationFailure()
        }
      }

      setAgreementSubmissionError({
        claimId: claim.claim_id,
        ...visibleFailure,
      })
      showError(requestError)
    }
  }

  async function createConfirmedClaim() {
    if (
      !claim
      || isBusy
      || claim.primary_action?.action_code !== 'claimant.create_claim'
      || !claim.primary_action.available
      || Number(claim.primary_action.claim_revision) !== Number(claim.revision)
    ) return
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
        primary_action: response.primary_action,
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
    const primaryAction = claim?.primary_action
    const needsConsent = primaryAction?.required_inputs?.includes('claimant_consent')
    if (
      !claim
      || !action
      || primaryAction?.action_type !== 'external_service'
      || !REQUESTABLE_EXTERNAL_ACTIONS.has(primaryAction.action_code)
      || !primaryAction.available
      || primaryAction.target_ref !== action.service_identity
      || Number(primaryAction.claim_revision) !== Number(claim.revision)
      || isBusy
    ) return
    if (needsConsent && !serviceConsentChecked) return

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
      if (needsConsent) {
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
          primary_action: consent.primary_action,
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
        primary_action: routed.primary_action,
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
        setContentsItems(current.contents_items || [])
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

  async function decideMessageExternalService(action, decision) {
    if (!claim || !action?.offer_id || isBusy) return
    if (decision === 'grant' && !offerConsentChecks[action.offer_id]) return
    setOfferErrors((current) => ({ ...current, [action.offer_id]: null }))
    setStatus('granting-service-consent')
    try {
      const response = await decideExternalServiceOffer({
        claimId: claim.claim_id,
        offerId: action.offer_id,
        revision: claim.revision,
        decision,
      })
      latestRevision.current = response.revision
      setClaim((current) => ({
        ...current,
        revision: response.revision,
        primary_action: response.primary_action,
      }))
      commitMessages((current) => current.map((message) => (
        message.message_id === action.agent_message_id
          ? {
              ...message,
              message_actions: (message.message_actions || []).map((candidate) => (
                candidate.offer_id === action.offer_id ? response.action : candidate
              )),
            }
          : message
      )))
      setNextStep(response.customer_next_step)
      setOfferConsentChecks((current) => ({ ...current, [action.offer_id]: false }))
      setStatus('idle')
    } catch (requestError) {
      setOfferErrors((current) => ({ ...current, [action.offer_id]: requestError }))
      setStatus('idle')
    }
  }

  async function loadSavedReports() {
    if (isBusy) return
    setError('')
    setClaimHistoryError('')
    setStatus('loading-reports')
    try {
      replaceClaimHistory(await fetchClaimHistory())
      setStatus('idle')
    } catch (requestError) {
      setClaimHistoryError(requestError.message || 'The Claim service did not respond.')
      showError(requestError)
    }
  }

  async function resumeSavedReport(claimId) {
    if (isBusy) return
    setError('')
    cancelComposerDraftAttachments()
    setStatus('resuming')
    const transition = beginClaimTransition(claimId)
    try {
      const savedClaim = await getClaim(claimId)
      const canResume = savedClaim.can_resume ?? savedClaim.customer_next_step?.can_resume
      if (canResume === false) {
        rememberClaimInHistory(savedClaim)
        openClaimFeatures(savedClaim)
        setStatus('idle')
        return
      }
      const session = await resumeClaimSession({ claimId })
      const current = await getClaim(claimId)
      const conversation = await getClaimMessages(claimId, session.session_id)
      clearComposerAttachments()
      replaceActiveClaimContext(current, session.session_id)
      if (session.model_profile_id) setSelectedModel(session.model_profile_id)
      commitMessages(conversation.items)
      setRecoveryFailure(null)
      setForm(current.form)
      setContentsItems(current.contents_items || [])
      setDynamicForm(current.dynamic_form || null)
      setNextStep(current.customer_next_step)
      setHandoff(current.handoff || null)
      setResumeContext({
        ...session.resume,
        resumed_at: session.started_at,
        resumed_after_message_id: orderMessages(conversation.items).at(-1)?.message_id || null,
        has_resume_boundary: true,
      })
      setWorkspaceActive(true)
      setPageState('home')
      setStatus('idle')
    } catch (requestError) {
      if (!hasClaimantAccessToken() && isPermanentAnonymousResumeFailure(requestError)) {
        setClaimHistory(forgetAnonymousConversation(claimId))
        setError('This conversation is no longer available in this browser session, so it was removed from history.')
        setStatus('error')
      } else if (!hasClaimantAccessToken()) {
        setError(`${requestError.message || 'We could not reopen this conversation.'} The conversation is still saved in history. Try opening it again.`)
        setStatus('error')
      } else {
        showError(requestError)
      }
    } finally {
      finishClaimTransition(transition)
    }
  }

  function openConversationHistorySidebar() {
    setConversationHistoryOpen(true)
  }

  function closeConversationHistorySidebar() {
    setConversationHistoryOpen(false)
  }

  function startHomepageConversation() {
    closeConversationHistorySidebar()
    startNewChat()
  }

  function resumeHomepageConversation(claimId) {
    closeConversationHistorySidebar()
    const savedClaim = claimHistory?.find((item) => item.claim_id === claimId)
      || (claim?.claim_id === claimId ? claim : null)
    const canResume = savedClaim?.can_resume ?? savedClaim?.customer_next_step?.can_resume
    if (savedClaim && canResume === false) {
      setError('')
      openClaimFeatures(savedClaim)
      return
    }
    if (claimId === claim?.claim_id && sessionId) {
      setError('')
      setWorkspaceActive(true)
      setPageState('home')
      const claimPath = `/claims/${claim.claim_id}`
      if (globalThis.location?.pathname !== claimPath) {
        globalThis.history?.pushState({ northwindRoute: 'home' }, '', claimPath)
      }
      return
    }
    resumeSavedReport(claimId)
  }

  function continueReportFromClaimHistory(claimId) {
    // Claim history can be open as a workspace utility view; leave it for the conversation
    // before taking the same resume path as conversation history.
    setWorkspaceView('chat')
    setSelectedHistoryClaimId(null)
    resumeHomepageConversation(claimId)
  }

  async function signIn(event) {
    event.preventDefault()
    invalidateSessionPause({ identityChanged: true })
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
          applyClaimSnapshot(promoted)
          forgetAnonymousConversation(claim.claim_id)
        } catch (promotionError) {
          if (!(promotionError instanceof ApiRequestError && promotionError.status === 404)) throw promotionError
        }
      }
      setAccount(await getAuthenticatedAccount())
      setClaimHistory(null)
      setWorkspaceActive(true)
      setWorkspaceView('chat'); setPage('home'); setAuthStatus('idle')
    } catch (requestError) {
      setClaimantAccessToken(null)
      setAuthError(requestError.message)
      setAuthStatus('idle')
    }
  }

  async function signUp(event) {
    event.preventDefault()
    invalidateSessionPause({ identityChanged: true })
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
          applyClaimSnapshot(promoted)
          forgetAnonymousConversation(claim.claim_id)
        } catch (promotionError) {
          if (!(promotionError instanceof ApiRequestError && promotionError.status === 404)) throw promotionError
        }
      }
      setAccount(await getAuthenticatedAccount())
      setClaimHistory(null)
      setWorkspaceActive(true)
      setWorkspaceView('chat'); setPage('home'); setAuthStatus('idle')
    } catch (requestError) {
      setClaimantAccessToken(null)
      setAuthError(requestError.message)
      setAuthStatus('idle')
    }
  }

  async function signOut() {
    invalidateSessionPause({ identityChanged: true })
    setAuthStatus('loading'); setAuthError('')
    try { await logoutClaimant() } catch (requestError) { setAuthError(requestError.message) }
    autoFillEditor.reset()
    setAccount(null)
    setClaimHistory(readAnonymousConversationHistory())
    setClaimHistoryError('')
    setSelectedHistoryClaimId(null)
    confirmedClaimProjections.current.clear()
    replaceActiveClaimContext(null, null)
    commitMessages([])
    setForm({})
    setContentsItems([])
    setDynamicForm(null)
    setNextStep(null)
    setHandoff(null)
    clearComposerAttachments()
    setDraft('')
    setError('')
    setFailedMessage(null)
    setRecoveryFailure(null)
    setPendingMessage(null)
    activeTurnProgressRef.current = null
    setActiveTurnProgress(null)
    setStatus('idle')
    setEvidenceItems([])
    setResumeContext(null)
    setExpandedConversationPanels({})
    setWorkspaceView('chat')
    setMobileView('chat')
    setWorkspaceActive(false)
    setPage('home', { replace: true })
    setAuthStatus('idle')
  }

  async function openSavedClaims() {
    setSelectedHistoryClaimId(null)
    setPage('claim-history')
    await loadSavedReports()
  }

  function openClaimHistory() {
    invalidateSessionPause()
    setSelectedHistoryClaimId(null)
    if (isWorkspaceActive) {
      setWorkspaceView('history')
      setMobileView('chat')
    } else {
      setPage('claim-history')
    }
    if (account) loadSavedReports().catch(() => {})
  }

  // The account pages show these Claim record views whenever the workspace is inactive, even
  // while a conversation is still loaded, so navigation follows isWorkspaceActive as they do.
  function openClaimFeatures(selectedClaim) {
    setSelectedHistoryClaimId(selectedClaim.claim_id)
    if (isWorkspaceActive) {
      setWorkspaceView('claim-features')
      setMobileView('chat')
    } else {
      setPageState('claim-features')
      globalThis.history?.pushState(
        { northwindRoute: 'claim-features' },
        '',
        `/account/claims/${encodeURIComponent(selectedClaim.claim_id)}`,
      )
    }
  }

  function openClaimEvidence() {
    if (!selectedHistoryClaim) return
    if (isWorkspaceActive) {
      setWorkspaceView('claim-evidence')
      setMobileView('chat')
    } else {
      setPage('claim-evidence')
    }
  }

  function openCurrentClaimDocuments() {
    setWorkspaceView('chat')
    setDetailsOpen(true)
    setDetailsTab('documents')
    setMobileView('details')
  }

  function handleDetailsTabKeyDown(event, currentTab) {
    const tabs = ['summary', 'documents']
    const currentIndex = tabs.indexOf(currentTab)
    let nextIndex
    if (event.key === 'ArrowRight') nextIndex = (currentIndex + 1) % tabs.length
    else if (event.key === 'ArrowLeft') nextIndex = (currentIndex - 1 + tabs.length) % tabs.length
    else if (event.key === 'Home') nextIndex = 0
    else if (event.key === 'End') nextIndex = tabs.length - 1
    else return
    event.preventDefault()
    const nextTab = tabs[nextIndex]
    setDetailsTab(nextTab)
    detailsTabRefs.current[nextTab]?.focus()
  }

  function leaveWorkspaceUtility() {
    setWorkspaceView('chat')
    setSelectedHistoryClaimId(null)
    setPage('home')
  }

  function navigateBackFromWorkspaceUtility() {
    if (workspaceView === 'claim-evidence') {
      setWorkspaceView('claim-features')
      return
    }
    if (workspaceView === 'claim-features') {
      openClaimHistory()
      return
    }
    leaveWorkspaceUtility()
  }

  function handleWorkspaceHeaderBack() {
    if (workspaceView !== 'chat') {
      navigateBackFromWorkspaceUtility()
      return
    }
    returnToLanding()
  }

  function openProfileFromWorkspace(section = null) {
    if (!account) {
      setPage('login')
      return
    }
    const returnClaimId = claim?.claim_id || null
    setProfileReturnClaimId(returnClaimId)
    setProfileSection(section)
    setWorkspaceView('chat')
    setMobileView('chat')
    setWorkspaceActive(false)
    setPageState('account')
    const nextPath = profilePathForSection(section)
    if (globalThis.location?.pathname !== nextPath) {
      globalThis.history?.pushState(
        { northwindRoute: 'account', profileReturnClaimId: returnClaimId },
        '',
        nextPath,
      )
    }
  }

  function leaveProfilePage() {
    if (profileReturnClaimId && claim?.claim_id === profileReturnClaimId) {
      setProfileReturnClaimId(null)
      setWorkspaceView('chat')
      setMobileView('chat')
      setWorkspaceActive(true)
      setPageState('home')
      const claimPath = `/claims/${claim.claim_id}`
      if (globalThis.location?.pathname !== claimPath) {
        globalThis.history?.pushState({ northwindRoute: 'home' }, '', claimPath)
      }
      return
    }
    setPage('home')
  }

  function returnToLanding() {
    clearComposerAttachments()
    pendingSubmission.current = null
    setDraft('')
    setError('')
    setFailedMessage(null)
    setPendingMessage(null)
    setWorkspaceView('chat')
    setMobileView('chat')
    setWorkspaceActive(false)
    setPageState('home')
    if (globalThis.location?.pathname !== '/') {
      globalThis.history?.pushState({ northwindRoute: 'home' }, '', '/')
    }
  }

  function openProfileSection(section) {
    setProfileSection(section)
    setPageState('account')
    const nextPath = profilePathForSection(section)
    if (globalThis.location?.pathname !== nextPath) {
      globalThis.history?.pushState({
        northwindRoute: 'account',
        profileSection: section,
        profileReturnClaimId,
      }, '', nextPath)
    }
  }


  async function addPayoutDestination({ accountType, accountNumber, bankName, accountHolderName }) {
    if (!account) {
      setPage('login')
      throw new ApiRequestError('Log in before saving payout details.', {
        code: 'AUTHENTICATION_REQUIRED',
        status: 401,
      })
    }
    setStatus('saving-payment-destination')
    try {
      const created = await createPaymentDestination({
        accountType,
        accountNumber,
        bankName,
        accountHolderName,
        idempotencyKey: requestId('payment-destination'),
      })
      setPaymentDestinationState((current) => ({
        ...current,
        status: 'ready',
        error: '',
        items: [
          created,
          ...current.items.filter(
            (item) => item.payment_destination_id !== created.payment_destination_id,
          ),
        ],
      }))
      return created
    } finally {
      setStatus('idle')
    }
  }

  async function continuePayoutContact({ paymentDestinationId, contactPreference }) {
    const primaryAction = claim?.primary_action
    if (
      !claim
      || !account
      || isBusy
      || primaryAction?.action_code !== 'claimant.review_payout_contact'
      || !primaryAction.available
      || Number(primaryAction.claim_revision) !== Number(claim.revision)
    ) {
      throw new ApiRequestError(
        account
          ? 'The Claim changed before payout details could be saved. Reload and try again.'
          : 'Log in before saving payout details.',
        {
          code: account ? 'REVISION_CONFLICT' : 'AUTHENTICATION_REQUIRED',
          status: account ? 409 : 401,
          retryable: Boolean(account),
        },
      )
    }

    setStatus('saving-payout-contact')
    try {
      const response = await selectClaimPayoutContact({
        claimId: claim.claim_id,
        revision: claim.revision,
        paymentDestinationId,
        contactPreference,
        idempotencyKey: requestId('payout-contact'),
      })
      rememberClaimRevision(response.revision)
      setClaim((current) => current
        ? {
          ...current,
          revision: response.revision,
          payment_destination_id: response.payment_destination_id,
          form: {
            ...current.form,
            'claimant.contact_preference': response.contact_preference,
          },
          customer_next_step: response.customer_next_step,
          primary_action: response.primary_action,
        }
        : current)
      setForm((current) => ({
        ...current,
        'claimant.contact_preference': response.contact_preference,
      }))
      setNextStep(response.customer_next_step)

      try {
        const snapshot = await getClaim(claim.claim_id)
        if (!applyClaimSnapshot(snapshot, { minimumRevision: response.revision })) {
          throw new ApiRequestError(
            'Northwind saved your details but the latest Claim readback is not available yet.',
            { code: 'STALE_READBACK', retryable: true },
          )
        }
        setRealtimeHealth('healthy')
        setWorkspaceView('agreement')
      } catch (readbackError) {
        setRealtimeHealth('stale')
        throw readbackError
      }
      return response
    } catch (requestError) {
      if (
        requestError instanceof ApiRequestError
        && requestError.status === 409
        && claim?.claim_id
      ) {
        try {
          const current = await getClaim(claim.claim_id)
          applyClaimSnapshot(current)
        } catch {
          setRealtimeHealth('stale')
        }
      }
      throw requestError
    } finally {
      setStatus('idle')
    }
  }

  function conversationPanelExpanded(panel) {
    if (!claim?.claim_id) return false
    return Boolean(expandedConversationPanels[`${claim.claim_id}:${panel}`])
  }

  function handleMessageListScroll(event) {
    const messageList = event.currentTarget
    followLatestMessages.current = (
      messageList.scrollHeight - messageList.scrollTop - messageList.clientHeight <= 1
    )
  }

  function closeExternalCapabilities() {
    restoreCapabilityTriggerFocus.current = true
    setExternalCapabilitiesOpen(false)
  }

  function toggleConversationPanel(panel) {
    if (!claim?.claim_id) return
    const panelKey = `${claim.claim_id}:${panel}`
    setExpandedConversationPanels((current) => ({
      ...current,
      [panelKey]: !current[panelKey],
    }))
  }

  function openClaimDetailsFromConversation() {
    setDetailsOpen(true)
    setMobileView('details')
  }

  function renderConversationAction() {
    if (conversationActionKind === 'external-service' && claim?.external_service_action) {
      return (
        <ExternalServiceAction
          key={conversationAction.identity}
          action={claim.external_service_action}
          consentChecked={serviceConsentChecked}
          setConsentChecked={setServiceConsentChecked}
          onRequest={requestVehicleAssessment}
          status={status}
          error={serviceError}
          expanded={conversationPanelExpanded('external-service')}
          onToggle={() => toggleConversationPanel('external-service')}
        />
      )
    }
    if (conversationActionKind === 'review-details') {
      const reviewItemCount = conversationAction.requiredItems.length
      return (
        <ConversationActionCard
          key={conversationAction.identity}
          icon="≡"
          title="Review claim details"
          description={`${reviewItemCount} ${reviewItemCount === 1 ? 'detail needs' : 'details need'} your confirmation before we continue.`}
          status={`${reviewItemCount} to review`}
          onClick={openClaimDetailsFromConversation}
        />
      )
    }
    if (conversationActionKind === 'payout-contact') {
      return (
        <PayoutContactPanel
          key={`${claim.claim_id}:${conversationAction.identity}`}
          account={account}
          claim={claim}
          destinations={paymentDestinationState.items}
          loading={paymentDestinationState.status === 'loading'}
          loadError={paymentDestinationState.error}
          busy={isBusy}
          onAddDestination={addPayoutDestination}
          onContinue={continuePayoutContact}
          onManageContact={() => openProfileFromWorkspace('personal-details')}
          onLogin={() => setPage('login')}
        />
      )
    }
    if (conversationActionKind === 'review-agreement') {
      return (
        <ConversationActionCard
          key={conversationAction.identity}
          icon="→"
          title="Agreement & confirmation"
          description="Your payout destination and contact preference are saved. Continue to Step 4."
          status="Step 4 ready"
          onClick={() => setWorkspaceView('agreement')}
        />
      )
    }
    if (conversationActionKind === 'create-claim') {
      return (
        <ConversationActionCard
          key={conversationAction.identity}
          icon="✓"
          title="Create your claim"
          description="Your required details are complete and ready to send to Northwind."
          status={status === 'creating-claim' ? 'Creating…' : 'Ready'}
          onClick={createConfirmedClaim}
          disabled={isBusy}
        />
      )
    }
    return null
  }

  const isUrgentSupport = handoff?.support_need === 'urgent'
  const isProfilePage = page === 'account'
  const isStandaloneClaimHistory = !isWorkspaceActive && page === 'claim-history'
  const profileDisplayName = account?.profile?.display_name || 'Log in'
  const profileEmail = account?.profile?.email || 'Profile and preferences'
  const profileNamePreview = middleEllipsisLayoutParts(profileDisplayName, PROFILE_NAME_PREVIEW_LENGTH)
  const profileButtonLabel = account
    ? `Open Profile for ${profileDisplayName} (${profileEmail})`
    : 'Open Profile and preferences'

  function openClaimWorkspacePage(destination) {
    if (destination === 'overview') {
      setWorkspaceView('chat')
      setMobileView('chat')
      return
    }
    if (destination === 'documents') {
      openCurrentClaimDocuments()
      return
    }
    if (destination === 'history') {
      openClaimHistory()
      return
    }
    if (destination === 'privacy') {
      setWorkspaceView('privacy')
      setMobileView('chat')
      return
    }
    setWorkspaceView('external-services')
    setMobileView('chat')
  }

  const showsClaimDetails = workspaceView === 'chat' || workspaceView === 'external-services'
  const reviewRequirements = claimReviewRequirements(dynamicForm)
  const toProvideCount = new Set([
    ...reviewRequirements.missingRequiredNow,
    ...reviewRequirements.pendingLater,
  ]).size
  const claimDetailsExpanded = detailsOpen && showsClaimDetails

  return (
    <div className={`customer-app ${!isWorkspaceActive && page === 'home' ? 'entry-shell' : ''} ${isWorkspaceActive && !['login', 'register'].includes(page) ? 'workspace-shell' : ''} ${isProfilePage ? 'is-profile-page' : ''} ${isStandaloneClaimHistory ? 'is-claim-history-page' : ''}`}>
      <header className={`product-header ${isWorkspaceActive && !['login', 'register'].includes(page) ? 'is-intake-header' : ''} ${isStandaloneClaimHistory ? 'is-claim-history-header' : ''}`}>
        <div className="header-leading">
          <a className="brand" href="/" onClick={(event) => { event.preventDefault(); setPage('home') }} aria-label="Northwind home">
            <span className="brand-mark">N</span>
            <span>Northwind Insurance</span>
          </a>
          {isWorkspaceActive && !['login', 'register'].includes(page) && (
            <button
              className="header-back-to-start"
              type="button"
              aria-label={workspaceView === 'chat' ? 'Back to start' : 'Back to previous page'}
              onClick={handleWorkspaceHeaderBack}
              disabled={isBusy}
            >
              <span aria-hidden="true">←</span>
              <span>Back</span>
            </button>
          )}
        </div>
        {!isWorkspaceActive && page === 'home' && (
          <nav className="entry-header-actions" aria-label="Account">
            <button className="entry-header-link" type="button" onClick={() => setPage(account ? 'account' : 'login')}>
              {account ? 'Profile' : 'Log in'}
            </button>
            {!account && (
              <button className="entry-header-account" type="button" onClick={() => setPage('register')}>
                Sign up
              </button>
            )}
          </nav>
        )}
        {!isWorkspaceActive && page !== 'home' && page !== 'how-it-works' && (
          <button
            className="login-button"
            type="button"
            onClick={() => isProfilePage ? leaveProfilePage() : setPage(account ? 'account' : 'login')}
          >
            {isProfilePage ? 'Back' : account ? 'Profile' : 'Log in'}
          </button>
        )}
        {isWorkspaceActive && claim && !['login', 'register'].includes(page) && (
          <div className="header-actions">
            {status === 'requesting-support' || handoff ? (
              <span className="header-assistance-chip">
                <span aria-hidden="true">●</span>
                {assistanceState?.title || 'Staff assistance active'}
              </span>
            ) : (
              <button className="support-button" type="button" onClick={requestSupport} disabled={isBusy}>
                Staff assistance
              </button>
            )}
          </div>
        )}
      </header>

      {!isWorkspaceActive && page === 'home' && (
        <ConversationHistorySidebar
          account={account}
          activeClaimId={claim?.claim_id || null}
          busy={isBusy}
          conversations={homepageConversationReports}
          error={claimHistoryError}
          isOpen={conversationHistoryOpen}
          loading={status === 'loading-reports'}
          onClose={closeConversationHistorySidebar}
          onLogin={() => setPage('login')}
          onNewConversation={startHomepageConversation}
          onOpen={openConversationHistorySidebar}
          onRetry={loadSavedReports}
          onSelect={resumeHomepageConversation}
        />
      )}

      {!isWorkspaceActive && page === 'how-it-works' ? (
        <main className="how-it-works-page">
          <section className="how-it-works-card" aria-labelledby="how-it-works-title">
            <button className="back-link" type="button" onClick={() => setPage('home')}>← Back</button>
            <p className="eyebrow">A calmer way to start</p>
            <h1 id="how-it-works-title">How this works</h1>
            <p>Tell us what happened in your own words. You do not need to know the right insurance terms or follow a fixed questionnaire.</p>
            <p>Our claims assistant keeps track of the details, asks only for what is still needed, and explains the next step clearly. You can start without an account and log in later if you want to save your progress.</p>
          </section>
        </main>
      ) : isStandaloneClaimHistory ? (
        <main className="claim-history-page">
          {account ? (
            <section className="claim-history-page-content" aria-labelledby="claim-history-page-title">
              <nav className="claim-history-breadcrumb" aria-label="Breadcrumb">
                <a
                  href="/profile"
                  onClick={(event) => {
                    event.preventDefault()
                    setPage('account')
                  }}
                >
                  Account
                </a>
                <span aria-hidden="true">/</span>
                <span aria-current="page">Claims</span>
              </nav>
              <header className="claim-history-hero">
                <div className="claim-history-hero-copy">
                  <p className="claim-history-eyebrow">Your claims</p>
                  <h1 id="claim-history-page-title">Claim history</h1>
                  <p>Track open claims and review your previous submissions.</p>
                </div>
                <button className="claim-history-start-action" type="button" onClick={startNewChat}>
                  <span aria-hidden="true">＋</span>
                  Start a new claim
                </button>
              </header>
              <ClaimHistory
                claims={claimHistory}
                error={claimHistoryError}
                loading={claimHistory === null && !claimHistoryError}
                refreshing={status === 'loading-reports'}
                onRetry={loadSavedReports}
                onSelect={openClaimFeatures}
                onStartClaim={startNewChat}
                onContinueReport={continueReportFromClaimHistory}
                showEmptyStartAction={false}
              />
            </section>
          ) : (
            <p className="claim-history-page-checking" role="status">Checking your account…</p>
          )}
        </main>
      ) : !isWorkspaceActive && ['claim-features', 'claim-evidence'].includes(page) ? (
        <main className="evidence-history-page">
          {account ? (
            <section className="evidence-history-page-content" aria-labelledby="account-claim-view-title">
              <button
                className="back-link"
                type="button"
                onClick={page === 'claim-evidence'
                  ? () => setPage('claim-features')
                  : openClaimHistory}
              >
                <span className="back-link-arrow" aria-hidden="true">←</span>
                {page === 'claim-evidence'
                  ? 'Back to Claim features'
                  : 'Back to Claim history'}
              </button>
              <p className="eyebrow">Northwind account</p>
              <h1 id="account-claim-view-title">
                {page === 'claim-features' ? 'Claim features' : 'Evidence history'}
              </h1>
              <p>
                {page === 'claim-features'
                  ? 'Review this Claim\'s current status and available information.'
                  : 'Review the files and supporting material recorded for the selected Claim.'}
              </p>
              {page === 'claim-features' && (
                selectedHistoryClaim ? (
                  <ClaimFeatureDirectory claim={selectedHistoryClaim} onOpenEvidence={openClaimEvidence} />
                ) : claimHistory === null && !claimHistoryError ? (
                  <p className="claim-history-state" role="status">Loading this Claim…</p>
                ) : (
                  <div className="claim-history-state is-error" role="alert">
                    <h2>This Claim is no longer available</h2>
                    <p>Return to Claim history and choose a Claim that is available to your account.</p>
                    <button className="secondary-button" type="button" onClick={openClaimHistory}>Return to Claim history</button>
                  </div>
                )
              )}
              {page === 'claim-evidence' && (
                selectedHistoryClaim ? (
                  <EvidenceHistory claimId={selectedHistoryClaim.claim_id} />
                ) : claimHistory === null && !claimHistoryError ? (
                  <p className="claim-history-state" role="status">Loading this Claim…</p>
                ) : (
                  <div className="claim-history-state is-error" role="alert">
                    <h2>This Claim is no longer available</h2>
                    <p>Return to Claim history and choose a Claim that is available to your account.</p>
                    <button className="secondary-button" type="button" onClick={openClaimHistory}>Return to Claim history</button>
                  </div>
                )
              )}
            </section>
          ) : (
            <p className="claim-history-state" role="status">Checking your account…</p>
          )}
        </main>
      ) : !isWorkspaceActive && page === 'files' ? (
        <main className="evidence-history-page">
          {account ? (
            <section className="evidence-history-page-content" aria-labelledby="account-evidence-history-title">
              <button className="back-link" type="button" onClick={() => setPage('account')}>
                <span className="back-link-arrow" aria-hidden="true">←</span>
                Back to account
              </button>
              <p className="eyebrow">Northwind account</p>
              <h1 id="account-evidence-history-title">Evidence history</h1>
              <p>Review files retained across your Northwind claims, including where they came from and their latest processing state.</p>
              <EvidenceHistory currentClaimId={null} />
            </section>
          ) : (
            <p className="evidence-history-state" role="status">Checking your account…</p>
          )}
        </main>
      ) : !isWorkspaceActive && page === 'account' ? (
        <main className="profile-page">
          {account ? (
            <UserProfile
              account={account}
              activeSection={profileSection}
              autoFillChoices={autoFillEditor.choices}
              autoFillDirty={autoFillEditor.dirty}
              autoFillError={autoFillEditor.error}
              autoFillNotice={autoFillEditor.notice}
              autoFillSaving={autoFillEditor.saving}
              controller={profileController}
              onChangeAutoFillChoice={autoFillEditor.changeChoice}
              onOpenClaims={openSavedClaims}
              onSaveAutoFillChoices={autoFillEditor.saveChoices}
              onSelectSection={openProfileSection}
              onSignOut={signOut}
            />
          ) : (
            <p className="profile-loading" role="status">Checking your account…</p>
          )}
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
              <a href={WORKBENCH_URL}>Employee access</a>
            </div>
          </section>
        </main>
      ) : !isWorkspaceActive ? (
        <ClaimEntryPage
          composer={{
            draft,
            setDraft,
            onSubmit: sendMessage,
            busy: isBusy,
            buttonLabel: failedMessage ? 'Retry claim message' : 'Start claim',
            error,
            models: claimantModels,
            selectedModel,
            setSelectedModel,
            attachments,
            onFileSelected: handleFileSelected,
            onRemoveAttachment: removeComposerAttachment,
          }}
          failure={failedMessage && (
            <article className="message message-claimant is-failed" role="alert">
              <p className="message-author">{failedMessage.sender}</p>
              {failedMessage.text && <p>{failedMessage.text}</p>}
              <ClaimantMessageAttachments
                evidenceItems={evidenceItems}
                attachments={failedMessage.attachments}
                previewFiles={evidencePreviewFiles.current}
              />
              <p className="message-state">{failedMessage.deliveryState || 'Not sent'}</p>
              <p className="message-failure-detail">{failedMessage.message}</p>
            </article>
          )}
          onOpenHowItWorks={() => setPage('how-it-works')}
        />
      ) : (
        <main
          className={`intake-page ${claimDetailsExpanded ? 'details-open' : 'details-closed'} ${workspaceView === 'privacy' ? 'privacy-view' : ''} ${arrivingFromEntry ? 'is-arriving' : ''}`}
          onAnimationEnd={(event) => {
            if (event.target.classList?.contains('message-list')) setArrivingFromEntry(false)
          }}
        >
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
              <button
                type="button"
                onClick={() => startNewChat({ stayInWorkspace: true })}
                disabled={isBusy}
              >
                {status === 'pausing-session' ? 'Saving...' : 'New chat'}
              </button>
              <button
                className={workspaceView === 'privacy' ? 'is-active' : undefined}
                type="button"
                aria-current={workspaceView === 'privacy' ? 'page' : undefined}
                onClick={() => {
                  setWorkspaceView('privacy')
                  setMobileView('chat')
                }}
              >
                Privacy &amp; your data
              </button>
              <button type="button" onClick={openClaimHistory}>Claim history</button>
              <button
                className={workspaceView === 'external-services' ? 'is-active' : undefined}
                type="button"
                aria-current={workspaceView === 'external-services' ? 'page' : undefined}
                onClick={() => openClaimWorkspacePage('external-services')}
              >
                External services
              </button>
            </div>
            <div className="intake-history-label">Conversation history</div>
            <div className="intake-history-list">
              {conversationReports.map((report) => {
                const isCurrent = report.claim_id === claim?.claim_id
                return (
                  <button
                    className={`intake-history-item ${isCurrent ? 'is-active' : ''}`}
                    type="button"
                    key={report.claim_id}
                    aria-current={isCurrent ? 'page' : undefined}
                    onClick={isCurrent ? undefined : () => resumeSavedReport(report.claim_id)}
                    disabled={isBusy}
                  >
                    <span className="intake-history-title">
                      {isCurrent ? 'Current claim' : report.incident_type || 'Incident report'}
                    </span>
                    <span className="intake-history-meta">
                      {isCurrent
                        ? `${report.incident_type || 'New report'} · ${claimStartedLabel(report)}`
                        : report.customer_next_step.summary}
                    </span>
                  </button>
                )
              })}
            </div>
            <div className="intake-history-bottom">
              <button
                className="intake-profile"
                type="button"
                aria-label={profileButtonLabel}
                onClick={() => openProfileFromWorkspace()}
              >
                <ClaimantAvatar className="intake-profile-avatar" displayName={account?.profile?.display_name} />
                <span className="intake-profile-copy">
                  <span className="intake-profile-name" title={profileDisplayName} aria-hidden="true">
                    {profileNamePreview.truncated ? (
                      <>
                        <span className="intake-profile-name-start">{profileNamePreview.start}</span>
                        <span className="intake-profile-name-end">{profileNamePreview.end}</span>
                      </>
                    ) : profileNamePreview.start}
                  </span>
                  <small className="intake-profile-email" title={profileEmail} aria-hidden="true">
                    {middleEllipsis(profileEmail, PROFILE_EMAIL_PREVIEW_LENGTH)}
                  </small>
                </span>
              </button>
            </div>
          </aside>
          <section ref={conversationPanelRef} className={`conversation-panel mobile-view-${mobileView} ${workspaceView !== 'chat' ? 'is-utility' : ''}`} aria-labelledby="conversation-title">
            <div
              className={`workspace-utility-page ${['history', 'claim-features', 'claim-evidence', 'files'].includes(workspaceView) ? 'is-claim-record-page' : ''} ${workspaceView === 'privacy' ? 'is-privacy-page' : ''} ${workspaceView === 'agreement' ? 'is-agreement-page' : ''}`}
              hidden={workspaceView === 'chat'}
            >
              {workspaceView === 'privacy' ? (
                <PrivacyPage
                  claimType={claim?.incident_type || null}
                  hasCurrentClaim={Boolean(claim?.claim_id)}
                  onViewClaim={claim ? () => openClaimFeatures(claim) : null}
                />
              ) : (
                ['agreement', 'external-services'].includes(workspaceView) ? null : (
                  <>
                    <h1>
                      {workspaceView === 'history'
                      ? 'Claim history'
                      : workspaceView === 'claim-features'
                        ? 'Claim features'
                        : workspaceView === 'agreement'
                            ? 'Agreement & confirmation'
                            : 'Evidence history'}
                    </h1>
                    <p>
                      {workspaceView === 'history'
                      ? 'Your Claims are listed by their latest server-recorded update. Open a Claim to review its available features.'
                      : workspaceView === 'claim-features'
                        ? 'Review this Claim\'s current status and available information.'
                        : workspaceView === 'agreement'
                            ? 'Your payout destination and preferred contact method are saved. Agreement review and final Claim confirmation happen in Step 4.'
                            : workspaceView === 'claim-evidence'
                            ? 'Review the files and supporting material recorded for the selected Claim.'
                            : 'Review files retained across your Northwind Claims, including where they came from and their latest processing state.'}
                    </p>
                  </>
                )
              )}
              {workspaceView === 'history' && (
                account ? (
                  <ClaimHistory
                    claims={claimHistory}
                    error={claimHistoryError}
                    loading={claimHistory === null && !claimHistoryError}
                    refreshing={status === 'loading-reports'}
                    onRetry={loadSavedReports}
                    onSelect={openClaimFeatures}
                    onStartClaim={startNewChat}
                    onContinueReport={continueReportFromClaimHistory}
                  />
                ) : (
                  <div className="claim-history-state">
                    <h2>Sign in to view Claim history</h2>
                    <p>Your current Claim remains available. Sign in to review the Claims saved to your account.</p>
                    <button className="secondary-button" type="button" onClick={() => setPage('login')}>Log in</button>
                  </div>
                )
              )}
              {workspaceView === 'claim-features' && (
                selectedHistoryClaim ? (
                  <ClaimFeatureDirectory claim={selectedHistoryClaim} onOpenEvidence={openClaimEvidence} />
                ) : (
                  <div className="claim-history-state is-error" role="alert">
                    <h2>This Claim is no longer available</h2>
                    <p>Northwind could not find it in the latest Claim history. Return to the list and choose another Claim.</p>
                    <button className="secondary-button" type="button" onClick={openClaimHistory}>Return to Claim history</button>
                  </div>
                )
              )}
              {workspaceView === 'agreement' && (
                <AgreementConfirmationPanel
                  claim={claim}
                  busy={isBusy}
                  status={status}
                  submissionError={agreementSubmissionError?.claimId === claim?.claim_id
                    ? agreementSubmissionError
                    : null}
                  onSubmit={submitAgreementAndCreate}
                  onReviewInformation={() => {
                    setDetailsOpen(true)
                    setDetailsTab('summary')
                    setWorkspaceView('chat')
                  }}
                  onReturnToConversation={() => setWorkspaceView('chat')}
                />
              )}
              {workspaceView === 'claim-evidence' && selectedHistoryClaim && (
                <EvidenceHistory claimId={selectedHistoryClaim.claim_id} />
              )}
              {workspaceView === 'external-services' && (
                <ExternalServicesPage
                  action={claim?.external_service_action || null}
                  messageActions={messageExternalServiceActions}
                  claim={claim}
                  onBackToOverview={() => openClaimWorkspacePage('overview')}
                  onWhatToProvide={() => openClaimWorkspacePage('documents')}
                />
              )}
              {workspaceView === 'files' && (
                account ? (
                  <EvidenceHistory
                    currentClaimId={claim?.claim_id || null}
                    currentClaimRevision={claim?.revision || null}
                  />
                ) : (
                  <div className="evidence-history-state">
                    <h2>Sign in to view your evidence history</h2>
                    <p>Your current claim remains available. Sign in to see files retained across your other claims.</p>
                    <button className="secondary-button" type="button" onClick={() => setPage('login')}>Log in</button>
                  </div>
                )
              )}
            </div>
            <div className={`conversation-heading ${claim ? '' : 'is-empty'}`}>
              {claim && (
                <div className="conversation-heading-main">
                  <div className="claim-heading-identity">
                    <h1 id="conversation-title">{claimHeading(claim)}</h1>
                  </div>
                </div>
              )}
              {claim && (
                <div className="claim-status">{claim.external_claim?.creation_status === 'created'
                  ? 'Claim created'
                  : handoff ? 'Staff assistance active' : 'In progress'}</div>
              )}
            </div>

            <div
              ref={messageListRef}
              className="message-list"
              aria-live="polite"
              onScroll={handleMessageListScroll}
            >
              {isNewConversationEmpty && !pendingMessage && <ConversationStart onChoosePrompt={setDraft} />}
              {conversationTimeline.map((item) => {
                if (item.kind === 'conversation-event') {
                  return (
                    <ConversationEvent
                      key={item.key}
                      title={item.title}
                      detail={item.detail}
                    />
                  )
                }
                if (item.kind === 'system-event') {
                  return (
                    <div className="conversation-system-event" key={item.key}>
                      <span aria-hidden="true">✓</span>
                      <span>{item.text}</span>
                    </div>
                  )
                }
                const message = item.message
                if (message.actor === 'claimant') {
                  return (
                    <ClaimantMessageRow
                      key={item.key}
                      message={message}
                      displayName={account?.profile?.display_name}
                      evidenceItems={evidenceItems}
                      previewFiles={evidencePreviewFiles.current}
                    >
                      {message.recovery && !messages.some((reply) => reply.actor === 'agent' && !reply.recovery && reply.in_reply_to === message.message_id) && (
                        <div className="message-recovery" role="status">
                          <p>{message.recovery.claimant_projection}</p>
                          {recoveryFailure?.messageId === message.message_id && (
                            <p className="message-state" role="alert">{recoveryFailure.message}</p>
                          )}
                          {message.client_message_id && message.recovery.resume_triggers?.includes('explicit_retry_request') && (
                            <button type="button" disabled={isBusy} onClick={(event) => sendMessage(event, message)}>Retry response</button>
                          )}
                        </div>
                      )}
                    </ClaimantMessageRow>
                  )
                }
                if (message.actor === 'staff') {
                  return <StaffMessageRow key={item.key} message={message} />
                }
                if (message.actor === 'system') {
                  return (
                    <div className="conversation-system-event" key={item.key}>
                      <span aria-hidden="true">✓</span>
                      <span>{messageText(message)}</span>
                    </div>
                  )
                }
                const recordedFacts = factCards.get(message.message_id)
                return (
                  <AgentMessageRow
                    key={item.key}
                    message={message}
                    activity={messageActivities[message.message_id]}
                  >
                        {recordedFacts && (
                          <RecordedFactsCard
                            facts={recordedFacts}
                            fieldInputs={dynamicForm?.field_inputs}
                            progress={recordedProgress}
                            latest={message.message_id === latestFactCardId}
                            busy={isBusy}
                            onConfirm={confirmFields}
                            onSave={(fact, value) => saveFieldValue(fact.fieldCode, fact.field, value)}
                          />
                        )}
                        {(message.message_actions || []).map((action) => (
                          <div className="conversation-agent-action" key={action.offer_id || action.service_identity}>
                            <ExternalServiceAction
                              action={action}
                              consentChecked={Boolean(offerConsentChecks[action.offer_id])}
                              setConsentChecked={(checked) => setOfferConsentChecks((current) => ({
                                ...current,
                                [action.offer_id]: checked,
                              }))}
                              onRequest={() => decideMessageExternalService(action, 'grant')}
                              onDecline={() => decideMessageExternalService(action, 'decline')}
                              onWithdraw={() => decideMessageExternalService(action, 'withdraw')}
                              status={status}
                              error={offerErrors[action.offer_id] || null}
                              expanded={conversationPanelExpanded(action.offer_id)}
                              onToggle={() => toggleConversationPanel(action.offer_id)}
                            />
                          </div>
                        ))}
                        {item.key === lastAgentMessageId && visibleConversationActionKind && (
                          <div className="conversation-agent-action">
                            {renderConversationAction()}
                          </div>
                        )}
                  </AgentMessageRow>
                )
              })}
              {!lastAgentMessageId && visibleConversationActionKind && (
                <div className="conversation-agent-action is-standalone">
                  {renderConversationAction()}
                </div>
              )}
              {account && claim && (
                <ClaimAutoFillPanel
                  key={`${account.customer_id}:${claim.claim_id}`}
                  account={account}
                  claim={claim}
                  busy={claimOperationBusy}
                  onBusyChange={setAutoFillBusy}
                  onClaimReadback={applyClaimSnapshot}
                />
              )}
              {pendingMessage && (
                <>
                  {!pendingMessage.retrying && !messages.some((message) => message.actor === 'claimant' && message.client_message_id === pendingMessage.turnId) && <article className="msg-user is-pending" aria-label="Message sending">
                    <div className="message-timestamp">Sending…</div>
                    <div className="chat-message-row">
                      <div className="user-message-body">
                        <div className="chat-bubble user-bubble">
                          {pendingMessage.text && <p className="user-bubble-text">{pendingMessage.text}</p>}
                          <ClaimantMessageAttachments
                            evidenceItems={evidenceItems}
                            attachments={pendingMessage.attachments}
                            previewFiles={evidencePreviewFiles.current}
                          />
                        </div>
                      </div>
                      <ClaimantAvatar className="message-avatar claimant-message-avatar" displayName={account?.profile?.display_name} />
                    </div>
                  </article>}
                  <AgentTurnPlaceholder
                    progress={activeTurnProgress}
                    turnId={pendingMessage.turnId}
                  />
                </>
              )}
              {failedMessage && (
                <article className="msg-user is-failed" role="alert">
                  <div className="chat-message-row">
                    <div className="user-message-body">
                      <div className="chat-bubble user-bubble">
                        <p className="message-author">{failedMessage.sender}</p>
                        {failedMessage.text && <p className="user-bubble-text">{failedMessage.text}</p>}
                        <ClaimantMessageAttachments
                          evidenceItems={evidenceItems}
                          attachments={failedMessage.attachments}
                          previewFiles={evidencePreviewFiles.current}
                        />
                        <p className="message-state">{failedMessage.deliveryState || 'Not sent'}</p>
                        <p className="message-failure-detail">{failedMessage.message}</p>
                      </div>
                    </div>
                    <ClaimantAvatar className="message-avatar claimant-message-avatar" displayName={account?.profile?.display_name} />
                  </div>
                </article>
              )}
              {isUrgentSupport && handoff && ['queued', 'accepted'].includes(handoff.status) && (
                <ConversationEvent
                  icon="!"
                  title="Urgent support · You can keep adding details"
                  detail={handoff.summary}
                  tone="urgent"
                />
              )}

              {assistanceState && !isUrgentSupport && (
                <ConversationEvent
                  icon={assistanceState.key === 'completed' ? '✓' : '●'}
                  title={assistanceState.title}
                  detail={assistanceState.description}
                  tone={assistanceState.key === 'response_needed' ? 'attention' : 'info'}
                />
              )}

              {claim?.external_claim && (
                <>
                  <ConversationEvent
                    icon={claim.external_claim.creation_status === 'failed' ? '!' : '✓'}
                    title={claim.external_claim.creation_status === 'created'
                      ? `Claim ${claim.external_claim.claim_number} created`
                      : claim.external_claim.creation_status === 'pending'
                        ? 'Claim creation in progress'
                        : 'Claim creation needs attention'}
                    tone={claim.external_claim.creation_status === 'failed' ? 'attention' : 'success'}
                  />
                  <ConversationInfoPanel
                    title="Claim details"
                    summary={[claim.external_claim.claim_number, claim.external_claim.route]
                      .filter(Boolean)
                      .join(' · ')}
                    expanded={conversationPanelExpanded('claim-created')}
                    onToggle={() => toggleConversationPanel('claim-created')}
                  >
                    <dl className="conversation-detail-list">
                      {claim.external_claim.route && (
                        <div><dt>Route</dt><dd>{claim.external_claim.route}</dd></div>
                      )}
                      {claim.external_claim.next_step && (
                        <div><dt>Next step</dt><dd>{claim.external_claim.next_step}</dd></div>
                      )}
                      {claim.external_claim.expected_by && (
                        <div>
                          <dt>Expected by</dt>
                          <dd>{new Date(claim.external_claim.expected_by).toLocaleString()}</dd>
                        </div>
                      )}
                    </dl>
                  </ConversationInfoPanel>
                </>
              )}

              {realtimeSyncNotice && (
                <ConversationEvent icon="●" title={realtimeSyncNotice} tone="info" />
              )}
              {evidenceSyncNotice && (
                <ConversationEvent icon="●" title={evidenceSyncNotice} tone="info" />
              )}
            </div>

            <MessageComposer
              draft={draft}
              setDraft={setDraft}
              onSubmit={sendMessage}
              inputLabel={assistanceState?.key === 'response_needed' ? 'Reply to Northwind staff' : inputLabel}
              busy={isBusy}
              hint={assistanceState?.key === 'reply_sent'
                ? 'Your reply is recorded. You can still add information if needed.'
                : proposedFields.length > 0 || proposedContentsItems.length > 0
                  ? 'You can keep describing the incident or correct a detail while these suggestions are waiting for review.'
                  : null}
              placeholder={assistanceState?.key === 'response_needed'
                ? 'Reply to Northwind staff...'
                : isNewConversationEmpty
                  ? 'Write what happened, or choose a prompt above…'
                  : 'Write the details you know...'}
              buttonLabel={status === 'sending'
                ? 'Sending...'
                : failedMessage
                  ? 'Retry message'
                  : assistanceState?.key === 'response_needed'
                    ? 'Send reply'
                    : 'Send'}
              error={error}
              variant="workspace"
              claimType={claimType}
              setClaimType={setClaimType}
              claimTypes={runtimeCapabilities.claim_types}
              models={claimantModels}
              selectedModel={selectedModel}
              setSelectedModel={setSelectedModel}
              claimTypeLocked={Boolean(sessionId)}
              attachments={attachments}
              onFileSelected={handleFileSelected}
              onRemoveAttachment={removeComposerAttachment}
            />
          </section>

          {!detailsOpen && showsClaimDetails && (
            <button
              className="details-reopen"
              type="button"
              onClick={() => setDetailsOpen(true)}
              aria-label="Open claim details panel"
              title="Open claim details panel"
            >
              <svg viewBox="0 0 24 24" aria-hidden="true">
                <rect x="3.5" y="4" width="17" height="16" rx="2" />
                <path d="M15 4v16m-1-12-4 4 4 4" />
              </svg>
            </button>
          )}
          <aside
            className={`claim-panel intake-details-panel mobile-view-${mobileView} ${claimDetailsExpanded ? 'is-open' : 'is-collapsed'}`}
            aria-label="Claim details"
            aria-hidden={!claimDetailsExpanded}
            hidden={!showsClaimDetails}
          >
            <div className="claim-details-sticky-header">
              <div className="claim-details-toolbar">
                <h2>Claim details</h2>
                <button
                  className="claim-details-collapse"
                  type="button"
                  aria-label="Collapse panel"
                  title="Collapse panel"
                  aria-expanded={claimDetailsExpanded}
                  aria-controls="claim-details-body"
                  onClick={() => setDetailsOpen(false)}
                >
                  <svg viewBox="0 0 24 24" aria-hidden="true">
                    <rect x="3.5" y="4" width="17" height="16" rx="2" />
                    <path d="M15 4v16m-5-12 4 4-4 4" />
                  </svg>
                </button>
              </div>
              <div className="claim-details-tabs" role="tablist" aria-label="Claim detail views">
                {[
                  ['summary', 'Overview'],
                  ['documents', 'Next steps'],
                ].map(([tab, label]) => (
                  <button
                    ref={(node) => { detailsTabRefs.current[tab] = node }}
                    id={`claim-details-${tab}-tab`}
                    key={tab}
                    type="button"
                    role="tab"
                    aria-selected={detailsTab === tab}
                    aria-controls={`claim-details-${tab}-panel`}
                    tabIndex={detailsTab === tab ? 0 : -1}
                    onClick={() => setDetailsTab(tab)}
                    onKeyDown={(event) => handleDetailsTabKeyDown(event, tab)}
                  >
                    <span>{label}</span>
                    {tab === 'documents' && (
                      <span className="claim-details-tab-count" aria-hidden="true">{toProvideCount}</span>
                    )}
                  </button>
                ))}
              </div>
              <ClaimSummaryProgress
                form={form}
                contentsItems={contentsItems}
                dynamicForm={dynamicForm}
              />
            </div>
            <div id="claim-details-body" hidden={!detailsOpen}>
            <div
              id="claim-details-summary-panel"
              role="tabpanel"
              aria-labelledby="claim-details-summary-tab"
              tabIndex="0"
              hidden={detailsTab !== 'summary'}
            >
              {detailsTab === 'summary' && (
                <ClaimReviewPanel
                  form={form}
                  contentsItems={contentsItems}
                  dynamicForm={dynamicForm}
                  proposedFields={proposedFields}
                  proposedContentsItems={proposedContentsItems}
                  editingField={editingField}
                  editValue={editValue}
                  setEditValue={setEditValue}
                  beginEdit={beginEdit}
                  cancelEdit={() => setEditingField(null)}
                  saveFieldCorrection={saveFieldCorrection}
                  confirmProposedFields={confirmProposedFields}
                  fieldLabel={fieldLabel}
                  fieldStatusLabel={fieldStatusLabel}
                  fieldSourceLabel={fieldSourceLabel}
                  fieldValueText={fieldValueText}
                  busy={isBusy}
                  status={status}
                  stepActive={conversationActionKind === 'review-details'}
                  conversationEmpty={isNewConversationEmpty}
                  onViewNextSteps={() => setDetailsTab('documents')}
                />
              )}
            </div>
            <div
              id="claim-details-documents-panel"
              role="tabpanel"
              aria-labelledby="claim-details-documents-tab"
              tabIndex="0"
              hidden={detailsTab !== 'documents'}
            >
              {detailsTab === 'documents' && (
                <ClaimNextStepsPanel
                  form={form}
                  dynamicForm={dynamicForm}
                  fieldLabel={fieldLabel}
                  editingField={editingField}
                  editValue={editValue}
                  setEditValue={setEditValue}
                  beginEdit={beginEdit}
                  cancelEdit={() => setEditingField(null)}
                  saveFieldCorrection={saveFieldCorrection}
                  busy={isBusy}
                  status={status}
                />
              )}
              {detailsTab === 'documents' && showsClaimDetails && (
                <ClaimDocuments
                  items={evidenceItems}
                  loadStatus={evidenceLoadStatus}
                  onUpload={(item, file) => handleFileSelected(
                    file,
                    null,
                    item.kind,
                    item.evidence_id,
                  )}
                  compact
                />
              )}
              {detailsTab === 'documents' && claim?.external_capabilities?.length > 0 && (
                <details className="next-steps-more-options">
                  <summary>
                    <span>More options</span>
                    <span>{claim.external_capabilities.length}</span>
                  </summary>
                  <button
                    ref={externalCapabilitiesTriggerRef}
                    className="external-capabilities-trigger"
                    type="button"
                    aria-haspopup="dialog"
                    onClick={() => setExternalCapabilitiesOpen(true)}
                  >
                    <strong>Use a third-party service</strong>
                    <span>
                      View {claim.external_capabilities.length}{' '}
                      {claim.external_capabilities.length === 1 ? 'option' : 'options'}
                      <span aria-hidden="true">›</span>
                    </span>
                  </button>
                </details>
              )}
            </div>
            </div>
          </aside>
          {claim?.external_capabilities?.length > 0 && (
            <ExternalCapabilityCatalogue
              capabilities={claim.external_capabilities}
              dialogRef={externalCapabilitiesDialogRef}
              headingRef={externalCapabilitiesHeadingRef}
              onClose={closeExternalCapabilities}
            />
          )}
        </main>
      )}
    </div>
  )
}

function ExternalCapabilityCatalogue({ capabilities, dialogRef, headingRef, onClose }) {
  return (
    <dialog
      ref={dialogRef}
      className="external-capabilities-dialog"
      aria-labelledby="external-capabilities-title"
      onCancel={(event) => {
        event.preventDefault()
        onClose()
      }}
    >
      <div className="external-capabilities-dialog-heading">
        <div>
          <p className="transfer-label">Available support</p>
          <h2 id="external-capabilities-title" ref={headingRef} tabIndex="-1">Third-party services</h2>
        </div>
        <button className="external-capabilities-close" type="button" aria-label="Close third-party services" onClick={onClose}>
          <span aria-hidden="true">×</span>
        </button>
      </div>
      <div className="service-capability-list">
        {capabilities.map((capability) => (
          <article className="service-capability" key={capability.service_identity}>
            <h3>{capability.service_name}</h3>
            <p>{capability.purpose}</p>
            <p className="service-limitation">{capability.result_semantics}</p>
            <div className="service-capability-actions">
              {capability.official_url && <a href={capability.official_url} target="_blank" rel="noreferrer">Official information</a>}
              {capability.official_phone && <a href={`tel:${capability.official_phone}`}>Call {capability.official_phone}</a>}
            </div>
          </article>
        ))}
      </div>
    </dialog>
  )
}
export default App
