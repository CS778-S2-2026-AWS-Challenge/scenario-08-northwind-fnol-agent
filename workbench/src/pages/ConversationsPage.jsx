import {
  ArrowLeft,
  ArrowRight,
  Bot,
  CheckCircle2,
  MessageSquareText,
  Search,
  UserRoundCheck,
} from 'lucide-react'
import { useState } from 'react'
import { failureReason, failureReference } from '../failure.js'
import { formatDateTime, words } from '../format.js'
import { translate as t } from '../i18n.js'

const AGENT_CONVERSATIONS_PER_PAGE = 5
const GENERIC_AGENT_TITLES = new Set([
  'new staff agent session',
  'new staff agent conversation',
  'new conversation',
])
const CONVERSATION_TIME_GROUPS = [
  ['today', 'Previous conversations'],
  ['yesterday', 'Yesterday'],
  ['previous-week', 'Previous 7 days'],
  ['older', 'Older'],
]

export default function ConversationsPage({
  conversations,
  loading,
  error,
  onRetry,
  onOpenConversation,
  selectedStaffAgentSessionId,
  assistanceRequests = [],
  assistanceLoading = false,
  assistanceError = null,
  onRetryAssistance = onRetry,
  onReviewRequest = onOpenConversation,
  onTakeOver,
}) {
  const [agentSearch, setAgentSearch] = useState('')
  const [agentPage, setAgentPage] = useState(1)
  const claimConversations = conversations.filter((item) => item.kind === 'claim')
  const activeClaimConversations = claimConversations.filter((item) => (
    item.assistance?.status !== 'resolved'
  ))
  const completedClaimConversations = claimConversations.filter((item) => (
    item.assistance?.status === 'resolved'
  ))
  const agentConversations = conversations.filter((item) => item.kind === 'staff_agent')
  const previousAgentConversations = selectedStaffAgentSessionId
    ? agentConversations.filter((item) => item.session_id !== selectedStaffAgentSessionId)
    : agentConversations
  const normalizedAgentSearch = agentSearch.trim().toLocaleLowerCase()
  const filteredAgentConversations = normalizedAgentSearch
    ? previousAgentConversations.filter((conversation) => (
      agentSessionSearchText(conversation).includes(normalizedAgentSearch)
    ))
    : previousAgentConversations
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
  const groupedAgentConversations = groupAgentConversations(visibleAgentConversations)

  function updateAgentSearch(value) {
    setAgentSearch(value)
    setAgentPage(1)
  }

  function openAgentConversation(conversation) {
    onOpenConversation(conversation)
  }

  return (
    <main className="conversations-page">
      <header className="content-header">
        <div>
          <p className="eyebrow">{t('Sessions')}</p>
          <h1>{t('Claim conversations')}</h1>
          <p>{t('Claim-bound conversations remain attached to their Claim workspace. Staff Agent sessions are kept separate.')}</p>
        </div>
      </header>
      <div className="conversation-groups">
        <section aria-labelledby="assistance-requests-title">
          <div className="section-heading">
            <div><p className="eyebrow">{t('Needs attention')}</p><h2 id="assistance-requests-title">{t('Human assistance requests')}</h2></div>
            <span className="count-badge">{assistanceRequests.length}</span>
          </div>
          {assistanceLoading && <p className="empty-note" aria-live="polite">{t('Loading assistance requests...')}</p>}
          {assistanceError && (
            <div className="form-error" role="alert">
              <strong>{t('Assistance requests are unavailable.')}</strong> {failureReason(assistanceError)}{' '}
              <button className="button button--quiet" type="button" onClick={onRetryAssistance}>{t('Retry')}</button>
              {failureReference(assistanceError) && <small>{failureReference(assistanceError)}</small>}
            </div>
          )}
          <div className="assistance-request-list">
            {assistanceRequests.map((request) => (
              <AssistanceRequestCard
                key={request.claim_id}
                request={request}
                onReview={onReviewRequest}
                onTakeOver={onTakeOver}
              />
            ))}
            {!assistanceLoading && !assistanceError && !assistanceRequests.length && (
              <p className="empty-note">{t('No customer assistance request is waiting for you.')}</p>
            )}
          </div>
        </section>

        <section aria-labelledby="active-conversations-title">
          <div className="section-heading">
            <div><p className="eyebrow">{t('Assigned work')}</p><h2 id="active-conversations-title">{t('My active conversations')}</h2></div>
            <span className="count-badge">{activeClaimConversations.length}</span>
          </div>
          {loading && <p className="empty-note" aria-live="polite">{t('Loading conversations...')}</p>}
          {error && <ConversationFailure error={error} onRetry={onRetry} />}
          <div className="conversation-cards">
            {activeClaimConversations.map((conversation) => (
              <ClaimConversationButton
                conversation={conversation}
                key={conversation.conversation_id}
                onOpen={onOpenConversation}
              />
            ))}
            {!loading && !error && !activeClaimConversations.length && <p className="empty-note">{t('No active Claim conversation is assigned to you.')}</p>}
          </div>
        </section>

        {completedClaimConversations.length > 0 && (
          <section aria-labelledby="completed-conversations-title">
            <div className="section-heading">
              <div><p className="eyebrow">{t('History')}</p><h2 id="completed-conversations-title">{t('Completed assistance')}</h2></div>
              <span className="count-badge">{completedClaimConversations.length}</span>
            </div>
            <div className="conversation-cards">
              {completedClaimConversations.map((conversation) => (
                <ClaimConversationButton
                  conversation={conversation}
                  key={conversation.conversation_id}
                  onOpen={onOpenConversation}
                />
              ))}
            </div>
          </section>
        )}

        <section className="staff-agent-conversations" aria-labelledby="staff-agent-conversations-title">
          <div className="section-heading">
            <div><p className="eyebrow">{t('Internal assistance')}</p><h2 id="staff-agent-conversations-title">{t('Staff Agent conversations')}</h2></div>
          </div>

          {loading && <p className="staff-agent-conversations__state" role="status">{t('Loading Staff Agent conversations...')}</p>}
          {error && (
            <div className="staff-agent-conversations__error" role="alert">
              <strong>{t('Staff Agent conversations are unavailable.')}</strong>
              <span>{failureReason(error)}</span>
              <button className="button button--quiet" type="button" onClick={onRetry}>{t('Retry')}</button>
              {failureReference(error) && <small>{failureReference(error)}</small>}
            </div>
          )}

          {!loading && !error && !agentConversations.length && (
            <p className="staff-agent-conversations__state" role="status">{t('No Staff Agent conversations yet.')}</p>
          )}

          {!loading && !error && agentConversations.length > 0 && !previousAgentConversations.length && (
            <p className="staff-agent-conversations__state" role="status">{t('No previous conversations yet.')}</p>
          )}

          {previousAgentConversations.length > 0 && (
            <div className="staff-agent-conversations__history">
              <div className="staff-agent-conversations__tools">
                <label className="staff-agent-conversations__search">
                  <span className="sr-only">{t('Search conversations')}</span>
                  <Search aria-hidden="true" />
                  <input
                    type="search"
                    value={agentSearch}
                    placeholder={t('Search conversations')}
                    onChange={(event) => updateAgentSearch(event.target.value)}
                  />
                </label>
                {normalizedAgentSearch && (
                  <small aria-live="polite">
                    {matchingConversationCount(filteredAgentConversations.length)}
                  </small>
                )}
              </div>

              {filteredAgentConversations.length > 0 ? (
                <>
                  <div className="staff-agent-conversations__groups">
                    {groupedAgentConversations.map((group) => (
                      <section className="staff-agent-conversations__group" key={group.key}>
                        <h4>{t(group.label)}</h4>
                        <ul aria-label={group.key === 'today' ? t('Previous conversations') : t('{group} conversations', { group: t(group.label) })}>
                          {group.items.map((conversation) => (
                            <li key={conversation.conversation_id}>
                              <AgentConversationButton conversation={conversation} onOpen={openAgentConversation} />
                            </li>
                          ))}
                        </ul>
                      </section>
                    ))}
                  </div>
                  {agentPageCount > 1 && (
                    <nav className="staff-agent-conversations__pagination" aria-label={t('Staff Agent conversation pages')}>
                      <small>
                        {t('Showing {start}–{end} of {total}', { start: agentPageStart + 1, end: Math.min(agentPageStart + AGENT_CONVERSATIONS_PER_PAGE, filteredAgentConversations.length), total: filteredAgentConversations.length })}
                      </small>
                      <span className="staff-agent-conversations__page-controls">
                        <button className="button button--quiet" type="button" disabled={currentAgentPage === 1} onClick={() => setAgentPage(currentAgentPage - 1)}>
                          <ArrowLeft aria-hidden="true" />{t('Previous')}
                        </button>
                        <span aria-live="polite" aria-atomic="true">{t('Page {page} of {total}', { page: currentAgentPage, total: agentPageCount })}</span>
                        <button className="button button--quiet" type="button" disabled={currentAgentPage === agentPageCount} onClick={() => setAgentPage(currentAgentPage + 1)}>
                          {t('Next')}<ArrowRight aria-hidden="true" />
                        </button>
                      </span>
                    </nav>
                  )}
                </>
              ) : (
                <div className="staff-agent-conversations__no-results" role="status">
                  <strong>{t('No conversations match “{query}”.', { query: agentSearch.trim() })}</strong>
                  <span>{t('Try another title, message preview, or updated time.')}</span>
                  <button className="button button--quiet" type="button" onClick={() => updateAgentSearch('')}>{t('Clear search')}</button>
                </div>
              )}
            </div>
          )}
        </section>
      </div>
    </main>
  )
}

