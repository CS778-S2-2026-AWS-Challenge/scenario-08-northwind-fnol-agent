import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  Bot,
  ChevronDown,
  CircleUserRound,
  Clock3,
  ExternalLink,
  FilePenLine,
  LockKeyhole,
  MoreHorizontal,
  Search,
  X,
} from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { claimIdentity } from '../claim-identity.js'
import { failureReason, failureReference } from '../failure.js'
import { formatCompactDateTime, formatDateTime, words } from '../format.js'
import { translate as t } from '../i18n.js'
import Conversation from '../components/Conversation.jsx'

const AGENT_CONVERSATIONS_PER_PAGE = 5
const MAX_VISIBLE_TABS = 5
const CATEGORIES = [
  ['attention', 'Action needed'],
  ['assigned', 'My conversations'],
  ['agent', 'Staff Agent'],
]
const GENERIC_AGENT_TITLES = new Set([
  'new staff agent session',
  'new staff agent conversation',
  'new conversation',
])

export default function ConversationsPage({
  conversations,
  loading,
  error,
  onRetry,
  onOpenConversation,
  queueVisible = true,
  selectedConversationSessionId = null,
  selectedStaffAgentSessionId = null,
  staffAgentDetail = null,
  assistanceRequests = [],
  assistanceLoading = false,
  assistanceError = null,
  onRetryAssistance = onRetry,
  onReviewRequest = onOpenConversation,
  onTakeOver,
  openConversationTabs = [],
  onActivateConversation,
  onCloseConversation,
  onBackToList,
  detail,
  detailLoading = false,
  detailError = null,
  detailStale = false,
  resources = {},
  profile,
  draft = '',
  scrollPosition = null,
  onDraft,
  onScrollPosition,
  onOpenClaim,
  onRetryDetail,
  onRetryConversation,
  onAccept,
  onResolve,
  onSend,
}) {
  const [category, setCategory] = useState(selectedStaffAgentSessionId ? 'agent' : 'attention')
  const [agentSearch, setAgentSearch] = useState('')
  const [agentPage, setAgentPage] = useState(1)
  const conversationTabByClaim = new Map(openConversationTabs.map((tab) => [tab.claimId, tab]))
  const claimConversations = conversations
    .filter((item) => item.kind === 'claim')
    .map((item) => ({ ...item, draft: conversationTabByClaim.get(item.claim_id)?.draft || '' }))
  const assignedConversations = claimConversations.filter((item) => isAssignedToViewer(item, profile))
  const agentConversations = conversations.filter((item) => item.kind === 'staff_agent')
  const assistanceQueue = assistanceRequests.map((request) => ({
    ...assistanceConversation(request),
    draft: conversationTabByClaim.get(request.claim_id)?.draft || '',
  }))
  const attentionConversations = mergeConversationQueues(
    assistanceQueue,
    claimConversations.filter(needsAttention),
  )
  const selectedConversation = findSelectedConversation(
    selectedConversationSessionId,
    claimConversations,
    assistanceQueue,
    openConversationTabs,
  )
  const counts = {
    attention: attentionConversations.length,
    assigned: assignedConversations.length,
    agent: agentConversations.length,
  }

  const normalizedAgentSearch = agentSearch.trim().toLocaleLowerCase()
  const filteredAgentConversations = normalizedAgentSearch
    ? agentConversations.filter((conversation) => (
      agentSessionSearchText(conversation).includes(normalizedAgentSearch)
    ))
    : agentConversations
  const agentPageCount = Math.max(
    1,
    Math.ceil(filteredAgentConversations.length / AGENT_CONVERSATIONS_PER_PAGE),
  )
  const currentAgentPage = Math.min(agentPage, agentPageCount)
  const agentPageStart = (currentAgentPage - 1) * AGENT_CONVERSATIONS_PER_PAGE
  const visibleAgentConversations = filteredAgentConversations.slice(
    agentPageStart,
    agentPageStart + AGENT_CONVERSATIONS_PER_PAGE,
  )
  const categoryConversations = category === 'attention'
    ? attentionConversations
    : category === 'assigned'
      ? assignedConversations
      : visibleAgentConversations
  const categoryLoading = category === 'attention'
    ? loading || assistanceLoading
    : loading
  const contextError = claimConversations.some((item) => item.contextUnavailable)
    ? new Error(t('Some conversation details could not be loaded. Refresh before relying on ownership or status.'))
    : null
  const categoryErrors = category === 'attention'
    ? [assistanceError, error, contextError].filter(Boolean)
    : [error, contextError].filter(Boolean)

  function updateAgentSearch(value) {
    setAgentSearch(value)
    setAgentPage(1)
  }

  function selectCategory(nextCategory) {
    setCategory(nextCategory)
    if (nextCategory !== 'agent') setAgentPage(1)
  }

  function openQueueConversation(conversation) {
    if (conversation.assistanceRequest) onReviewRequest(conversation.assistanceRequest)
    else onOpenConversation(conversation)
  }

  return (
    <main className={`conversations-page${selectedConversationSessionId || selectedStaffAgentSessionId ? ' is-detail-open' : ''}${queueVisible ? '' : ' is-queue-collapsed'}`}>
      <nav className="conversation-category-tabs" aria-label={t('Conversation categories')} role="tablist">
        {CATEGORIES.map(([value, label], index) => (
          <button
            className={category === value ? 'is-active' : ''}
            id={`conversation-category-${value}`}
            aria-controls="conversation-queue-panel"
            aria-label={t('{label}, {count} conversations', { label: t(label), count: counts[value] })}
            aria-selected={category === value}
            role="tab"
            tabIndex={category === value ? 0 : -1}
            type="button"
            key={value}
            onClick={() => selectCategory(value)}
            onKeyDown={(event) => moveCategoryFocus(event, index, selectCategory)}
          >
            <span>{t(label)}</span>
            <span className="conversation-category-tabs__count" aria-hidden="true">{counts[value]}</span>
          </button>
        ))}
      </nav>

      <div className="conversation-workspace">
        <aside
          className="conversation-queue"
          id="conversation-queue-panel"
          aria-labelledby={`conversation-category-${category}`}
          role="tabpanel"
          tabIndex={0}
        >
          <header className="conversation-queue__header">
            <div>
              <strong>{t(CATEGORIES.find(([value]) => value === category)?.[1] || 'Conversations')}</strong>
              <small>{queueDescription(category)}</small>
            </div>
            <span>{counts[category]}</span>
          </header>

          {category === 'agent' && agentConversations.length > 0 && (
            <label className="conversation-queue__search">
              <span className="sr-only">{t('Search conversations')}</span>
              <Search aria-hidden="true" />
              <input
                type="search"
                value={agentSearch}
                placeholder={t('Search conversations')}
                onChange={(event) => updateAgentSearch(event.target.value)}
              />
            </label>
          )}

          {!(category === 'agent' && normalizedAgentSearch && !filteredAgentConversations.length) && (
            <QueueState
              category={category}
              conversations={categoryConversations}
              loading={categoryLoading}
              errors={categoryErrors}
              selectedSessionId={category === 'agent' ? selectedStaffAgentSessionId : selectedConversationSessionId}
              onOpen={openQueueConversation}
              onRetry={category === 'attention' ? onRetryAssistance : onRetry}
              onTakeOver={onTakeOver}
            />
          )}

          {category === 'agent' && !loading && !error && normalizedAgentSearch && !filteredAgentConversations.length && (
            <div className="conversation-queue__empty" role="status">
              <Search aria-hidden="true" />
              <strong>{t('No conversations match “{query}”.', { query: agentSearch.trim() })}</strong>
              <button className="button button--quiet" type="button" onClick={() => updateAgentSearch('')}>{t('Clear search')}</button>
            </div>
          )}

          {category === 'agent' && filteredAgentConversations.length > AGENT_CONVERSATIONS_PER_PAGE && (
            <nav className="conversation-queue__pagination" aria-label={t('Staff Agent conversation pages')}>
              <button className="icon-button" type="button" disabled={currentAgentPage === 1} aria-label={t('Previous')} onClick={() => setAgentPage(currentAgentPage - 1)}><ArrowLeft aria-hidden="true" /></button>
              <span aria-live="polite">{t('Page {page} of {total}', { page: currentAgentPage, total: agentPageCount })}</span>
              <button className="icon-button" type="button" disabled={currentAgentPage === agentPageCount} aria-label={t('Next')} onClick={() => setAgentPage(currentAgentPage + 1)}><ArrowRight aria-hidden="true" /></button>
            </nav>
          )}
        </aside>

        <section className="conversation-detail" aria-label={t('Current conversation')}>
          {!selectedStaffAgentSessionId && (
            <OpenConversationTabs
              tabs={openConversationTabs}
              activeSessionId={selectedConversationSessionId}
              onActivate={onActivateConversation}
              onClose={onCloseConversation}
            />
          )}
          {selectedStaffAgentSessionId ? staffAgentDetail : selectedConversationSessionId ? (
            <ConversationDetail
              conversation={selectedConversation}
              detail={detail}
              loading={detailLoading}
              error={detailError}
              stale={detailStale}
              resources={resources}
              profile={profile}
              draft={draft}
              scrollPosition={scrollPosition}
              onDraft={onDraft}
              onScrollPosition={onScrollPosition}
              onBack={onBackToList}
              onOpenClaim={onOpenClaim}
              onClose={() => onCloseConversation?.(detail?.claim_id || selectedConversation?.claim_id)}
              onRetryDetail={onRetryDetail}
              onRetryConversation={onRetryConversation}
              onAccept={onAccept}
              onResolve={onResolve}
              onSend={onSend}
              requestedSessionId={selectedConversationSessionId}
            />
          ) : (
            <EmptyConversationDetail />
          )}
        </section>
      </div>
    </main>
  )
}

