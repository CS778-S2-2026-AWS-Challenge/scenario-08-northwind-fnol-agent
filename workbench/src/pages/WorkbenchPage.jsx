import { Menu, PanelLeftClose, PanelLeftOpen, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useLocation, useNavigate, useParams, useSearchParams } from 'react-router-dom'
import { workbenchApi } from '../api.js'
import { useAuth } from '../auth/auth-context.js'
import ClaimTabs from '../components/ClaimTabs.jsx'
import ClaimWorkspace from '../components/ClaimWorkspace.jsx'
import NavigationRail from '../components/NavigationRail.jsx'
import QueuePanel from '../components/QueuePanel.jsx'
import StaffAgent from '../components/StaffAgent.jsx'
import { usePersistentTabs } from '../hooks/usePersistentTabs.js'
import { actionFailureMessage, failureReason, failureReference } from '../failure.js'
import { revisionNotice as buildRevisionNotice } from '../revision.js'
import ConversationsPage from './ConversationsPage.jsx'

export default function WorkbenchPage() {
  const { token, profile, logout } = useAuth()
  const { claimId, section: routeSection, agentSessionId: routeAgentSessionId, conversationSessionId } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const [searchParams, setSearchParams] = useSearchParams()
  const tabs = usePersistentTabs()
  const openTab = tabs.open
  const [claims, setClaims] = useState([])
  const [viewCounts, setViewCounts] = useState(UNAVAILABLE_VIEW_COUNTS)
  const [filterMetadata, setFilterMetadata] = useState(null)
  const [filterMetadataLoading, setFilterMetadataLoading] = useState(true)
  const [filterMetadataError, setFilterMetadataError] = useState(null)
  const [filterMetadataAttempt, setFilterMetadataAttempt] = useState(0)
  const [nextCursor, setNextCursor] = useState(null)
  const [queueLoading, setQueueLoading] = useState(false)
  const [queueError, setQueueError] = useState(null)
  const [queueNotice, setQueueNotice] = useState('')
  const [movementNotice, setMovementNotice] = useState(null)
  const queueRequestId = useRef(0)
  const queueSnapshotKeyRef = useRef('')
  const [queueSnapshotKey, setQueueSnapshotKey] = useState('')
  const [conversations, setConversations] = useState([])
  const [conversationsLoading, setConversationsLoading] = useState(false)
  const [conversationsError, setConversationsError] = useState(null)
  const [detail, setDetail] = useState(null)
  const detailRef = useRef(null)
  const currentClaimIdRef = useRef(claimId)
  currentClaimIdRef.current = claimId
  const detailRequestId = useRef(0)
  const backgroundRefreshId = useRef(0)
  const resourceRequestIds = useRef({})
  const [resources, setResources] = useState({})
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState(null)
  const [detailStale, setDetailStale] = useState(false)
  const [queueVisible, setQueueVisible] = useState(true)
  const [agentOpen, setAgentOpen] = useState(false)
  const [agentSessionId, setAgentSessionId] = useState(null)
  const [revisionNotice, setRevisionNotice] = useState(null)
  const isConversations = location.pathname === '/workbench/conversations' || location.pathname.startsWith('/workbench/conversations/')
  const isAgentRoute = Boolean(routeAgentSessionId)
  const selectedSessionId = new URLSearchParams(location.search).get('session')
  const currentTab = tabs.tabs.find((tab) => tab.claimId === claimId)
  const currentSection = CLAIM_SECTIONS.has(routeSection)
    ? routeSection
    : currentTab?.section || 'summary'
  const queueFilters = useMemo(
    () => readQueueFilters(searchParams, filterMetadata),
    [filterMetadata, searchParams],
  )
  const {
    view,
    viewAvailable,
    workflowState,
    priority,
    assigneeId,
    nextAction,
    tagFilter,
    search,
    updatedBefore,
    updatedAfter,
  } = queueFilters
  const currentQueueKey = queueFilterKey(queueFilters)
  const visibleClaims = queueSnapshotKey === currentQueueKey ? claims : []

  const openConversation = useCallback((conversation) => {
    if (conversation.kind === 'staff_agent') {
      setAgentSessionId(conversation.session_id)
      setAgentOpen(true)
      navigate(queueRoute(`/workbench/agent/sessions/${encodeURIComponent(conversation.session_id)}`, queueFilters))
      return
    }
    tabs.open({
      claim_id: conversation.claim_id,
      display_reference: conversation.display_reference,
    })
    tabs.update(conversation.claim_id, {
      section: 'conversation',
      sessionId: conversation.session_id,
    })
    navigate(queueRoute(`/workbench/claims/${conversation.claim_id}/conversation`, queueFilters, conversation.session_id))
  }, [navigate, queueFilters, tabs])

  const applyDetailProjection = useCallback((response, {
    expectedClaimId,
    requestId = null,
    announceRevision = false,
  }) => {
    if (
      currentClaimIdRef.current !== expectedClaimId
      || response?.claim_id !== expectedClaimId
      || (requestId !== null && detailRequestId.current !== requestId)
    ) return null
    if (isOlderClaimProjection(response, detailRef.current)) return detailRef.current

    detailRef.current = response
    setDetail((current) => {
      if (announceRevision) {
        const notice = buildRevisionNotice(current, response)
        if (notice) setRevisionNotice(notice)
      }
      return response
    })
    setDetailError(null)
    setDetailStale(false)
    openTab(response)
    return response
  }, [openTab])

  const loadClaims = useCallback(async ({ cursor = null, append = false } = {}) => {
    if (!filterMetadata || !viewAvailable) return
    const requestId = ++queueRequestId.current
    const snapshotKey = queueFilterKey(queueFilters)
    const sameSnapshot = queueSnapshotKeyRef.current === snapshotKey
    setQueueLoading(true)
    setQueueError(null)
    setQueueNotice('')
    if (!append) {
      setNextCursor(null)
      if (!sameSnapshot) {
        setClaims([])
        setViewCounts(UNAVAILABLE_VIEW_COUNTS)
      }
    }
    try {
      const response = await workbenchApi.claims(token, queueRequestFilters(queueFilters, cursor))
      if (requestId !== queueRequestId.current) return
      setClaims((current) => append ? [...current, ...response.items] : response.items)
      queueSnapshotKeyRef.current = snapshotKey
      setQueueSnapshotKey(snapshotKey)
      setNextCursor(response.page?.next_cursor || null)
      setViewCounts(response.view_counts || UNAVAILABLE_VIEW_COUNTS)
    } catch (error) {
      if (requestId !== queueRequestId.current) return
      if (append && error.code === 'VALIDATION_ERROR') {
        try {
          const response = await workbenchApi.claims(token, queueRequestFilters(queueFilters))
          if (requestId !== queueRequestId.current) return
          setClaims(response.items)
          queueSnapshotKeyRef.current = snapshotKey
          setQueueSnapshotKey(snapshotKey)
          setNextCursor(response.page?.next_cursor || null)
          setViewCounts(response.view_counts || UNAVAILABLE_VIEW_COUNTS)
          setQueueNotice('The saved queue page was invalid or stale, so current work was reloaded from the start.')
          return
        } catch (recoveryError) {
          if (requestId === queueRequestId.current) setQueueError(recoveryError)
          return
        }
      }
      setQueueError(error)
    } finally {
      if (requestId === queueRequestId.current) setQueueLoading(false)
    }
  }, [filterMetadata, queueFilters, token, viewAvailable])

  const loadDetail = useCallback(async (id) => {
    const requestId = ++detailRequestId.current
    if (!id) {
      detailRef.current = null
      setDetail(null)
      return
    }
    const preserve = detailRef.current?.claim_id === id
    if (!preserve) {
      detailRef.current = null
      setDetail(null)
      setResources({})
    }
    setDetailLoading(true)
    setDetailError(null)
    setDetailStale(false)
    setResources((current) => {
      const base = preserve ? current : {}
      return {
        ...base,
        handoffs: { ...(base.handoffs || {}), loading: true, error: null },
        collaborationRequests: { ...(base.collaborationRequests || {}), loading: true, error: null },
      }
    })
    const supportingRequest = Promise.allSettled([
      workbenchApi.handoffs(token, id),
      workbenchApi.collaborationRequests(token, id),
    ])
    try {
      const response = await workbenchApi.claim(token, id)
      if (!applyDetailProjection(response, { expectedClaimId: id, requestId })) return
      setDetailLoading(false)
      const [handoffs, collaborationRequests] = await supportingRequest
      if (requestId !== detailRequestId.current) return
      setResources((current) => ({
        ...current,
        handoffs: settledResourceState(handoffs, current.handoffs),
        collaborationRequests: settledResourceState(
          collaborationRequests,
          current.collaborationRequests,
        ),
      }))
    } catch (error) {
      if (requestId !== detailRequestId.current) return
      if (!preserve || isInaccessibleError(error)) {
        detailRef.current = null
        setDetail(null)
        setResources({})
      } else {
        setDetailStale(true)
      }
      setDetailError(error)
    } finally {
      if (requestId === detailRequestId.current) setDetailLoading(false)
    }
  }, [applyDetailProjection, token])

  const refreshDetail = useCallback(async (id) => {
    if (!id) return
    const refreshId = ++backgroundRefreshId.current
    const detailGeneration = detailRequestId.current
    try {
      const response = await workbenchApi.claim(token, id)
      applyDetailProjection(response, {
        expectedClaimId: id,
        requestId: detailGeneration,
        announceRevision: true,
      })
    } catch (error) {
      if (
        currentClaimIdRef.current !== id
        || detailRequestId.current !== detailGeneration
        || backgroundRefreshId.current !== refreshId
      ) return
      if (isInaccessibleError(error)) {
        detailRef.current = null
        setDetail(null)
        setResources({})
      } else {
        setDetailStale(true)
      }
      setDetailError(error)
    }
  }, [applyDetailProjection, token])

  const loadResource = useCallback(async (name, ownerId, loader) => {
    const requestId = (resourceRequestIds.current[name] || 0) + 1
    resourceRequestIds.current[name] = requestId
    setResources((current) => ({
      ...current,
      [name]: { ...(current[name] || {}), loading: true, error: null },
    }))
    try {
      const response = await loader()
      if (currentClaimIdRef.current !== ownerId || resourceRequestIds.current[name] !== requestId) return null
      setResources((current) => ({ ...current, [name]: resourceState(response) }))
      return response
    } catch (error) {
      if (currentClaimIdRef.current !== ownerId || resourceRequestIds.current[name] !== requestId) return null
      setResources((current) => ({
        ...current,
        [name]: {
          ...(current[name] || {}),
          items: current[name]?.items || [],
          status: 'unavailable',
          limitation: current[name]?.limitation || null,
          loading: false,
          stale: Boolean(current[name]?.items?.length),
          error,
        },
      }))
      return null
    }
  }, [])

  const loadConversationResources = useCallback(async (id, requestedSessionId) => {
    const sessions = await loadResource('sessions', id, () => workbenchApi.sessions(token, id))
    if (!sessions) {
      if (currentClaimIdRef.current === id) {
        setResources((current) => {
          const previous = current.messages || {}
          return {
            ...current,
            messages: {
              ...previous,
              items: previous.items || [],
              status: 'unavailable',
              limitation: 'Conversation messages cannot be loaded until the session list is available.',
              loading: false,
              stale: Boolean(previous.items?.length),
              error: current.sessions?.error || null,
            },
          }
        })
      }
      return
    }
    const session = sessions?.items?.find((item) => item.session_id === requestedSessionId)
      || sessions?.items?.at(-1)
    if (session) {
      await loadResource('messages', id, () => workbenchApi.messages(token, id, session.session_id))
    } else if (currentClaimIdRef.current === id) {
      setResources((current) => ({ ...current, messages: resourceState({ items: [] }) }))
    }
  }, [loadResource, token])

  const loadSectionResources = useCallback(async (id, section) => {
    const loaders = {
      summary: [],
      fields: [['fields', () => workbenchApi.fields(token, id)]],
      evidence: [['evidence', () => workbenchApi.evidence(token, id)]],
      references: [['retrievals', () => workbenchApi.retrievals(token, id)]],
      'external-services': [['externalRequests', () => workbenchApi.externalRequests(token, id)]],
      signals: [['signals', () => workbenchApi.signals(token, id)]],
      activity: [
        ['workItems', () => workbenchApi.workItems(token, id)],
        ['customerUpdates', () => workbenchApi.customerUpdates(token, id)],
        ['events', () => workbenchApi.events(token, id)],
      ],
    }
    if (section === 'conversation') {
      await loadConversationResources(id, selectedSessionId)
      return
    }
    await Promise.all((loaders[section] || []).map(([name, loader]) => loadResource(name, id, loader)))
  }, [loadConversationResources, loadResource, selectedSessionId, token])

  const loadConversations = useCallback(async () => {
    setConversationsLoading(true)
    setConversationsError(null)
    try {
      const response = await workbenchApi.conversations(token)
      setConversations(response.items || [])
    } catch (error) {
      setConversationsError(error)
    } finally {
      setConversationsLoading(false)
    }
  }, [token])

  useEffect(() => {
    let active = true
    ++queueRequestId.current
    setFilterMetadata(null)
    setFilterMetadataLoading(true)
    setFilterMetadataError(null)
    setQueueLoading(false)
    workbenchApi.claimFilterMetadata(token).then(
      (response) => {
        if (active) setFilterMetadata(response)
      },
      (error) => {
        if (active) setFilterMetadataError(error)
      },
    ).finally(() => {
      if (active) setFilterMetadataLoading(false)
    })
    return () => { active = false }
  }, [filterMetadataAttempt, token])
  useEffect(() => {
    if (!filterMetadata) return
    const normalized = normalizeQueueSearchParams(searchParams, filterMetadata)
    if (normalized.toString() !== searchParams.toString()) {
      setSearchParams(normalized, { replace: true })
    }
  }, [filterMetadata, searchParams, setSearchParams])
  useEffect(() => {
    loadClaims()
  }, [loadClaims])
  useEffect(() => {
    if (isConversations) loadConversations()
  }, [isConversations, loadConversations])
  useEffect(() => {
    if (!conversationSessionId || !conversations.length) return
    const conversation = conversations.find((item) => item.session_id === conversationSessionId)
    if (conversation) openConversation(conversation)
  }, [conversationSessionId, conversations, openConversation])
  useEffect(() => {
    if (isAgentRoute) {
      setAgentSessionId(routeAgentSessionId)
      setAgentOpen(true)
    }
  }, [isAgentRoute, routeAgentSessionId])
  useEffect(() => {
    if (claimId) {
      loadDetail(claimId)
    } else if (!isConversations) {
      ++detailRequestId.current
      detailRef.current = null
      setDetail(null)
      setDetailError(null)
      setDetailStale(false)
      setResources({})
    }
  }, [claimId, isConversations, loadDetail])
  useEffect(() => {
    if (claimId && detail?.claim_id === claimId) {
      loadSectionResources(claimId, currentSection)
    }
  }, [claimId, currentSection, detail?.claim_id, detail?.revision, loadSectionResources])
  useEffect(() => {
    if (!claimId) return undefined
    const timer = window.setInterval(() => refreshDetail(claimId), 20000)
    return () => window.clearInterval(timer)
  }, [claimId, refreshDetail])
  useEffect(() => {
    if (filterMetadata && claimId && routeSection && !CLAIM_SECTIONS.has(routeSection)) {
      navigate(queueRoute(`/workbench/claims/${claimId}`, queueFilters), { replace: true })
    }
  }, [claimId, filterMetadata, navigate, queueFilters, routeSection])

  function openClaim(claim) {
    tabs.open(claim)
    navigate(queueRoute(`/workbench/claims/${claim.claim_id}`, queueFilters))
  }

  function activateTab(id) {
    tabs.activate(id)
    const tab = tabs.tabs.find((item) => item.claimId === id)
    const suffix = tab?.section && tab.section !== 'summary' ? `/${tab.section}` : ''
    const query = tab?.section === 'conversation' && tab.sessionId
      ? `?session=${encodeURIComponent(tab.sessionId)}`
      : ''
    navigate(queueRoute(`/workbench/claims/${id}${suffix}`, queueFilters, query ? tab.sessionId : null))
  }

  function closeTab(id) {
    const wasActive = tabs.activeId === id
    const index = tabs.tabs.findIndex((item) => item.claimId === id)
    const remaining = tabs.tabs.filter((item) => item.claimId !== id)
    tabs.close(id)
    if (wasActive) {
      const neighbour = remaining[Math.min(index, remaining.length - 1)]
      const suffix = neighbour?.section && neighbour.section !== 'summary'
        ? `/${neighbour.section}`
        : ''
      navigate(queueRoute(neighbour ? `/workbench/claims/${neighbour.claimId}${suffix}` : '/workbench', queueFilters))
    }
  }

  function changeSection(section) {
    if (!claimId) return
    tabs.update(claimId, { section, ...(section === 'conversation' ? {} : { sessionId: null }) })
    const suffix = section === 'summary' ? '' : `/${section}`
    const query = section === 'conversation' && currentTab?.sessionId
      ? `?session=${encodeURIComponent(currentTab.sessionId)}`
      : ''
    navigate(
      queueRoute(`/workbench/claims/${claimId}${suffix}`, queueFilters, query ? currentTab.sessionId : null),
      { replace: true },
    )
  }

  function setQueueFilter(name, value) {
    setSearchParams((current) => {
      const next = new URLSearchParams(current)
      const normalized = value.trim()
      if (!normalized || (name === 'view' && normalized === 'all')) next.delete(name)
      else next.set(name, normalized)
      next.delete('cursor')
      return next
    }, { replace: true })
  }

  function clearQueueFilters() {
    setSearchParams((current) => {
      const next = new URLSearchParams(current)
      for (const name of QUEUE_FILTER_PARAM_NAMES) next.delete(name)
      next.delete('cursor')
      return next
    }, { replace: true })
  }

  async function runClaimMutation(label, operation) {
    const previous = detailRef.current
    if (!previous) throw new Error('The current Claim projection is unavailable. Refresh the Claim before acting.')
    const mutationRequestId = ++detailRequestId.current
    try {
      await operation(previous)
    } catch (error) {
      let latest = null
      const refreshGeneration = backgroundRefreshId.current
      try {
        const response = await workbenchApi.claim(token, previous.claim_id)
        latest = applyDetailProjection(response, {
          expectedClaimId: previous.claim_id,
          requestId: mutationRequestId,
        })
        error.projectionReloaded = Boolean(latest)
        error.projectionChanged = latest ? latest.revision !== previous.revision : false
        error.latestRevision = latest?.revision
        await loadClaims()
      } catch (reloadError) {
        const current = detailRef.current
        const newerProjectionIsShown = current?.claim_id === previous.claim_id
          && current.revision > previous.revision
        if (
          currentClaimIdRef.current === previous.claim_id
          && detailRequestId.current === mutationRequestId
          && backgroundRefreshId.current === refreshGeneration
          && !newerProjectionIsShown
        ) {
          if (isInaccessibleError(reloadError)) {
            detailRef.current = null
            setDetail(null)
            setResources({})
          } else {
            setDetailStale(true)
          }
          setDetailError(reloadError)
        }
      }
      error.message = actionFailureMessage(label, error, latest)
      throw error
    }
    if (currentClaimIdRef.current === previous.claim_id) {
      await Promise.all([loadDetail(previous.claim_id), loadClaims()])
    } else {
      await loadClaims()
    }
  }

  async function acceptHandoff(handoff) {
    await runClaimMutation('Accepting the handoff', (current) => (
      workbenchApi.acceptHandoff(
        token,
        current.claim_id,
        handoff.handoff_id,
        current.revision,
      )
    ))
  }

  async function resolveHandoff(handoff, payload) {
    await runClaimMutation('Resolving the handoff', (current) => (
      workbenchApi.resolveHandoff(
        token,
        current.claim_id,
        handoff.handoff_id,
        current.revision,
        payload,
      )
    ))
  }

  async function decideSignal(signalId, payload) {
    await runClaimMutation('Recording the signal decision', (current) => (
      workbenchApi.decideSignal(token, current.claim_id, signalId, current.revision, payload)
    ))
  }

  async function createStaffAction(payload) {
    await runClaimMutation('Creating the staff action', (current) => (
      workbenchApi.createStaffAction(token, current.claim_id, current.revision, payload)
    ))
  }

  async function updateStaffAction(actionId, payload) {
    await runClaimMutation('Updating the staff action', (current) => (
      workbenchApi.updateStaffAction(
        token,
        current.claim_id,
        actionId,
        current.revision,
        payload,
      )
    ))
  }

  function loadEvidence(evidenceId) {
    return workbenchApi.evidenceContent(token, detail.claim_id, evidenceId)
  }

  async function sendMessage(message) {
    await runClaimMutation('Sending the claimant message', (current) => (
      workbenchApi.sendMessage(token, current.claim_id, message, current.revision)
    ))
  }

  async function performOwnershipAction(action, payload) {
    let operation
    if (action.action_code === 'ownership.request_cowork' || action.action_code === 'ownership.invite_cowork') {
      operation = (current) => workbenchApi.requestCowork(token, current.claim_id, current.revision, payload)
    } else if (action.action_code === 'ownership.request_transfer') {
      operation = (current) => workbenchApi.requestTransfer(token, current.claim_id, current.revision, payload)
    } else if (action.action_code === 'ownership.requeue') {
      operation = (current) => workbenchApi.requeue(token, current.claim_id, current.revision, payload)
    } else if (action.target_type === 'collaboration_request') {
      operation = (current) => workbenchApi.decideCollaboration(token, current.claim_id, action.target_ref, current.revision, payload)
    } else {
      throw new Error('This ownership action is not connected. Refresh the Claim and try again.')
    }
    await runClaimMutation(action.label, operation)
  }

  async function reopenClaim(action, payload, idempotencyKey) {
    const current = detail
    if (
      action.action_code !== 'claim.reopen'
      || action.target_type !== 'claim'
      || action.target_ref !== current.claim_id
      || action.based_on_revision !== current.revision
    ) {
      throw new Error('The projected reopen action no longer matches this Claim revision. Refresh the Claim and review the current action.')
    }

    const mutationRequestId = ++detailRequestId.current
    let accepted = false
    try {
      await workbenchApi.reopenClaim(
        token,
        current.claim_id,
        action.based_on_revision,
        payload,
        idempotencyKey,
      )
      accepted = true
      const latest = await workbenchApi.claim(token, current.claim_id)
      applyReopenProjection(latest, true, null, mutationRequestId, current.claim_id)
    } catch (error) {
      try {
        const latest = await workbenchApi.claim(token, current.claim_id)
        const projection = applyReopenProjection(
          latest,
          accepted,
          error,
          mutationRequestId,
          current.claim_id,
        )
        if (accepted) return
        error.projectionReloaded = Boolean(projection)
        error.projectionChanged = projection ? projection.revision !== current.revision : false
        error.latestRevision = projection?.revision
      } catch {
        // The dialog keeps the original actionable mutation error when resynchronisation fails.
      }
      throw error
    }
  }

  function applyReopenProjection(response, accepted, error, requestId, expectedClaimId) {
    const latest = applyDetailProjection(response, { expectedClaimId, requestId })
    if (!latest) return null
    const queueKey = latest.work_summary?.queue_key
    const queueOption = filterMetadata?.views.find((option) => option.value === queueKey)
    if (queueOption) {
      setSearchParams((current) => {
        const next = new URLSearchParams(current)
        if (queueKey === 'all') next.delete('view')
        else next.set('view', queueKey)
        next.delete('cursor')
        return next
      }, { replace: true })
    }
    setMovementNotice({
      claimId: latest.claim_id,
      revision: latest.revision,
      kind: accepted ? 'status' : 'error',
      message: accepted
        ? `Claim ${latest.display_reference || latest.claim_id} reopened at revision ${latest.revision} and moved to ${queueOption?.label || queueKey || 'its server-projected queue'}.`
        : reopenFailureNotice(error, latest, queueOption?.label || queueKey),
    })
    return latest
  }

  return (
    <div className="workbench-app">
      <NavigationRail profile={profile} onLogout={async () => { await logout(); navigate('/workbench/login', { replace: true }) }} onAgent={() => setAgentOpen(true)} />
      <div className="workbench-stage">
        <header className="workbench-topbar">
          <button className="icon-button mobile-menu" type="button" aria-label="Open navigation"><Menu size={19} /></button>
          <div><strong>Claims Workbench</strong><span>Source-linked operational view</span></div>
          <div className="topbar-actions">
            {!isConversations && <button className="icon-button" type="button" onClick={() => setQueueVisible((value) => !value)} aria-label={queueVisible ? 'Hide Claim queue' : 'Show Claim queue'}>{queueVisible ? <PanelLeftClose size={18} /> : <PanelLeftOpen size={18} />}</button>}
            <button className="icon-button" type="button" onClick={filterMetadata ? loadClaims : () => setFilterMetadataAttempt((attempt) => attempt + 1)} aria-label="Refresh Workbench projection"><RefreshCw size={17} /></button>
          </div>
        </header>
        {queueNotice && <div className="global-error" role="status">{queueNotice}</div>}
        {movementNotice && (
          <div className={`movement-notice${movementNotice.kind === 'error' ? ' movement-notice--error' : ''}`} role={movementNotice.kind === 'error' ? 'alert' : 'status'}>
            <span>{movementNotice.message}</span>
            <button type="button" className="icon-button icon-button--small" aria-label="Dismiss Claim movement notice" onClick={() => setMovementNotice(null)}>×</button>
          </div>
        )}
        {revisionNotice && revisionNotice.claimId === claimId && (
          <div className="revision-notice" role="status">
            <span>This Claim changed in another session (revision {revisionNotice.revision}).</span>
            <button type="button" onClick={() => { setRevisionNotice(null); loadDetail(claimId) }}>Review the latest version</button>
            <button type="button" className="icon-button icon-button--small" aria-label="Dismiss revision notice" onClick={() => setRevisionNotice(null)}>×</button>
          </div>
        )}
        {isConversations ? (
          <ConversationsPage conversations={conversations} loading={conversationsLoading} error={conversationsError} onRetry={loadConversations} onOpenConversation={openConversation} />
        ) : (
          <div className={`workbench-layout${queueVisible ? '' : ' queue-hidden'}`}>
            {queueVisible && (filterMetadata
              ? viewAvailable
                ? <QueuePanel claims={visibleClaims} loading={queueLoading} error={queueError} onRetry={() => loadClaims()} selectedId={claimId} filterMetadata={filterMetadata} viewCounts={viewCounts} view={view} onView={(value) => setQueueFilter('view', value)} workflowState={workflowState} onWorkflowState={(value) => setQueueFilter('workflow_state', value)} priority={priority} onPriority={(value) => setQueueFilter('priority', value)} tagFilter={tagFilter} onTag={(value) => setQueueFilter('tag', value)} search={search} onSearch={(value) => setQueueFilter('search', value)} additionalFiltersActive={Boolean(assigneeId || nextAction || updatedBefore || updatedAfter)} onClearFilters={clearQueueFilters} nextCursor={nextCursor} onLoadMore={() => loadClaims({ cursor: nextCursor, append: true })} onOpen={openClaim} />
                : <QueueViewUnavailable view={view} onOpenAll={() => setQueueFilter('view', 'all')} />
              : <QueueMetadataState loading={filterMetadataLoading} error={filterMetadataError} onRetry={() => setFilterMetadataAttempt((attempt) => attempt + 1)} />)}
            <section className="workspace-region">
              <ClaimTabs tabs={tabs.tabs} activeId={claimId || tabs.activeId} onActivate={activateTab} onClose={closeTab} />
              <div id="open-claim-panel" className="open-claim-panel" role="tabpanel" aria-labelledby={claimId ? `open-claim-tab-${claimId}` : undefined} tabIndex={0}>
                <ClaimWorkspace detail={detail} resources={resources} loading={detailLoading} stale={detailStale} error={detailError} section={currentSection} draft={currentTab?.draft || ''} profile={profile} onSection={changeSection} onDraft={(draft) => claimId && tabs.update(claimId, { draft })} onRetry={() => loadDetail(claimId)} onRetrySection={() => loadSectionResources(claimId, currentSection)} onAccept={acceptHandoff} onResolve={resolveHandoff} onSignalDecision={decideSignal} onCreateAction={createStaffAction} onUpdateAction={updateStaffAction} onLoadEvidence={loadEvidence} onSend={sendMessage} onOwnershipAction={performOwnershipAction} onReopen={reopenClaim} />
              </div>
            </section>
          </div>
        )}
      </div>
      <StaffAgent
        open={agentOpen}
        onOpenChange={setAgentOpen}
        requestedSessionId={agentSessionId}
        token={token}
        onSessionChange={(sessionId) => setAgentSessionId(sessionId)}
        onConversationChanged={() => {
          if (isConversations) loadConversations()
        }}
      />
    </div>
  )
}