function AssistanceRequestCard({ request, onReview, onTakeOver }) {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const handoff = request.handoff || {}
  const creationStatus = request.detail?.integration_summary?.claim_creation_status

  async function takeOver() {
    if (!onTakeOver || busy) return
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
    <article className="assistance-request">
      <div className="assistance-request__summary">
        <span className="assistance-request__icon" aria-hidden="true"><MessageSquareText /></span>
        <div>
          <span className="record-status">{t('Waiting request')}</span>
          <h3>{request.display_reference || request.claim_id}</h3>
          <p>{handoff.packet?.incident_summary || request.incident?.summary || t('No conversation summary is available.')}</p>
        </div>
      </div>
      <dl className="assistance-request__meta">
        <div><dt>{t('Requested')}</dt><dd>{handoff.created_at ? <time dateTime={handoff.created_at}>{formatDateTime(handoff.created_at)}</time> : t('Not recorded')}</dd></div>
        <div><dt>{t('Claim')}</dt><dd>{claimCreationLabel(creationStatus)}</dd></div>
        <div><dt>{t('Reason')}</dt><dd>{handoff.reason || t('No reason recorded')}</dd></div>
      </dl>
      <div className="assistance-request__actions">
        <button className="button button--quiet" type="button" onClick={() => onReview(request)}>{t('Review')}</button>
        {!confirming ? (
          <button className="button button--secondary" type="button" disabled={!request.canTakeOver} onClick={() => setConfirming(true)}>{t('Take over')}</button>
        ) : (
          <span className="assistance-request__confirm">
            <span>{t('Assign this conversation to you?')}</span>
            <button className="button button--ghost" type="button" disabled={busy} onClick={() => setConfirming(false)}>{t('Cancel')}</button>
            <button className="button button--secondary" type="button" disabled={busy} onClick={takeOver}>{t(busy ? 'Taking over...' : 'Confirm take over')}</button>
          </span>
        )}
      </div>
      {!request.canTakeOver && request.blockedReason && <p className="assistance-request__note">{request.blockedReason}</p>}
      {error && <p className="form-error" role="alert">{error}</p>}
    </article>
  )
}