function QueueState({ category, conversations, loading, errors, selectedSessionId, onOpen, onRetry, onTakeOver }) {
  if (loading && !conversations.length) {
    return (
      <div className="conversation-queue__state" role="status">
        <span className="loading-mark" />
        <strong>{t('Loading conversations...')}</strong>
      </div>
    )
  }
  if (errors.length && !conversations.length) {
    return <ConversationFailure errors={errors} onRetry={onRetry} />
  }
  if (!conversations.length) {
    return category === 'agent'
      ? <div className="conversation-queue__empty" role="status"><Bot aria-hidden="true" /><strong>{t('No Staff Agent conversations yet.')}</strong><p>{t('Past internal assistance sessions will appear here.')}</p></div>
      : category === 'attention'
        ? <div className="conversation-queue__empty" role="status"><Clock3 aria-hidden="true" /><strong>{t('Nothing needs attention')}</strong><p>{t('New customer requests and unread replies will appear here.')}</p></div>
        : <div className="conversation-queue__empty" role="status"><CircleUserRound aria-hidden="true" /><strong>{t('No assigned conversations')}</strong><p>{t('Conversations assigned to you will appear here.')}</p></div>
  }
  return (
    <>
      {errors.length > 0 && <ConversationFailure compact errors={errors} onRetry={onRetry} />}
      <ol className="conversation-queue__list" aria-label={t('Conversation queue')}>
        {conversations.map((conversation) => (
          <li key={conversation.conversation_id}>
            <ConversationQueueRow
              conversation={conversation}
              selected={conversation.session_id === selectedSessionId}
              onOpen={onOpen}
              onTakeOver={onTakeOver}
            />
          </li>
        ))}
      </ol>
    </>
  )
}