function reopenFailureNotice(error, latest, queueLabel) {
  const identity = latest.display_reference || latest.claim_id
  const location = `${queueLabel || 'the current queue'} at revision ${latest.revision}`
  const reference = failureReference(error)
  let message
  if (error?.code === 'REVISION_CONFLICT') message = `Claim ${identity} was not reopened because the loaded revision was stale. The latest server projection is in ${location}; review it and try again.`
  else if (error?.code === 'ACCESS_DENIED') message = `Claim ${identity} was not reopened because this staff identity is not authorised for the action. The latest server projection is in ${location}; ask the primary owner to review it.`
  else if (error?.code === 'IDEMPOTENCY_CONFLICT') message = `Claim ${identity} was not reopened because this request no longer matches the original attempt. The latest server projection is in ${location}; review it before retrying.`
  else message = `The reopen outcome for Claim ${identity} was unclear. The latest server projection is in ${location}; review it before trying again.`
  return [message, reference].filter(Boolean).join(' ')
}

function QueueViewUnavailable({ view, onOpenAll }) {
  return (
    <aside className="queue-panel" aria-label="Claim queue">
      <header className="queue-panel__header">
        <div>
          <p className="eyebrow">My work</p>
          <h2>Claim queue</h2>
        </div>
      </header>
      <div className="queue-list">
        <div className="queue-state" role="alert">
          <strong>This queue view is no longer available</strong>
          <p>The view “{view}” is not published by the Workbench service. Choose a current server-published queue to continue.</p>
          <button className="button button--quiet" type="button" onClick={onOpenAll}>Open all active work</button>
        </div>
      </div>
    </aside>
  )
}