function ClaimConversationButton({ conversation, onOpen }) {
  const state = claimConversationState(conversation)
  return (
    <button type="button" onClick={() => onOpen(conversation)}>
      {state.label === 'Completed' ? <CheckCircle2 size={18} /> : <UserRoundCheck size={18} />}
      <span>
        <strong>{conversation.title}</strong>
        <small>{conversation.summary || t('No summary is available.')}</small>
      </span>
      <span className={`record-status${state.tone ? ` record-status--${state.tone}` : ''}`}>{t(state.label)}</span>
    </button>
  )
}

function ConversationFailure({ error, onRetry }) {
  return (
    <div className="form-error" role="alert">
      <strong>{t('Conversations are unavailable.')}</strong> {failureReason(error)}{' '}
      <button className="button button--quiet" type="button" onClick={onRetry}>{t('Retry')}</button>
      {failureReference(error) && <small>{failureReference(error)}</small>}
    </div>
  )
}

function claimConversationState(conversation) {
  if (conversation.assistance?.status === 'resolved') return { label: 'Completed', tone: 'confirmed' }
  if ((conversation.detail?.work_summary?.unread_claimant_messages || 0) > 0) return { label: 'Action needed', tone: 'attention' }
  if (conversation.assistance?.waitingForCustomer) return { label: 'Waiting for customer', tone: '' }
  return { label: 'Assigned to me', tone: 'confirmed' }
}