function ConversationQueueRow({ conversation, selected, onOpen, onTakeOver }) {
  const state = conversationState(conversation)
  const identity = conversationIdentity(conversation)
  const unread = conversationUnreadCount(conversation)
  const priority = conversation.detail?.priority_projection
  const dueAt = priority?.due_at || conversation.detail?.work_summary?.due_at
  const owner = conversationOwner(conversation.detail)
  const isAgent = conversation.kind === 'staff_agent'
  return (
    <article className={`conversation-queue-row${selected ? ' is-selected' : ''}${unread ? ' has-unread' : ''}`}>
      <button
        className="conversation-queue-row__open"
        type="button"
        aria-current={selected ? 'true' : undefined}
        onClick={() => onOpen(conversation)}
      >
        <span className="conversation-avatar" aria-hidden="true">
          {isAgent ? <Bot /> : identity.initials || <CircleUserRound />}
        </span>
        <span className="conversation-queue-row__copy">
          <span className="conversation-queue-row__headline">
            <strong>{isAgent ? agentSessionTitle(conversation) : identity.name}</strong>
            <time dateTime={conversation.updated_at}>{updatedLabel(conversation.updated_at)}</time>
          </span>
          {!isAgent && <small className="conversation-queue-row__reference">{t('Claim')} {identity.reference}</small>}
          <span className="conversation-queue-row__summary">{conversation.summary?.trim() || t('No messages yet.')}</span>
          <span className="conversation-queue-row__signals">
            <span className={`record-status${state.tone ? ` record-status--${state.tone}` : ''}`}>{t(state.label)}</span>
            {unread > 0 && <span className="conversation-unread" aria-label={t('{count} unread messages', { count: unread })}>{unread}</span>}
            {conversation.draft && <span className="conversation-draft"><FilePenLine aria-hidden="true" />{t('Draft')}</span>}
            {!isAgent && priority?.level && <span>{words(priority.level)}</span>}
            {!isAgent && dueAt && <span>{t('Due')} {formatDateTime(dueAt)}</span>}
          </span>
          {!isAgent && owner && <span className="conversation-queue-row__owner"><LockKeyhole aria-hidden="true" />{owner}</span>}
        </span>
      </button>
      {conversation.assistanceRequest?.canTakeOver && onTakeOver && (
        <QueueTakeOver request={conversation.assistanceRequest} onTakeOver={onTakeOver} />
      )}
    </article>
  )
}