function QueueMetadataState({ loading, error, onRetry }) {
  return (
    <aside className="queue-panel" aria-label="Claim queue">
      <header className="queue-panel__header">
        <div>
          <p className="eyebrow">My work</p>
          <h2>Claim queue</h2>
        </div>
      </header>
      <div className="queue-list" aria-live="polite" aria-busy={loading}>
        {loading && <p className="queue-state" role="status">Loading queue filters...</p>}
        {!loading && error && (
          <div className="queue-state" role="alert">
            <strong>Claim queue unavailable</strong>
            <p>The Workbench could not load the server-published queue controls. The current URL has been preserved; retry when the service is available.</p>
            <p>{failureReason(error)}</p>
            {failureReference(error) && <small>{failureReference(error)}</small>}
            <button className="button button--quiet" type="button" onClick={onRetry}>Retry</button>
          </div>
        )}
      </div>
    </aside>
  )
}

const CLAIM_SECTIONS = new Set([
  'summary',
  'conversation',
  'fields',
  'evidence',
  'references',
  'external-services',
  'signals',
  'activity',
])

function resourceState(response = {}) {
  return {
    items: response.items || [],
    page: response.page || { next_cursor: null },
    status: response.status || 'available',
    limitation: response.limitation || null,
    loading: false,
    stale: false,
    error: null,
  }
}

