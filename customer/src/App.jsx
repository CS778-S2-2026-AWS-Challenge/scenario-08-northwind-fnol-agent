import { useEffect, useMemo, useRef, useState } from 'react'
import {
  ApiRequestError,
  confirmClaimFields,
  createClaim,
  createExternalClaim,
  decideExternalServiceOffer,
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
  streamRealtimeEvents,
  submitClaimMessage,
  setClaimantAccessToken,
  updateAccountPreferences,
  updateAccountProfile,
  updateClaimField,
} from './api.js'
import './App.css'
import './styles/frontend-refactor.css'
import MessageComposer from './components/MessageComposer.jsx'
import ExternalServiceAction, { ExternalServiceOverview } from './components/ExternalServiceAction.jsx'
import EvidenceHistory from './components/EvidenceHistory.jsx'
import ClaimHistory, { ClaimFeatureDirectory } from './components/ClaimHistory.jsx'
import ClaimDocuments from './components/ClaimDocuments.jsx'
import ClaimReviewPanel from './components/ClaimReviewPanel.jsx'
import ConversationHistorySidebar from './components/ConversationHistorySidebar.jsx'
import {
  AgentTurnDisclosure,
  AgentTurnPlaceholder,
} from './components/AgentTurnActivity.jsx'
import { completeTurnProgress, reduceTurnProgress } from './agentTurnProgress.js'
import { documentAttentionCount } from './claimDocumentProjection.js'
import {
  forgetAnonymousConversation,
  readAnonymousConversationHistory,
  rememberAnonymousConversation,
} from './anonymousConversationHistory.js'
import {
  ClaimProgressDisclosure,
  ConversationActionCard,
  ConversationEvent,
  ConversationInfoPanel,
} from './components/ConversationContext.jsx'

const FIELD_LABELS = {
  'claim.product_family': 'Claim type',
  'incident.description': 'What happened',
  'incident.injury_or_danger': 'Injury or immediate danger',
  'incident.occurred_at': 'When it happened',
  'incident.location': 'Incident location',
  'loss.description': 'Damage or loss',
  'parties.other_parties': 'Other people or vehicles involved',
  'vehicle.damage_description': 'Vehicle damage',
  'vehicle.drivable': 'Vehicle safe to drive',
  'property.address': 'Affected property',
  'property.affected_areas': 'Affected areas',
  'property.ongoing_risk': 'Ongoing property risk',
  'property.habitable': 'Property safe to live in',
  'contents.items': 'Damaged, lost, or stolen items',
}

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

const FIELD_SOURCE_LABELS = {
  claimant: 'Provided by you',
  inference: 'Suggested from your description',
  image: 'Suggested from your image',
  document: 'Suggested from your document',
  policy: 'From your policy information',
  claim_history: 'From your previous claim information',
  staff: 'Provided by Northwind support',
}

const SUPPORT_HANDOFF_TYPES = new Set(['human_support', 'urgent_support'])

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
  if (typeof message?.content?.text === 'string') return message.content.text
  if (typeof message?.content?.summary === 'string') return message.content.summary
  return ''
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

function buildConversationTimeline(messages, resumeContext) {
  const timeline = messages.map((message) => ({
    key: message.message_id,
    kind: 'message',
    message,
  }))
  if (resumeContext) {
    const boundaryMessageIndex = resumeContext.resumed_after_message_id
      ? timeline.findIndex((item) => item.message?.message_id === resumeContext.resumed_after_message_id)
      : -1
    const resumedAt = Date.parse(resumeContext.resumed_at || '')
    const firstMessageAfterResume = boundaryMessageIndex < 0 && Number.isFinite(resumedAt)
      ? timeline.findIndex((item) => (
          item.message && Date.parse(item.message.created_at || '') >= resumedAt
        ))
      : -1
    const insertAt = boundaryMessageIndex >= 0
      ? boundaryMessageIndex + 1
      : firstMessageAfterResume >= 0
        ? firstMessageAfterResume
        : resumeContext.has_resume_boundary
          ? 0
          : timeline.length
    timeline.splice(insertAt, 0, {
      key: `claim-resumed-${resumeContext.resumed_at || 'current'}`,
      kind: 'conversation-event',
      title: 'Claim resumed',
      detail: 'Continuing from your previous conversation',
    })
  }
  return timeline
}

function mergeMessagesById(current, incoming) {
  const merged = new Map(current.map((message) => [message.message_id, message]))
  for (const message of incoming) {
    if (message?.message_id) merged.set(message.message_id, message)
  }
  return [...merged.values()]
}