function QueueTakeOver({ request, onTakeOver }) {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  async function takeOver() {
    setBusy(true)
    setError('')
    try {
      await onTakeOver(request)
    } catch (nextError) {
      setError(nextError.message)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="conversation-queue-row__takeover">
      {confirming ? (
        <>
          <span>{t('Assign to you?')}</span>
          <button className="button button--ghost" type="button" disabled={busy} onClick={() => setConfirming(false)}>{t('Cancel')}</button>
          <button className="button button--secondary" type="button" disabled={busy} onClick={takeOver}>{t(busy ? 'Taking over...' : 'Confirm take over')}</button>
        </>
      ) : (
        <button className="button button--quiet" type="button" onClick={() => setConfirming(true)}>{t('Take over')}</button>
      )}
      {error && <span className="form-error" role="alert">{error}</span>}
    </div>
  )
}

function OpenConversationTabs({ tabs, activeSessionId, onActivate, onClose }) {
  const [menuOpen, setMenuOpen] = useState(false)
  const moreButtonRef = useRef(null)
  const menuRef = useRef(null)
  const { visible, overflow } = visibleConversationTabs(tabs, activeSessionId)

  useEffect(() => {
    if (!menuOpen) return
    menuRef.current?.querySelector('[role="menuitem"]')?.focus()
  }, [menuOpen])

  if (!tabs.length) return <div className="open-conversation-tabs open-conversation-tabs--empty"><span>{t('Open conversations')}</span></div>

  function activate(tab) {
    setMenuOpen(false)
    onActivate?.(tab.claimId)
  }

  function onMenuKeyDown(event) {
    const items = [...event.currentTarget.querySelectorAll('[role="menuitem"]')]
    const index = items.indexOf(document.activeElement)
    if (event.key === 'Escape') {
      event.preventDefault()
      setMenuOpen(false)
      moreButtonRef.current?.focus()
      return
    }
    if (event.key === 'Tab') {
      setMenuOpen(false)
      return
    }
    if (!['ArrowDown', 'ArrowUp', 'Home', 'End'].includes(event.key)) return
    event.preventDefault()
    const nextIndex = event.key === 'Home'
      ? 0
      : event.key === 'End'
        ? items.length - 1
        : event.key === 'ArrowDown'
          ? (index + 1) % items.length
          : (index - 1 + items.length) % items.length
    items[nextIndex]?.focus()
  }

  return (
    <div className="open-conversation-tabs">
      <span className="sr-only" id="open-conversations-label">{t('Open conversations')}</span>
      <div className="open-conversation-tabs__list" role="tablist" aria-labelledby="open-conversations-label">
        {visible.map((tab, index) => (
          <span className={`open-conversation-tab${tab.sessionId === activeSessionId ? ' is-active' : ''}`} key={tab.claimId}>
            <button
              id={`open-conversation-tab-${tab.claimId}`}
              type="button"
              role="tab"
              aria-controls="current-conversation-panel"
              aria-selected={tab.sessionId === activeSessionId}
              tabIndex={tab.sessionId === activeSessionId || (!activeSessionId && index === 0) ? 0 : -1}
              onClick={() => activate(tab)}
              onKeyDown={(event) => moveOpenTabFocus(event, index, visible, activate, onClose)}
            >
              <span>{tab.label}</span>
              {tab.unreadCount > 0 && <span className="conversation-unread" aria-label={t('{count} unread messages', { count: tab.unreadCount })}>{tab.unreadCount}</span>}
              {tab.draft && <FilePenLine aria-label={t('Unsent draft')} />}
            </button>
            <button className="open-conversation-tab__close" type="button" aria-label={t('Close {name} tab', { name: tab.label })} onClick={() => onClose?.(tab.claimId)}><X aria-hidden="true" /></button>
          </span>
        ))}
      </div>
      {overflow.length > 0 && (
        <div className="open-conversation-tabs__more">
          <button
            ref={moreButtonRef}
            className="open-conversation-tabs__more-button"
            type="button"
            aria-haspopup="menu"
            aria-expanded={menuOpen}
            onClick={() => setMenuOpen((value) => !value)}
            onKeyDown={(event) => {
              if (!['Enter', ' ', 'ArrowDown'].includes(event.key)) return
              event.preventDefault()
              setMenuOpen(true)
            }}
          >
            <MoreHorizontal aria-hidden="true" />{t('More')}<ChevronDown aria-hidden="true" />
          </button>
          {menuOpen && (
            <div ref={menuRef} className="open-conversation-tabs__menu" role="menu" aria-label={t('More open conversations')} onKeyDown={onMenuKeyDown}>
              {overflow.map((tab) => (
                <button type="button" role="menuitem" key={tab.claimId} onClick={() => activate(tab)}>
                  <span>{tab.label}</span>
                  {tab.unreadCount > 0 && <span className="conversation-unread">{tab.unreadCount}</span>}
                  {tab.draft && <FilePenLine aria-label={t('Unsent draft')} />}
                </button>
              ))}
            </div>
          )}
        </div>
      )}
    </div>
  )
}

function ConversationDetail({ conversation, detail, loading, error, stale, resources, profile, draft, scrollPosition, onDraft, onScrollPosition, onBack, onOpenClaim, onClose, onRetryDetail, onRetryConversation, onAccept, onResolve, onSend, requestedSessionId }) {
  if (loading && !detail) {
    return <div className="conversation-detail__state" role="status"><span className="loading-mark" /><strong>{t('Loading conversation...')}</strong></div>
  }
  if (error && !detail) {
    return <div className="conversation-detail__state conversation-detail__state--error" role="alert"><AlertTriangle aria-hidden="true" /><strong>{t('This conversation could not be opened')}</strong><p>{failureReason(error)}</p>{failureReference(error) && <small>{failureReference(error)}</small>}<button className="button button--quiet" type="button" onClick={onRetryDetail}>{t('Retry')}</button></div>
  }
  if (!detail) {
    return <div className="conversation-detail__state" role="status"><AlertTriangle aria-hidden="true" /><strong>{t('Conversation unavailable')}</strong><p>{t('The selected conversation is no longer available in the current projection.')}</p><button className="button button--quiet" type="button" onClick={onBack}>{t('Back to conversations')}</button></div>
  }
  const identity = claimIdentity(detail)
  const state = conversationState(conversation || { detail })
  const owner = conversationOwner(detail) || t('Unassigned')
  const unread = conversationUnreadCount(conversation || { detail })
  const assignedElsewhere = Boolean(
    detail.ownership?.primary_assignee
      && detail.ownership.current_staff_access !== 'primary',
  )
  const resolved = ['resolved', 'closed'].includes(state.key)
  const evidenceRecords = resources.evidence?.items || []

  return (
    <div className="conversation-detail__body" id="current-conversation-panel" role="tabpanel" aria-labelledby={detail.claim_id ? `open-conversation-tab-${detail.claim_id}` : undefined}>
      <header className="conversation-detail__header">
        <button className="conversation-detail__back" type="button" onClick={onBack}><ArrowLeft aria-hidden="true" />{t('Conversations')}</button>
        <div className="conversation-detail__identity">
          <span className="conversation-avatar" aria-hidden="true">{initials(identity.claimantName) || <CircleUserRound />}</span>
          <div>
            <h2>{identity.claimantName || t('Customer')}</h2>
            <p>{t('Claim')} {identity.referenceLabel} · {identity.typeLabel}</p>
          </div>
        </div>
        <dl className="conversation-detail__meta">
          <div><dt>{t('Status')}</dt><dd><span className={`record-status${state.tone ? ` record-status--${state.tone}` : ''}`}>{t(state.label)}</span></dd></div>
          <div><dt>{t('Owner')}</dt><dd>{owner}</dd></div>
          <div><dt>{t('Last activity')}</dt><dd>{detail.updated_at ? <time dateTime={detail.updated_at}>{formatDateTime(detail.updated_at)}</time> : t('Not recorded')}</dd></div>
        </dl>
        <div className="conversation-detail__actions">
          <button className="button button--quiet" type="button" onClick={onOpenClaim}><ExternalLink aria-hidden="true" />{t('Open claim')}</button>
          <button className="icon-button" type="button" aria-label={t('Close current conversation tab')} onClick={onClose}><X aria-hidden="true" /></button>
        </div>
      </header>
      {(loading || stale || error) && detail && (
        <div className={`conversation-detail__notice${error ? ' is-error' : ''}`} role={error ? 'alert' : 'status'}>
          <span>{t(loading ? 'Refreshing this conversation…' : error ? 'Showing a saved conversation snapshot.' : 'This conversation may have changed.')}</span>
          {!loading && <button className="button button--quiet" type="button" onClick={onRetryDetail}>{t('Refresh')}</button>}
        </div>
      )}
      {unread > 0 && <div className="conversation-detail__notice" role="status" aria-live="polite">{t('{count} new customer messages', { count: unread })}</div>}
      {assignedElsewhere && (
        <div className="conversation-detail__notice conversation-detail__notice--ownership" role="status">
          <LockKeyhole aria-hidden="true" />
          <span><strong>{t('Owned by another staff member')}</strong>{t(' Replies remain disabled unless the authoritative assignment changes.')}</span>
        </div>
      )}
      {resolved && <div className="conversation-detail__notice" role="status">{t('This conversation is {status}. It remains available as read-only history.', { status: state.label.toLocaleLowerCase() })}</div>}
      <Conversation
        detail={detail}
        handoffs={resources.handoffs?.items || []}
        profile={profile}
        resource={resources.messages}
        evidenceRecords={evidenceRecords}
        requestedSessionId={requestedSessionId}
        draft={draft}
        scrollPosition={scrollPosition}
        onDraft={onDraft}
        onScrollPosition={onScrollPosition}
        onAccept={onAccept}
        onResolve={onResolve}
        onSend={onSend}
        onRetry={onRetryConversation}
      />
    </div>
  )
}

function EmptyConversationDetail() {
  return (
    <div className="conversation-detail__empty">
      <div className="conversation-detail__empty-symbol"><CircleUserRound aria-hidden="true" /></div>
      <p className="eyebrow">{t('Conversation workspace')}</p>
      <h2>{t('Select a conversation')}</h2>
      <p>{t('Choose a customer conversation from the queue. Only one full timeline is shown at a time.')}</p>
    </div>
  )
}

function ConversationFailure({ errors, onRetry, compact = false }) {
  return (
    <div className={`conversation-queue__failure${compact ? ' is-compact' : ''}`} role="alert">
      <AlertTriangle aria-hidden="true" />
      <div>
        <strong>{t('Conversations are unavailable.')}</strong>
        {errors.map((item, index) => <p key={`${failureReason(item)}:${index}`}>{failureReason(item)}</p>)}
        {errors.map(failureReference).filter(Boolean).map((reference) => <small key={reference}>{reference}</small>)}
      </div>
      <button className="button button--quiet" type="button" onClick={onRetry}>{t('Retry')}</button>
    </div>
  )
}

function assistanceConversation(request) {
  const sessionId = request.detail?.active_session_id || request.handoff?.session_id || request.claim_id
  return {
    conversation_id: `assistance:${request.claim_id}`,
    kind: 'claim',
    claim_id: request.claim_id,
    display_reference: request.display_reference,
    session_id: sessionId,
    status: request.handoff?.status || 'queued',
    title: request.detail?.claimant?.display_name || request.display_reference || request.claim_id,
    summary: request.handoff?.packet?.incident_summary || request.incident?.summary,
    updated_at: request.handoff?.created_at || request.updated_at,
    detail: request.detail,
    assistance: request.handoff,
    assistanceRequest: request,
  }
}

function mergeConversationQueues(primary, secondary) {
  const seen = new Set()
  return [...primary, ...secondary].filter((conversation) => {
    const key = conversation.claim_id || conversation.conversation_id
    if (seen.has(key)) return false
    seen.add(key)
    return true
  })
}

function findSelectedConversation(sessionId, claimConversations, assistanceQueue, tabs) {
  if (!sessionId) return null
  return [...assistanceQueue, ...claimConversations].find((item) => item.session_id === sessionId)
    || tabs.find((item) => item.sessionId === sessionId)
    || null
}

function needsAttention(conversation) {
  if (conversation.kind !== 'claim') return false
  const state = conversationState(conversation)
  return ['needs-attention', 'waiting-request'].includes(state.key)
}

function isAssignedToViewer(conversation, profile) {
  if (conversation.detail?.ownership?.current_staff_access === 'primary') return true
  return Boolean(
    profile?.staff_id
      && conversation.assistance?.assigned_to === profile.staff_id,
  )
}

function conversationState(conversation) {
  if (conversation.assistance?.status === 'resolved') return { key: 'resolved', label: 'Resolved', tone: 'confirmed' }
  if (['closed', 'completed', 'ended'].includes(conversation.status)) return { key: 'closed', label: 'Closed', tone: 'confirmed' }
  if (conversation.assistance?.status === 'queued') return { key: 'waiting-request', label: 'Needs attention', tone: 'attention' }
  if (conversationUnreadCount(conversation) > 0 || conversation.detail?.priority_projection?.is_overdue) return { key: 'needs-attention', label: 'Needs attention', tone: 'attention' }
  if (conversation.assistance?.waitingForCustomer || conversation.detail?.customer_next_step?.responsible_party === 'claimant') return { key: 'waiting-customer', label: 'Waiting for customer', tone: '' }
  if (conversation.kind === 'staff_agent') return { key: 'agent', label: 'Staff Agent', tone: '' }
  return { key: 'assigned', label: 'Assigned', tone: 'confirmed' }
}

function conversationIdentity(conversation) {
  const identity = claimIdentity({
    ...conversation.detail,
    claim_id: conversation.claim_id,
    display_reference: conversation.display_reference,
  })
  const name = identity.claimantName || t('Customer')
  return {
    name,
    initials: initials(identity.claimantName),
    reference: identity.referenceLabel,
  }
}

function conversationUnreadCount(conversation) {
  return conversation?.unread_count
    ?? conversation?.detail?.work_summary?.unread_claimant_messages
    ?? 0
}

function conversationOwner(detail) {
  const owner = detail?.ownership?.primary_assignee
  if (!owner) return detail?.ownership?.state === 'unassigned' ? t('Unassigned') : null
  if (detail.ownership.current_staff_access === 'primary') return t('Assigned to you')
  return owner.display_name ? t('Assigned to {name}', { name: owner.display_name }) : t('Assigned to another staff member')
}

function initials(name) {
  if (!name) return ''
  return name.split(/\s+/).filter(Boolean).slice(0, 2).map((part) => part[0].toLocaleUpperCase()).join('')
}

function updatedLabel(value) {
  if (!value) return t('Not recorded')
  try {
    return formatCompactDateTime(value)
  } catch {
    return t('Not recorded')
  }
}

function queueDescription(category) {
  if (category === 'attention') return t('Customer replies and unassigned requests')
  if (category === 'assigned') return t('Your current and recently resolved Claim conversations')
  return t('Internal assistance history')
}

function visibleConversationTabs(tabs, activeSessionId) {
  if (tabs.length <= MAX_VISIBLE_TABS) return { visible: tabs, overflow: [] }
  const firstTabs = tabs.slice(0, MAX_VISIBLE_TABS)
  const active = tabs.find((tab) => tab.sessionId === activeSessionId)
  const visible = active && !firstTabs.includes(active)
    ? [...tabs.slice(0, MAX_VISIBLE_TABS - 1), active]
    : firstTabs
  const visibleIds = new Set(visible.map((tab) => tab.claimId))
  return { visible, overflow: tabs.filter((tab) => !visibleIds.has(tab.claimId)) }
}

function moveCategoryFocus(event, currentIndex, onSelect) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const nextIndex = event.key === 'Home'
    ? 0
    : event.key === 'End'
      ? CATEGORIES.length - 1
      : event.key === 'ArrowRight'
        ? (currentIndex + 1) % CATEGORIES.length
        : (currentIndex - 1 + CATEGORIES.length) % CATEGORIES.length
  onSelect(CATEGORIES[nextIndex][0])
  event.currentTarget.parentElement?.querySelectorAll('[role="tab"]')[nextIndex]?.focus()
}