function settledResourceState(result, previous = {}) {
  if (result.status === 'fulfilled') return resourceState(result.value)
  return {
    ...previous,
    items: previous.items || [],
    status: 'unavailable',
    limitation: previous.limitation || null,
    loading: false,
    stale: Boolean(previous.items?.length),
    error: result.reason,
  }
}

function isInaccessibleError(error) {
  return error?.status === 403
    || error?.status === 404
    || error?.code === 'ACCESS_DENIED'
    || error?.code === 'RESOURCE_NOT_FOUND'
}

function isOlderClaimProjection(candidate, current) {
  return candidate?.claim_id === current?.claim_id
    && candidate.revision < current.revision
}

function queueRequestFilters(filters, cursor = null) {
  return {
    ...(filters.view === 'all' ? {} : { view: filters.view }),
    ...(filters.workflowState ? { workflow_state: filters.workflowState } : {}),
    ...(filters.priority ? { priority: filters.priority } : {}),
    ...(filters.assigneeId ? { assignee_id: filters.assigneeId } : {}),
    ...(filters.nextAction ? { next_action: filters.nextAction } : {}),
    ...(filters.tagFilter ? { tag: filters.tagFilter } : {}),
    ...(filters.search ? { search: filters.search } : {}),
    ...(filters.updatedBefore ? { updated_before: filters.updatedBefore } : {}),
    ...(filters.updatedAfter ? { updated_after: filters.updatedAfter } : {}),
    limit: 25,
    ...(cursor ? { cursor } : {}),
  }
}