const CLAIMANT_ACTION_KINDS = Object.freeze({
  'claimant.create_claim': 'create-claim',
  'claimant.review_details': 'review-details',
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

function evidenceFileStatusLabel(fileStatus, status) {
  if (fileStatus === 'awaiting_upload') return 'Upload incomplete'
  if (fileStatus === 'processing') return 'Processing'
  if (fileStatus === 'failed') return 'Processing failed'
  if (fileStatus === 'ready') return 'Ready'
  if (fileStatus) return fileStatus
  return status === 'received' ? 'Received' : status
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

function claimProgress(nextStep, dynamicForm) {
  const requirements = dynamicForm?.requirements
  const total = requirements?.current_action_total || 0
  const current = requirements?.current_action_satisfied || 0
  const items = requirements
    ? [
        ...(requirements.satisfied || []).map((fieldCode) => ({
          fieldCode,
          label: fieldLabel(fieldCode),
          state: 'complete',
        })),
        ...(requirements.missing_required_now || []).map((fieldCode) => ({
          fieldCode,
          label: fieldLabel(fieldCode),
          state: 'required',
        })),
        ...(requirements.pending_later || []).map((fieldCode) => ({
          fieldCode,
          label: fieldLabel(fieldCode),
          state: 'later',
        })),
      ]
    : []
  return {
    current,
    total,
    label: requirements?.ready
      ? 'Ready to create'
      : ['human_support_queued', 'human_support_in_progress', 'urgent_support_queued']
          .includes(nextStep?.status)
        ? ''
        : nextStep?.summary || '',
    available: Boolean(requirements),
    items,
  }
}

function App() {
  const initialPage = (() => {
    const path = globalThis.location?.pathname || '/'
    if (path === '/auth/login') return 'login'
    if (path === '/auth/register') return 'register'
    if (path === '/account') return 'account'
    if (/^\/account\/claims\/[^/]+\/evidence$/.test(path)) return 'claim-evidence'
    if (/^\/account\/claims\/[^/]+$/.test(path)) return 'claim-features'
    if (path === '/account/claims') return 'claim-history'
    if (path === '/files') return 'files'
    if (path === '/how-it-works') return 'how-it-works'
    return 'home'
  })()
  const [page, setPageState] = useState(initialPage)
  const [account, setAccount] = useState(null)
  const [authStatus, setAuthStatus] = useState('idle')
  const [authError, setAuthError] = useState('')
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
  const [error, setError] = useState('')
  const [editingField, setEditingField] = useState(null)
  const [editValue, setEditValue] = useState('')
  const [handoff, setHandoff] = useState(null)
  const [assistanceReplyReview, setAssistanceReplyReview] = useState(null)
  const [claimHistory, setClaimHistory] = useState(() => (
    hasClaimantAccessToken() ? null : readAnonymousConversationHistory()
  ))
  const [claimHistoryError, setClaimHistoryError] = useState('')
  const [conversationHistoryOpen, setConversationHistoryOpen] = useState(false)
  const [selectedHistoryClaimId, setSelectedHistoryClaimId] = useState(() => {
    const match = globalThis.location?.pathname?.match(/^\/account\/claims\/([^/]+)/)
    return match ? decodeURIComponent(match[1]) : null
  })
  const [detailsOpen, setDetailsOpen] = useState(true)
  const [detailsTab, setDetailsTab] = useState('summary')
  const [mobileView, setMobileView] = useState('chat')
  const [workspaceView, setWorkspaceView] = useState('chat')
  const [workspaceActive, setWorkspaceActive] = useState(false)
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
  const [pendingMessage, setPendingMessage] = useState(null)
  const [activeTurnProgress, setActiveTurnProgress] = useState(null)
  const [messageActivities, setMessageActivities] = useState({})
  const activeTurnProgressRef = useRef(null)
  const pendingSubmission = useRef(null)
  const pendingConfirmation = useRef(null)
  const pendingSupportRequest = useRef(null)
  const pendingClaimCreation = useRef(null)
  const pendingExternalService = useRef(null)
  const latestRevision = useRef(0)
  const latestRevisionClaimId = useRef(null)
  const activeClaimRef = useRef(claim)
  const activeSessionIdRef = useRef(sessionId)
  const accountRef = useRef(account)
  const realtimeCursor = useRef(null)
  const realtimeSeenEventIds = useRef(new Set())
  const messagesRequestGeneration = useRef(0)
  const claimTransitionRef = useRef(null)
  const latestEvidenceRevision = useRef(0)
  const latestEvidenceItems = useRef([])
  const evidenceHasLocalMutation = useRef(false)
  const evidenceClaimId = useRef(null)
  const evidenceUploadControllers = useRef(new Map())
  const dismissedComposerEvidenceIds = useRef(new Set())
  const detailsTabRefs = useRef({})
  const conversationPanelRef = useRef(null)
  const messageListRef = useRef(null)
  const externalCapabilitiesDialogRef = useRef(null)
  const externalCapabilitiesHeadingRef = useRef(null)
  const externalCapabilitiesTriggerRef = useRef(null)
  const presentedCapabilityCatalogues = useRef(new Set())
  const restoreCapabilityTriggerFocus = useRef(false)
  const followLatestMessages = useRef(true)
  const forceLatestMessages = useRef(false)
  const confirmedClaimProjections = useRef(new Map())
  activeClaimRef.current = claim
  activeSessionIdRef.current = sessionId
  accountRef.current = account
  const realtimePrincipal = account ? 'authenticated' : claim?.claim_id ? 'anonymous' : 'none'
  const hasStarted = claim !== null
  const isWorkspaceActive = hasStarted && workspaceActive
  const savedReports = claimHistory === null
    ? null
    : claimHistory.filter((item) => item.can_resume)
  const conversationReports = claim
    ? claimHistory?.some((item) => item.claim_id === claim.claim_id)
      ? claimHistory
          .map((item) => item.claim_id === claim.claim_id ? claim : item)
          .filter((item) => item.claim_id === claim.claim_id || item.can_resume)
      : [claim, ...(savedReports || [])]
    : []
  const homepageConversationReports = claim ? conversationReports : (savedReports || [])
  const selectedHistoryClaim = claimHistory?.find((item) => item.claim_id === selectedHistoryClaimId)
    || (claim?.claim_id === selectedHistoryClaimId ? claim : null)
  const documentOutstandingCount = evidenceLoadStatus === 'ready'
    ? documentAttentionCount(evidenceItems)
    : null

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
        if (globalThis.location?.pathname === '/files' || globalThis.location?.pathname?.startsWith('/account/claims')) {
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

  function routeForPage(nextPage) {
    if (nextPage === 'login') return '/auth/login'
    if (nextPage === 'register') return '/auth/register'
    if (nextPage === 'account') return '/account'
    if (nextPage === 'claim-history') return '/account/claims'
    if (nextPage === 'claim-features' && selectedHistoryClaimId) return `/account/claims/${encodeURIComponent(selectedHistoryClaimId)}`
    if (nextPage === 'claim-evidence' && selectedHistoryClaimId) return `/account/claims/${encodeURIComponent(selectedHistoryClaimId)}/evidence`
    if (nextPage === 'files') return '/files'
    if (nextPage === 'how-it-works') return '/how-it-works'
    if (isWorkspaceActive && claim?.claim_id) return `/claims/${claim.claim_id}`
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
    if (pathname === '/account/claims') return account ? 'claim-history' : 'login'
    if (/^\/account\/claims\/[^/]+\/evidence$/.test(pathname)) return account ? 'claim-evidence' : 'login'
    if (/^\/account\/claims\/[^/]+$/.test(pathname)) return account ? 'claim-features' : 'login'
    if (pathname === '/files') return account ? 'files' : 'login'
    if (pathname === '/how-it-works') return 'how-it-works'
    if (pathname.startsWith('/claims/')) return claim?.claim_id ? 'home' : 'home'
    return 'home'
  }

  useEffect(() => {
    const onPopState = () => {
      const path = globalThis.location?.pathname || '/'
      const nextPage = pageForPath(path)
      setWorkspaceActive(path.startsWith('/claims/') && Boolean(claim))
      const historyClaimMatch = path.match(/^\/account\/claims\/([^/]+)/)
      setSelectedHistoryClaimId(historyClaimMatch ? decodeURIComponent(historyClaimMatch[1]) : null)
      setPageState(nextPage)
      const canonicalPath = ['claim-history', 'claim-features', 'claim-evidence'].includes(nextPage)
        ? path
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
    const expectedPath = page === 'login'
      ? '/auth/login'
      : page === 'register'
        ? '/auth/register'
        : page === 'account'
          ? '/account'
          : page === 'claim-history'
            ? '/account/claims'
            : page === 'claim-features' && selectedHistoryClaimId
              ? `/account/claims/${encodeURIComponent(selectedHistoryClaimId)}`
              : page === 'claim-evidence' && selectedHistoryClaimId
                ? `/account/claims/${encodeURIComponent(selectedHistoryClaimId)}/evidence`
                : page === 'files'
                  ? '/files'
                  : page === 'how-it-works'
                    ? '/how-it-works'
                    : isWorkspaceActive && claim?.claim_id ? `/claims/${claim.claim_id}` : '/'
    if (globalThis.location?.pathname !== expectedPath) {
      globalThis.history?.replaceState({ northwindRoute: page }, '', expectedPath)
    }
  }, [isWorkspaceActive, page, claim?.claim_id, selectedHistoryClaimId])

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
  const proposedContentsItems = useMemo(
    () => contentsItems.filter((item) => item.status === 'proposed'),
    [contentsItems],
  )
  const inputLabel = INPUT_LABELS[nextStep?.status] || 'Add more information'
  const progress = useMemo(() => claimProgress(nextStep, dynamicForm), [dynamicForm, nextStep])
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
  const conversationActionKind = conversationAction?.kind || null
  const externalCapabilityKey = claim?.external_capabilities?.length > 0
    ? `${claim.claim_id}:${claim.external_capabilities
        .map((capability) => `${capability.service_identity}:${capability.registry_version || ''}`)
        .join('|')}`
    : null

  useEffect(() => {
    if (!externalCapabilityKey || !isWorkspaceActive) return
    if (presentedCapabilityCatalogues.current.has(externalCapabilityKey)) return
    presentedCapabilityCatalogues.current.add(externalCapabilityKey)
    setExternalCapabilitiesOpen(true)
  }, [externalCapabilityKey, isWorkspaceActive])

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
    if (!followLatestMessages.current && !forceLatestMessages.current) return
    messageList.scrollTop = messageList.scrollHeight
    followLatestMessages.current = true
    forceLatestMessages.current = false
  }, [
    assistanceState,
    claim?.external_claim,
    conversationActionKind,
    conversationTimeline,
    evidenceSyncNotice,
    failedMessage,
    isWorkspaceActive,
    pendingMessage,
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

  function beginMessagesReadback() {
    messagesRequestGeneration.current += 1
    return messagesRequestGeneration.current
  }

  function commitMessages(nextMessages) {
    messagesRequestGeneration.current += 1
    setMessages(nextMessages)
  }

  function applyMessagesReadback(items, { generation, claimId, sessionId }) {
    if (
      generation !== messagesRequestGeneration.current
      || activeClaimRef.current?.claim_id !== claimId
      || activeSessionIdRef.current !== sessionId
    ) return false
    setMessages(items)
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

  function replaceActiveClaimContext(currentClaim, currentSessionId) {
    activeClaimRef.current = currentClaim
    activeSessionIdRef.current = currentSessionId
    latestRevisionClaimId.current = currentClaim?.claim_id || null
    latestRevision.current = Number(currentClaim?.revision || 0)
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
      if (current.some((item) => item.status === 'uploading')) {
        return current.map((item) => {
          const evidence = items.find((candidate) => candidate.evidence_id === item.evidenceId)
          return evidence ? attachmentForEvidence(evidence, item) : item
        })
      }
      return items
        .filter((item) => !dismissedComposerEvidenceIds.current.has(item.evidence_id))
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
      return undefined
    }

    const controller = new AbortController()
    let active = true
    let reconnectDelay = 1000
    let degradedRefreshes = 0
    let needsResyncSnapshot = false
    const maxDegradedRefreshes = 5

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

      if (activeClaim?.claim_id) {
        const claimId = activeClaim.claim_id
        refreshes.push((async () => {
          const messagesGeneration = activeSessionId ? beginMessagesReadback() : null
          const [currentClaim, conversation, evidence] = await Promise.all([
            getClaim(claimId),
            activeSessionId ? getClaimMessages(claimId, activeSessionId) : Promise.resolve(null),
            getClaimEvidence(claimId),
          ])
          if (!active || activeClaimRef.current?.claim_id !== claimId) return
          applyClaimSnapshot(currentClaim)
          if (conversation && messagesGeneration !== null) {
            applyMessagesReadback(conversation.items, {
              generation: messagesGeneration,
              claimId,
              sessionId: activeSessionId,
            })
          }
          if (syncEvidenceProjection(evidence)) setEvidenceSyncNotice('')
          setEvidenceLoadStatus('ready')
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
    }

    async function applyRealtimeEvent(delivery) {
      if (!active) return

      if (delivery.type === 'resync_required') {
        needsResyncSnapshot = true
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
        const recoverOnOpen = needsResyncSnapshot
        try {
          await streamRealtimeEvents({
            cursor: recoverOnOpen ? null : realtimeCursor.current,
            signal: controller.signal,
            onOpen: recoverOnOpen
              ? async () => {
                await refreshFullSnapshot()
                if (!active || controller.signal.aborted) return
                needsResyncSnapshot = false
                realtimeCursor.current = null
                realtimeSeenEventIds.current.clear()
                reconnectDelay = 1000
                degradedRefreshes = 0
              }
              : undefined,
            onEvent: applyRealtimeEvent,
            onCursor: (cursor) => { realtimeCursor.current = cursor },
          })
        } catch (streamFailure) {
          if (!active || controller.signal.aborted) return
          if (streamFailure instanceof ApiRequestError && streamFailure.code === 'INVALID_EVENT_CURSOR') {
            needsResyncSnapshot = true
            realtimeCursor.current = null
            realtimeSeenEventIds.current.clear()
            reconnectDelay = 0
            degradedRefreshes = 0
          } else if (needsResyncSnapshot) {
            reconnectDelay = Math.max(reconnectDelay, 1000)
          } else {
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
  }, [])

  useEffect(() => {
    if (!claim?.claim_id) {
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
    setAttachments((current) => existingAttachment
      ? current.map((item) => item.id === localId
        ? { ...item, status: 'uploading', statusLabel: 'Uploading…', retry: null }
        : item)
      : [...current, { id: localId, name: file.name, status: 'uploading', statusLabel: 'Uploading…' }])
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
          return { revision: uploadRevision, succeeded: true }
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
      evidenceHasLocalMutation.current = true
      latestEvidenceRevision.current = requested.revision
      attempt.evidenceId = requested.evidence_id
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
      return { revision: completed.revision, succeeded: true }
    } catch (requestError) {
      if (requestError?.name === 'AbortError') {
        return { revision: uploadRevision, succeeded: false }
      }
      setAttachments((current) => current.map((item) => item.id === localId
        ? { ...item, status: 'failed', statusLabel: requestError.message || 'Upload failed', retry: () => handleFileSelected(file, attempt) }
        : item))
      showError(requestError)
      return {
        revision: Math.max(uploadRevision, latestEvidenceRevision.current),
        succeeded: false,
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
    if (isBusy) return
    if (!hasClaimantAccessToken()) {
      setError('Sign in before uploading a file. Your anonymous conversation is still available, and you can resume it after signing in.')
      setStatus('error')
      return
    }
    setError('')
    const attempt = existingAttempt || {
      localId: requestId('file'),
      uploadKey: requestId('evidence-upload'),
      completeKey: requestId('evidence-complete'),
      kind: requestedKind || (file.type.startsWith('image/') ? 'incident_photo' : 'other_document'),
      evidenceId: requestedEvidenceId,
    }

    if (!isWorkspaceActive || !claim) {
      setAttachments((current) => [
        ...current,
        {
          id: attempt.localId,
          name: file.name,
          status: 'staged',
          statusLabel: 'Ready to upload after your first message is sent',
          stagedFile: file,
          uploadAttempt: attempt,
        },
      ])
      return
    }

    await uploadAttachment(file, attempt, claim, {
      existingAttachment: Boolean(existingAttempt),
      checkExistingEvidence: Boolean(existingAttempt),
    })
  }

  function removeComposerAttachment(attachment) {
    evidenceUploadControllers.current.get(attachment.id)?.abort()
    evidenceUploadControllers.current.delete(attachment.id)
    const evidenceId = attachment.evidenceId || attachment.uploadAttempt?.evidenceId
    if (evidenceId) dismissedComposerEvidenceIds.current.add(evidenceId)
    setAttachments((current) => current.filter((item) => item.id !== attachment.id))
  }

  function clearComposerAttachments() {
    for (const controller of evidenceUploadControllers.current.values()) controller.abort()
    evidenceUploadControllers.current.clear()
    dismissedComposerEvidenceIds.current.clear()
    setAttachments([])
  }

  function cancelComposerDraftAttachments() {
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

  async function sendMessage(event) {
    event.preventDefault()
    const text = draft.trim()
    if (!text || isBusy) return
    const stagedAttachments = attachments.filter((attachment) => (
      attachment.status === 'staged'
      && attachment.stagedFile
      && attachment.uploadAttempt
    ))
    const isAssistanceReply = assistanceState?.key === 'response_needed'

    forceLatestMessages.current = true
    setError('')
    setFailedMessage(null)
    if (isAssistanceReply) {
      setAssistanceReplyReview({
        claimId: claim.claim_id,
        handoffId: handoff.handoff_id,
        messageId: null,
      })
    }
    setStatus(isWorkspaceActive ? 'sending' : 'starting')
    let messageWasSubmitted = isWorkspaceActive
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
      activeTurnProgressRef.current = null
      setActiveTurnProgress(null)
      setPendingMessage({ text, turnId: operation.clientMessageId })
      let activeClaim = isWorkspaceActive ? claim : null
      let activeSessionId = isWorkspaceActive ? sessionId : null
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
        messageWasSubmitted = true
      }

      const turn = await submitClaimMessage({
        claimId: activeClaim.claim_id,
        sessionId: activeSessionId,
        revision: activeClaim.revision,
        text,
        modelProfileId: selectedModel,
        idempotencyKey: operation.turnKey,
        clientMessageId: operation.clientMessageId,
      })
      commitMessages((current) => mergeMessagesById(current, [
        turn.claimant_message,
        ...(turn.agent_message ? [turn.agent_message] : []),
      ]))
      setForm((current) => mergeFields(current, turn.form_changes))
      setContentsItems((current) => mergeContentsItems(current, turn.contents_item_changes || []))
      setDynamicForm(turn.dynamic_form || null)
      setClaimRevision(turn.claim_revision, turn.primary_action)
      if (turn.decision) setNextStep(turn.decision.customer_next_step)
      if (turn.handoff) setHandoff(turn.handoff)
      rememberClaimInHistory({
        ...activeClaim,
        revision: turn.claim_revision,
        customer_next_step: turn.decision?.customer_next_step || activeClaim.customer_next_step,
        updated_at: turn.claimant_message?.created_at || activeClaim.updated_at,
      })
      setDraft('')
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
      let attachmentClaim = { ...activeClaim, revision: turn.claim_revision }
      let stagedUploadsSucceeded = true
      for (const attachment of stagedAttachments) {
        const upload = await uploadAttachment(
          attachment.stagedFile,
          attachment.uploadAttempt,
          attachmentClaim,
          { existingAttachment: true, settleStatus: false },
        )
        attachmentClaim = { ...attachmentClaim, revision: upload.revision }
        if (!upload.succeeded) {
          stagedUploadsSucceeded = false
          break
        }
      }
      if (stagedUploadsSucceeded) setStatus('idle')
    } catch (requestError) {
      if (isAssistanceReply) setAssistanceReplyReview(null)
      activeTurnProgressRef.current = null
      setActiveTurnProgress(null)
      setPendingMessage(null)
      if (messageWasSubmitted) {
        const serverConfirmedFailure = requestError instanceof ApiRequestError
          && Number.isInteger(requestError.status)
        const retryGuidance = requestError instanceof ApiRequestError && requestError.retryable
          ? 'Try again in a moment.'
          : 'Review the message and try again.'
        setFailedMessage({
          text,
          sender: 'You',
          message: serverConfirmedFailure
            ? `${requestError.message} ${retryGuidance}`
            : 'We could not confirm delivery because the connection ended before the service responded. Retry safely; the same request will not create a duplicate.',
        })
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

  function startNewChat() {
    if (isBusy) return
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
    replaceActiveClaimContext(null, null)
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
    setExpandedConversationPanels({})
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
    setWorkspaceActive(false)
    setDraft('')
    setClaimType('')
    setError('')
    setFailedMessage(null)
    setPendingMessage(null)
    activeTurnProgressRef.current = null
    setActiveTurnProgress(null)
    setMessageActivities({})
    setStatus('idle')
    setPageState('home')
    if (globalThis.location?.pathname !== '/') {
      globalThis.history?.pushState({ northwindRoute: 'home' }, '', '/')
    }
  }

  async function confirmProposedFields() {
    if (!claim || (proposedFields.length === 0 && proposedContentsItems.length === 0) || isBusy) return
    setError('')
    setStatus('confirming')
    try {
      const fieldCodes = [
        ...proposedFields.map(([fieldCode]) => fieldCode),
        ...(proposedContentsItems.length > 0 ? ['contents.items'] : []),
      ]
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
    } catch (requestError) {
      showError(requestError)
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
        if (hasClaimantAccessToken()) {
          setClaimHistory((history) => history?.filter((item) => item.claim_id !== claimId) || history)
        } else {
          setClaimHistory(forgetAnonymousConversation(claimId))
        }
        setError('This conversation can no longer be resumed, so it was removed from history.')
        setStatus('error')
        return
      }
      const session = await resumeClaimSession({ claimId })
      const current = await getClaim(claimId)
      const conversation = await getClaimMessages(claimId, session.session_id)
      clearComposerAttachments()
      replaceActiveClaimContext(current, session.session_id)
      if (session.model_profile_id) setSelectedModel(session.model_profile_id)
      commitMessages(conversation.items)
      setForm(current.form)
      setContentsItems(current.contents_items || [])
      setDynamicForm(current.dynamic_form || null)
      setNextStep(current.customer_next_step)
      setHandoff(current.handoff || null)
      setResumeContext({
        ...session.resume,
        resumed_at: session.started_at,
        resumed_after_message_id: conversation.items.at(-1)?.message_id || null,
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
    setAuthStatus('loading'); setAuthError('')
    try { await logoutClaimant() } catch (requestError) { setAuthError(requestError.message) }
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
    setSelectedHistoryClaimId(null)
    if (hasStarted) {
      setWorkspaceView('history')
      setMobileView('chat')
    } else {
      setPage('claim-history')
    }
    if (account) loadSavedReports().catch(() => {})
  }

  function openClaimFeatures(selectedClaim) {
    setSelectedHistoryClaimId(selectedClaim.claim_id)
    if (hasStarted) {
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
    if (hasStarted) {
      setWorkspaceView('claim-evidence')
      setMobileView('chat')
    } else {
      setPage('claim-evidence')
    }
  }

  function openCurrentClaimEvidence() {
    if (!claim?.claim_id) return
    setSelectedHistoryClaimId(claim.claim_id)
    setWorkspaceView('claim-evidence')
    setMobileView('chat')
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

  function returnToLanding() {
    clearComposerAttachments()
    pendingSubmission.current = null
    setDraft('')
    setClaimType('')
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

  return (
    <div className={`customer-app ${!isWorkspaceActive && page === 'home' ? 'entry-shell' : ''}`}>
      <header className={`product-header ${isWorkspaceActive && !['login', 'register'].includes(page) ? 'is-intake-header' : ''}`}>
        <div className="header-leading">
          <a className="brand" href="/" onClick={(event) => { event.preventDefault(); setPage('home') }} aria-label="Northwind home">
            <span className="brand-mark">N</span>
            <span>Northwind Insurance</span>
          </a>
          {isWorkspaceActive && !['login', 'register'].includes(page) && (
            <button
              className="header-back-to-start"
              type="button"
              aria-label="Back to start"
              onClick={returnToLanding}
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
              {account ? 'My account' : 'Log in'}
            </button>
            {!account && (
              <button className="entry-header-account" type="button" onClick={() => setPage('register')}>
                Sign up
              </button>
            )}
          </nav>
        )}
        {!isWorkspaceActive && page !== 'home' && page !== 'how-it-works' && (
          <button className="login-button" type="button" onClick={() => setPage(account ? 'account' : 'login')}>
            {account ? 'My account' : 'Log in'}
          </button>
        )}
        {isWorkspaceActive && !['login', 'register'].includes(page) && (
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
      ) : !isWorkspaceActive && ['claim-history', 'claim-features', 'claim-evidence'].includes(page) ? (
        <main className="evidence-history-page">
          {account ? (
            <section className="evidence-history-page-content" aria-labelledby="account-claim-view-title">
              <button
                className="back-link"
                type="button"
                onClick={page === 'claim-evidence'
                  ? () => setPage('claim-features')
                  : page === 'claim-features'
                    ? openClaimHistory
                    : () => setPage('account')}
              >
                <span className="back-link-arrow" aria-hidden="true">←</span>
                {page === 'claim-evidence'
                  ? 'Back to Claim features'
                  : page === 'claim-features'
                    ? 'Back to Claim history'
                    : 'Back to account'}
              </button>
              <p className="eyebrow">Northwind account</p>
              <h1 id="account-claim-view-title">
                {page === 'claim-history' ? 'Claim history' : page === 'claim-features' ? 'Claim features' : 'Evidence history'}
              </h1>
              <p>
                {page === 'claim-history'
                  ? 'Your Claims are listed by their latest server-recorded update. Open a Claim to review its available features.'
                  : page === 'claim-features'
                    ? 'Review this Claim\'s current status and available information.'
                    : 'Review the files and supporting material recorded for the selected Claim.'}
              </p>
              {page === 'claim-history' && (
                <ClaimHistory
                  claims={claimHistory}
                  error={claimHistoryError}
                  loading={claimHistory === null && !claimHistoryError}
                  refreshing={status === 'loading-reports'}
                  onRetry={loadSavedReports}
                  onSelect={openClaimFeatures}
                />
              )}
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
      ) : !isWorkspaceActive && page === 'account' && account ? (
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
              View Claim history
            </button>
            <button className="secondary-button" type="button" onClick={() => setPage('files')}>
              View evidence history
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
      ) : !isWorkspaceActive ? (
        <main className="entry-page">
          <section className="entry-hero" aria-labelledby="entry-title">
            <div className="entry-content">
              <p className="entry-brand-line">
                <span>Understand insurance.</span>
                {' '}
                <span>Understand you better.</span>
              </p>
              <h1 className="entry-task-title" id="entry-title">Start your insurance claim</h1>
              <p className="entry-intro">Tell us what happened — we&apos;ll guide you through the next steps.</p>
              <section id="claims" className="claim-starter" aria-label="Start a claim">
                <MessageComposer
                  draft={draft}
                  setDraft={setDraft}
                  onSubmit={sendMessage}
                  inputLabel="Incident description"
                  busy={isBusy}
                  buttonLabel={status === 'starting' ? 'Starting claim...' : failedMessage ? 'Retry claim message' : 'Start claim'}
                  error={error}
                  placeholder="Tell us what happened…"
                  showClaimTypeControl
                  showModelControl
                  claimType={claimType}
                  setClaimType={setClaimType}
                  claimTypes={runtimeCapabilities.claim_types}
                  models={runtimeCapabilities.models}
                  selectedModel={selectedModel}
                  setSelectedModel={setSelectedModel}
                  claimTypeLocked={isWorkspaceActive && Boolean(sessionId)}
                  attachments={attachments}
                  onFileSelected={handleFileSelected}
                  onRemoveAttachment={removeComposerAttachment}
                />
                {failedMessage && (
                  <article className="message message-claimant is-failed">
                    <p className="message-author">{failedMessage.sender}</p>
                    <p>{failedMessage.text}</p>
                    <p className="message-state">{failedMessage.message}</p>
                  </article>
                )}
              </section>
              <div className="entry-tertiary-links">
                <button className="text-link entry-process-link" type="button" onClick={() => setPage('how-it-works')}>
                  How does the claim process work?
                </button>
              </div>
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
              <button type="button" onClick={openClaimHistory}>Claim history</button>
              <button type="button" onClick={() => setWorkspaceView('external-services')}>External services</button>
              <button
                className="history-action-button"
                type="button"
                aria-label={documentOutstandingCount > 0
                  ? `What to provide, ${documentOutstandingCount} outstanding`
                  : 'What to provide'}
                onClick={openCurrentClaimDocuments}
              >
                <span>What to provide</span>
                {documentOutstandingCount > 0 && (
                  <span className="history-action-count" aria-hidden="true">
                    {documentOutstandingCount}
                  </span>
                )}
              </button>
            </div>
            <div className="intake-history-label">Conversation history</div>
            <div className="intake-history-list">
              {conversationReports.map((report) => {
                const isCurrent = report.claim_id === claim.claim_id
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
                        ? `${report.incident_type || 'New report'} · ${report.claim_id}`
                        : report.customer_next_step.summary}
                    </span>
                  </button>
                )
              })}
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
          <section ref={conversationPanelRef} className={`conversation-panel mobile-view-${mobileView} ${workspaceView !== 'chat' ? 'is-utility' : ''}`} aria-labelledby="conversation-title">
            <div
              className={`workspace-utility-page ${['history', 'claim-features', 'claim-evidence', 'files'].includes(workspaceView) ? 'is-claim-record-page' : ''}`}
              hidden={workspaceView === 'chat'}
            >
              <button
                className="back-link"
                type="button"
                onClick={workspaceView === 'claim-evidence'
                  ? () => setWorkspaceView('claim-features')
                  : workspaceView === 'claim-features'
                    ? openClaimHistory
                    : leaveWorkspaceUtility}
              >
                <span className="back-link-arrow" aria-hidden="true">←</span>
                {workspaceView === 'claim-evidence'
                  ? 'Back to Claim features'
                  : workspaceView === 'claim-features'
                    ? 'Back to Claim history'
                    : 'Back to conversation'}
              </button>
              <h1>
                {workspaceView === 'privacy'
                  ? 'Privacy policy'
                  : workspaceView === 'history'
                    ? 'Claim history'
                    : workspaceView === 'claim-features'
                      ? 'Claim features'
                      : workspaceView === 'external-services'
                        ? 'External services'
                        : workspaceView === 'account'
                          ? 'Your account'
                          : 'Evidence history'}
              </h1>
              <p>
                {workspaceView === 'privacy'
                  ? 'We only use the information needed to handle your Claim and show you what has been recorded.'
                  : workspaceView === 'history'
                    ? 'Your Claims are listed by their latest server-recorded update. Open a Claim to review its available features.'
                    : workspaceView === 'claim-features'
                      ? 'Review this Claim\'s current status and available information.'
                      : workspaceView === 'external-services'
                        ? 'See the external service currently recorded for this Claim, including what may be shared and what happens next.'
                        : workspaceView === 'account'
                          ? 'Manage your profile and communication preferences.'
                          : workspaceView === 'claim-evidence'
                            ? 'Review the files and supporting material recorded for the selected Claim.'
                            : 'Review files retained across your Northwind Claims, including where they came from and their latest processing state.'}
              </p>
              {workspaceView === 'history' && (
                account ? (
                  <ClaimHistory
                    claims={claimHistory}
                    error={claimHistoryError}
                    loading={claimHistory === null && !claimHistoryError}
                    refreshing={status === 'loading-reports'}
                    onRetry={loadSavedReports}
                    onSelect={openClaimFeatures}
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
              {workspaceView === 'claim-evidence' && selectedHistoryClaim && (
                <EvidenceHistory claimId={selectedHistoryClaim.claim_id} />
              )}
              {workspaceView === 'external-services' && (
                claim.external_service_action
                  ? <ExternalServiceOverview action={claim.external_service_action} />
                  : <p className="empty-details">No external service is currently recorded for this claim.</p>
              )}
              {workspaceView === 'files' && (
                account ? (
                  <EvidenceHistory
                    currentClaimId={claim.claim_id}
                    currentClaimRevision={claim.revision}
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
            <div className="conversation-heading">
              <div className="conversation-heading-main">
                <div className="claim-heading-identity">
                  <span>Claim:</span>
                  <h1 id="conversation-title">{claim.claim_id}</h1>
                </div>
              </div>
              <div className="claim-status">{handoff ? 'Staff assistance active' : 'In progress'}</div>
            </div>

            <ClaimProgressDisclosure
              progress={progress}
              expanded={conversationPanelExpanded('progress')}
              onToggle={() => toggleConversationPanel('progress')}
            />

            <div
              ref={messageListRef}
              className="message-list"
              aria-live="polite"
              onScroll={handleMessageListScroll}
            >
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
                    <article className="msg-user" key={item.key}>
                      <div>
                        <div className="user-bubble">{messageText(message)}</div>
                        <div className="msg-meta">{new Date(message.created_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</div>
                      </div>
                    </article>
                  )
                }
                if (message.actor === 'staff') {
                  return (
                    <article className="msg-staff" key={item.key}>
                      <div className="staff-mark" aria-hidden="true">N</div>
                      <div className="staff-message-body">
                        <div className="staff-label">Northwind staff</div>
                        <div className="staff-bubble">{messageText(message)}</div>
                        <div className="msg-meta">{new Date(message.created_at).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</div>
                      </div>
                    </article>
                  )
                }
                if (message.actor === 'system') {
                  return (
                    <div className="conversation-system-event" key={item.key}>
                      <span aria-hidden="true">✓</span>
                      <span>{messageText(message)}</span>
                    </div>
                  )
                }
                return (
                  <article className="msg-agent" key={item.key}>
                    <div className="agent-bar" />
                    <div className="agent-body">
                      <div className="agent-label">Claims assistant</div>
                      <AgentTurnDisclosure progress={messageActivities[message.message_id]} />
                      <div className="agent-text"><p>{messageText(message)}</p><button className="listen-message" type="button" onClick={() => { if (globalThis.speechSynthesis) { globalThis.speechSynthesis.cancel(); globalThis.speechSynthesis.speak(new SpeechSynthesisUtterance(messageText(message))) } }}>Listen</button></div>
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
                      {item.key === lastAgentMessageId && conversationActionKind && (
                        <div className="conversation-agent-action">
                          {renderConversationAction()}
                        </div>
                      )}
                    </div>
                  </article>
                )
              })}
              {!lastAgentMessageId && conversationActionKind && (
                <div className="conversation-agent-action is-standalone">
                  {renderConversationAction()}
                </div>
              )}
              {pendingMessage && (
                <>
                  <article className="msg-user is-pending" aria-label="Message sending">
                    <div>
                      <div className="user-bubble">{pendingMessage.text}</div>
                      <div className="msg-meta">Sending…</div>
                    </div>
                  </article>
                  <AgentTurnPlaceholder
                    progress={activeTurnProgress}
                    turnId={pendingMessage.turnId}
                  />
                </>
              )}
              {failedMessage && (
                <article className="message message-claimant is-failed" role="alert">
                  <p className="message-author">{failedMessage.sender}</p>
                  <p>{failedMessage.text}</p>
                  <p className="message-state">Not sent</p>
                </article>
              )}
              {isUrgentSupport && handoff && ['queued', 'accepted'].includes(handoff.status) && (
                <ConversationEvent
                  icon="!"
                  title="Urgent support · Normal intake has paused"
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

              {claim.external_claim && (
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
                : 'Write the details you know...'}
              buttonLabel={status === 'sending'
                ? 'Sending...'
                : failedMessage
                  ? 'Retry message'
                  : assistanceState?.key === 'response_needed'
                    ? 'Send reply'
                    : 'Send'}
              error={failedMessage?.message || error}
              variant="workspace"
              claimType={claimType}
              setClaimType={setClaimType}
              claimTypes={runtimeCapabilities.claim_types}
              models={runtimeCapabilities.models}
              selectedModel={selectedModel}
              setSelectedModel={setSelectedModel}
              claimTypeLocked={Boolean(sessionId)}
              attachments={attachments}
              onFileSelected={handleFileSelected}
              onRemoveAttachment={removeComposerAttachment}
            />
          </section>

          {!detailsOpen && workspaceView === 'chat' && (
            <button className="details-reopen" type="button" onClick={() => setDetailsOpen(true)} aria-label="Show claim details" title="Show claim details">‹</button>
          )}
          <aside className={`claim-panel intake-details-panel mobile-view-${mobileView} ${detailsOpen && workspaceView === 'chat' ? 'is-open' : 'is-collapsed'} ${workspaceView !== 'chat' ? 'is-hidden' : ''}`} aria-labelledby="claim-details-title">
            <div className="claim-panel-heading">
              <div>
                <p className="eyebrow">Your claim</p>
                <h2 id="claim-details-title">Claim details</h2>
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
            <div className="claim-details-tabs" role="tablist" aria-label="Claim details">
              {[
                ['summary', 'Summary'],
                ['documents', 'What to provide'],
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
                  {label}
                </button>
              ))}
            </div>
            <div id="claim-details-body" hidden={!detailsOpen}>
            <div
              id="claim-details-summary-panel"
              role="tabpanel"
              aria-labelledby="claim-details-summary-tab"
              tabIndex="0"
              hidden={detailsTab !== 'summary'}
            >
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
              />
            </div>
            <div
              id="claim-details-documents-panel"
              role="tabpanel"
              aria-labelledby="claim-details-documents-tab"
              tabIndex="0"
              hidden={detailsTab !== 'documents'}
            >
              {claim.external_capabilities?.length > 0 && (
                <button
                  ref={externalCapabilitiesTriggerRef}
                  className="external-capabilities-trigger"
                  type="button"
                  aria-haspopup="dialog"
                  onClick={() => setExternalCapabilitiesOpen(true)}
                >
                  <span>
                    <strong>Third-party support</strong>
                    <small>{claim.external_capabilities.length} services available</small>
                  </span>
                  <span aria-hidden="true">View</span>
                </button>
              )}
              {detailsTab === 'documents' && workspaceView === 'chat' && (
                <ClaimDocuments
                  items={evidenceItems}
                  loadStatus={evidenceLoadStatus}
                  busy={isBusy}
                  onUpload={(item, file) => handleFileSelected(
                    file,
                    null,
                    item.kind,
                    item.evidence_id,
                  )}
                  onView={openCurrentClaimEvidence}
                />
              )}
            </div>
            </div>
          </aside>
          {claim.external_capabilities?.length > 0 && (
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