function claimCreationLabel(value) {
  if (value === 'created') return t('Claim created')
  if (value) return t('Claim creation: {status}', { status: words(value) })
  return t('Claim not yet created')
}

function AgentConversationButton({ conversation, onOpen }) {
  return (
    <button
      className="staff-agent-conversations__conversation"
      type="button"
      onClick={() => onOpen(conversation)}
    >
      <span className="staff-agent-conversations__icon" aria-hidden="true"><Bot /></span>
      <span className="staff-agent-conversations__copy">
        <strong>{agentSessionTitle(conversation)}</strong>
        <small>{agentSessionPreview(conversation)}</small>
      </span>
      <span className="staff-agent-conversations__meta">
        {conversation.unread_count > 0 && (
          <span className="staff-agent-conversations__unread">
            {t('{count} unread', { count: conversation.unread_count })}
          </span>
        )}
        {conversation.updated_at
          ? <time dateTime={conversation.updated_at}>{agentSessionUpdatedLabel(conversation.updated_at)}</time>
          : <span>{agentSessionUpdatedLabel()}</span>}
      </span>
    </button>
  )
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

function agentSessionPreview(conversation) {
  return conversation.summary?.trim() || t('No messages yet.')
}

function agentSessionUpdatedLabel(value) {
  if (!value) return t('Update time not recorded')
  try {
    return t('Updated {date}', { date: formatDateTime(value) })
  } catch {
    return t('Update time not recorded')
  }
}

function agentSessionSearchText(conversation) {
  return [
    agentSessionTitle(conversation),
    agentSessionPreview(conversation),
    agentSessionUpdatedLabel(conversation.updated_at),
  ].join(' ').toLocaleLowerCase()
}

function groupAgentConversations(conversations, now = new Date()) {
  const startOfToday = new Date(now)
  startOfToday.setHours(0, 0, 0, 0)
  const startOfYesterday = new Date(startOfToday)
  startOfYesterday.setDate(startOfYesterday.getDate() - 1)
  const startOfPreviousWeek = new Date(startOfToday)
  startOfPreviousWeek.setDate(startOfPreviousWeek.getDate() - 7)
  const groups = new Map(CONVERSATION_TIME_GROUPS.map(([key, label]) => (
    [key, { key, label, items: [] }]
  )))

  for (const conversation of conversations) {
    const updatedAt = new Date(conversation.updated_at)
    let groupKey = 'older'
    if (!Number.isNaN(updatedAt.getTime())) {
      if (updatedAt >= startOfToday) groupKey = 'today'
      else if (updatedAt >= startOfYesterday) groupKey = 'yesterday'
      else if (updatedAt >= startOfPreviousWeek) groupKey = 'previous-week'
    }
    groups.get(groupKey).items.push(conversation)
  }

  return [...groups.values()].filter((group) => group.items.length > 0)
}

function matchingConversationCount(count) {
  return t(count === 1 ? '{count} matching conversation' : '{count} matching conversations', { count })
}