function queueFilterKey(filters) {
  return JSON.stringify(queueRequestFilters(filters))
}

function readQueueFilters(searchParams, metadata) {
  if (!metadata) return EMPTY_QUEUE_FILTERS
  const requestedView = (searchParams.get('view') || 'all').trim() || 'all'
  return {
    view: requestedView,
    viewAvailable: metadata.views.some((option) => option.value === requestedView),
    workflowState: validFilterValue(
      searchParams.get('workflow_state'),
      metadata.workflow_states,
    ),
    priority: validFilterValue(searchParams.get('priority'), metadata.priorities),
    assigneeId: (searchParams.get('assignee_id') || '').trim(),
    nextAction: (searchParams.get('next_action') || '').trim(),
    tagFilter: validFilterValue(searchParams.get('tag'), metadata.tags),
    search: (searchParams.get('search') || '').trim().slice(0, 200),
    updatedBefore: (searchParams.get('updated_before') || '').trim(),
    updatedAfter: (searchParams.get('updated_after') || '').trim(),
  }
}

function validFilterValue(value, options, fallback = '') {
  return options.some((option) => option.value === value) ? value : fallback
}

function normalizeQueueSearchParams(searchParams, metadata) {
  const next = new URLSearchParams(searchParams)
  const filters = readQueueFilters(next, metadata)
  if (filters.viewAvailable) {
    setNormalizedParam(next, 'view', filters.view === 'all' ? '' : filters.view)
  }
  setNormalizedParam(next, 'workflow_state', filters.workflowState)
  setNormalizedParam(next, 'priority', filters.priority)
  setNormalizedParam(next, 'tag', filters.tagFilter)
  setNormalizedParam(next, 'search', filters.search)
  next.delete('cursor')
  return next
}

