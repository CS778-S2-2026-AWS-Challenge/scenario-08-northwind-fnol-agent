import { useEffect, useId, useMemo, useRef, useState } from 'react'
import { claimTitle, sortClaimsByLatestUpdate } from '../formatters.js'

const MOBILE_QUERY = '(max-width: 640px)'
const HISTORY_GROUPS = [
  ['today', 'TODAY'],
  ['previous', 'PREVIOUS 7 DAYS'],
  ['older', 'OLDER'],
]

function useMobileDrawer() {
  const [isMobile, setIsMobile] = useState(
    () => globalThis.matchMedia?.(MOBILE_QUERY).matches ?? false,
  )

  useEffect(() => {
    const mediaQuery = globalThis.matchMedia?.(MOBILE_QUERY)
    if (!mediaQuery) return undefined
    const update = (event) => setIsMobile(event.matches)
    mediaQuery.addEventListener?.('change', update)
    return () => mediaQuery.removeEventListener?.('change', update)
  }, [])

  return isMobile
}

function zonedDateParts(value) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return null
  const parts = new Intl.DateTimeFormat('en-NZ', {
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
    timeZone: 'Pacific/Auckland',
  }).formatToParts(date)
  const values = Object.fromEntries(parts.map((part) => [part.type, part.value]))
  return {
    day: Number(values.day),
    month: Number(values.month),
    year: Number(values.year),
  }
}

function dayNumber(value) {
  const parts = zonedDateParts(value)
  return parts ? Date.UTC(parts.year, parts.month - 1, parts.day) / 86_400_000 : null
}

function groupConversationHistory(conversations, now = new Date()) {
  const today = dayNumber(now)
  const groups = { today: [], previous: [], older: [] }

  for (const conversation of sortClaimsByLatestUpdate(conversations)) {
    const updatedDay = dayNumber(conversation.updated_at || conversation.created_at)
    const age = today !== null && updatedDay !== null ? today - updatedDay : null
    if (age === 0) groups.today.push(conversation)
    else if (age !== null && age > 0 && age < 7) groups.previous.push(conversation)
    else groups.older.push(conversation)
  }

  return groups
}

function historyItemDate(conversation, group) {
  const value = conversation.updated_at || conversation.created_at
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return 'Date unavailable'
  const options = group === 'today'
    ? { timeStyle: 'short' }
    : group === 'previous'
      ? { weekday: 'short', hour: 'numeric', minute: '2-digit' }
      : { dateStyle: 'medium' }
  return new Intl.DateTimeFormat('en-NZ', {
    ...options,
    timeZone: 'Pacific/Auckland',
  }).format(date)
}

function RailAction({ description, icon, onClick, disabled = false }) {
  const tooltipId = useId()

  return (
    <button
      className="conversation-sidebar-icon-button"
      type="button"
      aria-label={description}
      aria-describedby={tooltipId}
      onClick={onClick}
      onKeyDown={(event) => {
        if (event.key === 'Escape') event.currentTarget.blur()
      }}
      disabled={disabled}
    >
      <span className="conversation-sidebar-icon" aria-hidden="true">{icon}</span>
      <span className="conversation-sidebar-tooltip" id={tooltipId} role="tooltip">
        {description}
      </span>
    </button>
  )
}