function moveOpenTabFocus(event, currentIndex, tabs, onActivate, onClose) {
  if (event.key === 'Delete') {
    event.preventDefault()
    onClose?.(tabs[currentIndex].claimId)
    return
  }
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  const nextIndex = event.key === 'Home'
    ? 0
    : event.key === 'End'
      ? tabs.length - 1
      : event.key === 'ArrowRight'
        ? (currentIndex + 1) % tabs.length
        : (currentIndex - 1 + tabs.length) % tabs.length
  onActivate(tabs[nextIndex])
  event.currentTarget.closest('[role="tablist"]')?.querySelectorAll('[role="tab"]')[nextIndex]?.focus()
}

function agentSessionTitle(conversation) {
  const title = conversation.title?.trim()
  if (title && !GENERIC_AGENT_TITLES.has(title.toLocaleLowerCase())) return title
  const preview = conversation.summary?.trim()
  if (preview) return shortMessageTitle(preview)
  return t('Empty conversation')
}

function shortMessageTitle(value) {
  const compactValue = value.replace(/\s+/g, ' ').trim()
  if (compactValue.length <= 64) return compactValue
  return `${compactValue.slice(0, 63).trimEnd()}…`
}

function agentSessionSearchText(conversation) {
  return [
    agentSessionTitle(conversation),
    conversation.summary?.trim() || t('No messages yet.'),
    updatedLabel(conversation.updated_at),
  ].join(' ').toLocaleLowerCase()
}