function setNormalizedParam(params, name, value) {
  if (value) params.set(name, value)
  else params.delete(name)
}

function queueRoute(path, filters, sessionId = null) {
  const params = new URLSearchParams()
  if (filters.view !== 'all') params.set('view', filters.view)
  if (filters.workflowState) params.set('workflow_state', filters.workflowState)
  if (filters.priority) params.set('priority', filters.priority)
  if (filters.assigneeId) params.set('assignee_id', filters.assigneeId)
  if (filters.nextAction) params.set('next_action', filters.nextAction)
  if (filters.tagFilter) params.set('tag', filters.tagFilter)
  if (filters.search) params.set('search', filters.search)
  if (filters.updatedBefore) params.set('updated_before', filters.updatedBefore)
  if (filters.updatedAfter) params.set('updated_after', filters.updatedAfter)
  if (sessionId) params.set('session', sessionId)
  return params.size ? `${path}?${params}` : path
}

const EMPTY_QUEUE_FILTERS = Object.freeze({
  view: 'all',
  viewAvailable: false,
  workflowState: '',
  priority: '',
  assigneeId: '',
  nextAction: '',
  tagFilter: '',
  search: '',
  updatedBefore: '',
  updatedAfter: '',
})

const UNAVAILABLE_VIEW_COUNTS = Object.freeze({
  status: 'unavailable',
  items: [],
  limitation: 'Queue totals are temporarily unavailable.',
})

const QUEUE_FILTER_PARAM_NAMES = Object.freeze([
  'view',
  'workflow_state',
  'priority',
  'assignee_id',
  'next_action',
  'tag',
  'search',
  'updated_before',
  'updated_after',
])