export default function ConversationHistorySidebar({
  account,
  activeClaimId,
  busy,
  conversations,
  error,
  isOpen,
  loading,
  onClose,
  onLogin,
  onNewConversation,
  onOpen,
  onRetry,
  onSelect,
}) {
  const [query, setQuery] = useState('')
  const isMobile = useMobileDrawer()
  const panelRef = useRef(null)
  const closeButtonRef = useRef(null)
  const openerRef = useRef(null)
  const onCloseRef = useRef(onClose)
  const headingId = useId()
  const searchId = useId()

  useEffect(() => {
    onCloseRef.current = onClose
  }, [onClose])

  useEffect(() => {
    if (!isOpen) return undefined
    const previousFocus = openerRef.current || document.activeElement
    closeButtonRef.current?.focus()
    return () => {
      if (previousFocus?.isConnected) previousFocus.focus()
      openerRef.current = null
    }
  }, [isOpen])

  useEffect(() => {
    if (!isOpen) return undefined
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onCloseRef.current()
        return
      }
      if (!isMobile || event.key !== 'Tab') return
      const focusable = [...panelRef.current.querySelectorAll(
        'button:not([disabled]), input:not([disabled]), [href], [tabindex]:not([tabindex="-1"])',
      )].filter((element) => !element.hidden)
      if (focusable.length === 0) return
      const first = focusable[0]
      const last = focusable.at(-1)
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => document.removeEventListener('keydown', handleKeyDown)
  }, [isMobile, isOpen])

  const filteredConversations = useMemo(() => {
    const normalizedQuery = query.trim().toLocaleLowerCase('en-NZ')
    if (!normalizedQuery) return conversations
    return conversations.filter((conversation) => (
      claimTitle(conversation).toLocaleLowerCase('en-NZ').includes(normalizedQuery)
    ))
  }, [conversations, query])
  const groupedConversations = useMemo(
    () => groupConversationHistory(filteredConversations),
    [filteredConversations],
  )

  function requestOpen(event) {
    openerRef.current = event.currentTarget
    setQuery('')
    onOpen()
  }

  function renderHistory() {
    if (loading) {
      return <p className="conversation-sidebar-state" role="status">Loading conversations…</p>
    }
    if (error && conversations.length === 0) {
      return (
        <div className="conversation-sidebar-state is-error" role="alert">
          <strong>Conversations could not be loaded</strong>
          <p>{error}</p>
          <button className="conversation-sidebar-secondary" type="button" onClick={onRetry}>
            Try again
          </button>
        </div>
      )
    }
    if (conversations.length === 0) {
      return (
        <div className="conversation-sidebar-state">
          <strong>{account ? 'No saved conversations yet' : 'No conversations in this browser session'}</strong>
          <p>Start a claim and resumable conversations will appear here.</p>
        </div>
      )
    }
    if (filteredConversations.length === 0) {
      return <p className="conversation-sidebar-state">No conversations match your search.</p>
    }

    return (
      <>
        {error && (
          <div className="conversation-sidebar-stale" role="status">
            <span>Showing saved conversations. The list may be out of date.</span>
            <button type="button" onClick={onRetry}>Retry</button>
          </div>
        )}
        <div className="conversation-sidebar-groups">
          {HISTORY_GROUPS.map(([groupKey, groupLabel]) => {
            const group = groupedConversations[groupKey]
            if (group.length === 0) return null
            return (
              <section className="conversation-sidebar-group" key={groupKey} aria-labelledby={`${headingId}-${groupKey}`}>
                <h3 id={`${headingId}-${groupKey}`}>{groupLabel}</h3>
                <ol>
                  {group.map((conversation) => {
                    const title = claimTitle(conversation)
                    const dateLabel = historyItemDate(conversation, groupKey)
                    const isActive = conversation.claim_id === activeClaimId
                    return (
                      <li key={conversation.claim_id}>
                        <button
                          className={`conversation-sidebar-item ${isActive ? 'is-active' : ''}`}
                          type="button"
                          aria-current={isActive ? 'page' : undefined}
                          aria-label={`Open ${title}, ${dateLabel}`}
                          onClick={isActive ? undefined : () => onSelect(conversation.claim_id)}
                          disabled={busy}
                        >
                          <span>{title}</span>
                          <time dateTime={conversation.updated_at || conversation.created_at}>{dateLabel}</time>
                        </button>
                      </li>
                    )
                  })}
                </ol>
              </section>
            )
          })}
        </div>
      </>
    )
  }

  return (
    <>
      <nav className="conversation-sidebar-rail" aria-label="Conversation shortcuts">
        <RailAction description="Expand conversation history" icon="☰" onClick={requestOpen} />
        <RailAction description="New conversation" icon="＋" onClick={onNewConversation} disabled={busy} />
        <RailAction description="View conversation history" icon="◷" onClick={requestOpen} />
      </nav>
      <button
        className="conversation-sidebar-mobile-trigger"
        type="button"
        aria-label="Open conversation history"
        aria-expanded={isOpen}
        onClick={requestOpen}
      >
        <span aria-hidden="true">☰</span>
      </button>
      {isOpen && (
        <div className={`conversation-sidebar-overlay ${isMobile ? 'is-mobile' : ''}`}>
          <button
            className="conversation-sidebar-scrim"
            type="button"
            aria-label="Close conversation history"
            aria-hidden="true"
            tabIndex={-1}
            onClick={onClose}
          />
          <aside
            className="conversation-sidebar-panel"
            ref={panelRef}
            role={isMobile ? 'dialog' : undefined}
            aria-modal={isMobile ? 'true' : undefined}
            aria-labelledby={headingId}
          >
            <header className="conversation-sidebar-header">
              <h2 id={headingId}>Conversation history</h2>
              <button
                className="conversation-sidebar-close"
                ref={closeButtonRef}
                type="button"
                aria-label="Collapse conversation history"
                onClick={onClose}
              >
                <span aria-hidden="true">‹</span>
              </button>
            </header>
            <button
              className="conversation-sidebar-new"
              type="button"
              onClick={onNewConversation}
              disabled={busy}
            >
              <span aria-hidden="true">＋</span>
              <span>New conversation</span>
            </button>
            <div className="conversation-sidebar-search">
              <label className="sr-only" htmlFor={searchId}>Search conversations</label>
              <input
                id={searchId}
                type="search"
                value={query}
                placeholder="Search conversations..."
                onChange={(event) => setQuery(event.target.value)}
              />
            </div>
            <div className="conversation-sidebar-content">
              {renderHistory()}
            </div>
            {!account && (
              <footer className="conversation-sidebar-local-note">
                <span>Saved in this browser session.</span>{' '}
                <button type="button" onClick={onLogin}>Sign in</button>{' '}
                <span>to access conversations across devices.</span>
              </footer>
            )}
          </aside>
        </div>
      )}
    </>
  )
}
