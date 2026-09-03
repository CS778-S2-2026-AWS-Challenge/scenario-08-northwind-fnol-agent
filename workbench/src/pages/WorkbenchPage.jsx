import { Menu, PanelLeftClose, PanelLeftOpen, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'
import { useLocation, useNavigate, useParams } from 'react-router-dom'
import { workbenchApi } from '../api.js'
import { useAuth } from '../auth/auth-context.js'
import ClaimTabs from '../components/ClaimTabs.jsx'
import ClaimWorkspace from '../components/ClaimWorkspace.jsx'
import NavigationRail from '../components/NavigationRail.jsx'
import QueuePanel from '../components/QueuePanel.jsx'
import StaffAgent from '../components/StaffAgent.jsx'
import { usePersistentTabs } from '../hooks/usePersistentTabs.js'
import { revisionNotice as buildRevisionNotice } from '../revision.js'
import ConversationsPage from './ConversationsPage.jsx'

export default function WorkbenchPage() {
  const { token, profile, logout } = useAuth()
  const { claimId, section: routeSection, agentSessionId: routeAgentSessionId, conversationSessionId } = useParams()
  const location = useLocation()
  const navigate = useNavigate()
  const tabs = usePersistentTabs()
  const openTab = tabs.open
  const [claims, setClaims] = useState([])
  const [view, setView] = useState('all')
  const [tagFilter, setTagFilter] = useState('')
  const [knownTags, setKnownTags] = useState([])
  const [nextCursor, setNextCursor] = useState(null)
  const [queueLoading, setQueueLoading] = useState(true)
  const [queueError, setQueueError] = useState('')
  const [conversations, setConversations] = useState([])
  const [conversationsLoading, setConversationsLoading] = useState(false)
  const [conversationsError, setConversationsError] = useState('')
  const [detail, setDetail] = useState(null)
  const [resources, setResources] = useState({})
  const [detailLoading, setDetailLoading] = useState(false)
  const [detailError, setDetailError] = useState('')
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

  const openConversation = useCallback((conversation) => {
    if (conversation.kind === 'staff_agent') {
      setAgentSessionId(conversation.session_id)
      setAgentOpen(true)
      navigate(`/workbench/agent/sessions/${encodeURIComponent(conversation.session_id)}`)
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
    navigate(
      `/workbench/claims/${conversation.claim_id}/conversation?session=${encodeURIComponent(conversation.session_id)}`,
    )
  }, [navigate, tabs])

  const loadClaims = useCallback(async ({ cursor = null, append = false } = {}) => {
    setQueueLoading(true)
    setQueueError('')
    try {
      const response = await workbenchApi.claims(token, {
        ...(view === 'all' ? {} : { view }),
        ...(tagFilter ? { tag: tagFilter } : {}),
        limit: 25,
        ...(cursor ? { cursor } : {}),
      })
      setClaims((current) => append ? [...current, ...response.items] : response.items)
      setNextCursor(response.page?.next_cursor || null)
      setKnownTags((current) => {
        const byCode = new Map(current.map((tag) => [tag.code, tag]))
        response.items.flatMap((claim) => claim.tags || []).forEach((tag) => byCode.set(tag.code, tag))
        return [...byCode.values()].sort((left, right) => left.label.localeCompare(right.label))
      })
    } catch (error) {
      setQueueError(error.message)
    } finally {
      setQueueLoading(false)
    }
  }, [tagFilter, token, view])

  const loadDetail = useCallback(async (id) => {
    if (!id) {
      setDetail(null)
      return
    }
    setDetailLoading(true)
    setDetailError('')
    try {
      const [response, handoffs, collaborationRequests] = await Promise.all([
        workbenchApi.claim(token, id),
        workbenchApi.handoffs(token, id),
        workbenchApi.collaborationRequests(token, id),
      ])
      setDetail(response)
      setResources({
        handoffs: resourceState(handoffs),
        collaborationRequests: resourceState(collaborationRequests),
      })
      openTab(response)
    } catch (error) {
      setDetail(null)
      setDetailError(error.message)
    } finally {
      setDetailLoading(false)
    }
  }, [openTab, token])

  const refreshDetail = useCallback(async (id) => {
    if (!id) return
    try {
      const response = await workbenchApi.claim(token, id)
      setDetail((current) => {
        const notice = buildRevisionNotice(current, response)
        if (notice) setRevisionNotice(notice)
        return response
      })
      openTab(response)
    } catch {
      // The foreground view owns actionable errors; background refresh must not erase drafts.
    }
  }, [openTab, token])

  const loadResource = useCallback(async (name, loader) => {
    setResources((current) => ({
      ...current,
      [name]: { ...(current[name] || {}), loading: true, error: '' },
    }))
    try {
      const response = await loader()
      setResources((current) => ({ ...current, [name]: resourceState(response) }))
      return response
    } catch (error) {
      setResources((current) => ({
        ...current,
        [name]: { items: [], status: 'unavailable', limitation: null, loading: false, error: error.message },
      }))
      return null
    }
  }, [])

  const loadConversationResources = useCallback(async (id, requestedSessionId) => {
    const sessions = await loadResource('sessions', () => workbenchApi.sessions(token, id))
    const session = sessions?.items?.find((item) => item.session_id === requestedSessionId)
      || sessions?.items?.at(-1)
    if (session) {
      await loadResource('messages', () => workbenchApi.messages(token, id, session.session_id))
    } else {
      setResources((current) => ({ ...current, messages: resourceState({ items: [] }) }))
    }
  }, [loadResource, token])

  const loadSectionResources = useCallback(async (id, section) => {
    const loaders = {
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
    await Promise.all((loaders[section] || []).map(([name, loader]) => loadResource(name, loader)))
  }, [loadConversationResources, loadResource, selectedSessionId, token])

  const loadConversations = useCallback(async () => {
    setConversationsLoading(true)
    setConversationsError('')
    try {
      const response = await workbenchApi.conversations(token)
      setConversations(response.items || [])
    } catch (error) {
      setConversationsError(error.message)
    } finally {
      setConversationsLoading(false)
    }
  }, [token])

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
      setDetail(null)
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
    if (claimId && routeSection && !CLAIM_SECTIONS.has(routeSection)) {
      navigate(`/workbench/claims/${claimId}`, { replace: true })
    }
  }, [claimId, navigate, routeSection])

  function openClaim(claim) {
    tabs.open(claim)
    navigate(`/workbench/claims/${claim.claim_id}`)
  }

  function activateTab(id) {
    tabs.activate(id)
    const tab = tabs.tabs.find((item) => item.claimId === id)
    const suffix = tab?.section && tab.section !== 'summary' ? `/${tab.section}` : ''
    const query = tab?.section === 'conversation' && tab.sessionId
      ? `?session=${encodeURIComponent(tab.sessionId)}`
      : ''
    navigate(`/workbench/claims/${id}${suffix}${query}`)
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
      navigate(neighbour ? `/workbench/claims/${neighbour.claimId}${suffix}` : '/workbench')
    }
  }

  function changeSection(section) {
    if (!claimId) return
    tabs.update(claimId, { section, ...(section === 'conversation' ? {} : { sessionId: null }) })
    const suffix = section === 'summary' ? '' : `/${section}`
    const query = section === 'conversation' && currentTab?.sessionId
      ? `?session=${encodeURIComponent(currentTab.sessionId)}`
      : ''
    navigate(`/workbench/claims/${claimId}${suffix}${query}`, { replace: true })
  }

  async function acceptHandoff(handoff) {
    await workbenchApi.acceptHandoff(token, detail.claim_id, handoff.handoff_id, detail.revision)
    await Promise.all([loadDetail(detail.claim_id), loadClaims()])
  }

  async function resolveHandoff(handoff, payload) {
    await workbenchApi.resolveHandoff(
      token,
      detail.claim_id,
      handoff.handoff_id,
      detail.revision,
      payload,
    )
    await Promise.all([loadDetail(detail.claim_id), loadClaims()])
  }

  async function decideSignal(signalId, payload) {
    await workbenchApi.decideSignal(token, detail.claim_id, signalId, detail.revision, payload)
    await Promise.all([loadDetail(detail.claim_id), loadClaims()])
  }

  async function createStaffAction(payload) {
    await workbenchApi.createStaffAction(token, detail.claim_id, detail.revision, payload)
    await Promise.all([loadDetail(detail.claim_id), loadClaims()])
  }

  async function updateStaffAction(actionId, payload) {
    await workbenchApi.updateStaffAction(
      token,
      detail.claim_id,
      actionId,
      detail.revision,
      payload,
    )
    await Promise.all([loadDetail(detail.claim_id), loadClaims()])
  }

  function loadEvidence(evidenceId) {
    return workbenchApi.evidenceContent(token, detail.claim_id, evidenceId)
  }

  async function sendMessage(message) {
    await workbenchApi.sendMessage(token, detail.claim_id, message, detail.revision)
    await Promise.all([loadDetail(detail.claim_id), loadClaims()])
  }

  async function requestCowork(payload) {
    await workbenchApi.requestCowork(token, detail.claim_id, detail.revision, payload)
    await Promise.all([loadDetail(detail.claim_id), loadClaims()])
  }

  async function requestTransfer(payload) {
    await workbenchApi.requestTransfer(token, detail.claim_id, detail.revision, payload)
    await Promise.all([loadDetail(detail.claim_id), loadClaims()])
  }

  async function requeueClaim(reason) {
    await workbenchApi.requeue(token, detail.claim_id, detail.revision, reason)
    await Promise.all([loadDetail(detail.claim_id), loadClaims()])
  }

  async function decideCollaboration(requestId, decision) {
    await workbenchApi.decideCollaboration(
      token,
      detail.claim_id,
      requestId,
      detail.revision,
      decision,
    )
    await Promise.all([loadDetail(detail.claim_id), loadClaims()])
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
            <button className="icon-button" type="button" onClick={loadClaims} aria-label="Refresh Workbench projection"><RefreshCw size={17} /></button>
          </div>
        </header>
        {queueError && <div className="global-error" role="alert">{queueError}</div>}
        {revisionNotice && revisionNotice.claimId === claimId && (
          <div className="revision-notice" role="status">
            <span>This Claim changed in another session (revision {revisionNotice.revision}).</span>
            <button type="button" onClick={() => { setRevisionNotice(null); loadDetail(claimId) }}>Review the latest version</button>
            <button type="button" className="icon-button icon-button--small" aria-label="Dismiss revision notice" onClick={() => setRevisionNotice(null)}>×</button>
          </div>
        )}
        {isConversations ? (
          <ConversationsPage conversations={conversations} loading={conversationsLoading} error={conversationsError} onOpenConversation={openConversation} />
        ) : (
          <div className={`workbench-layout${queueVisible ? '' : ' queue-hidden'}`}>
            {queueVisible && <QueuePanel claims={claims} loading={queueLoading} selectedId={claimId} view={view} onView={setView} tagFilter={tagFilter} tags={knownTags} onTag={setTagFilter} nextCursor={nextCursor} onLoadMore={() => loadClaims({ cursor: nextCursor, append: true })} onOpen={openClaim} />}
            <section className="workspace-region">
              <ClaimTabs tabs={tabs.tabs} activeId={claimId || tabs.activeId} onActivate={activateTab} onClose={closeTab} />
              <div id="open-claim-panel" className="open-claim-panel" role="tabpanel" aria-labelledby={claimId ? `open-claim-tab-${claimId}` : undefined} tabIndex={0}>
                <ClaimWorkspace detail={detail} resources={resources} loading={detailLoading} error={detailError} section={currentSection} draft={currentTab?.draft || ''} profile={profile} onSection={changeSection} onDraft={(draft) => claimId && tabs.update(claimId, { draft })} onAccept={acceptHandoff} onResolve={resolveHandoff} onSignalDecision={decideSignal} onCreateAction={createStaffAction} onUpdateAction={updateStaffAction} onLoadEvidence={loadEvidence} onSend={sendMessage} onCoworkRequest={requestCowork} onTransferRequest={requestTransfer} onRequeue={requeueClaim} onCollaborationDecision={decideCollaboration} />
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
    error: '',
  }
}
