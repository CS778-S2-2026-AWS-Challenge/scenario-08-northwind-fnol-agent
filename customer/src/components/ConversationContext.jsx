import { useId } from 'react'

function Chevron({ expanded = null }) {
  const symbol = expanded === null ? '›' : expanded ? '⌃' : '⌄'
  return <span className="conversation-card-chevron" aria-hidden="true">{symbol}</span>
}

// A system event in the conversation is a thin divider with one sentence, not a card.
export function ConversationEvent({ title, detail, tone = 'success' }) {
  return (
    <div
      className={`conversation-event is-${tone}`}
      role={tone === 'urgent' ? 'alert' : 'status'}
      aria-label={detail ? `${title}. ${detail}` : title}
    >
      <span className="conversation-event-copy">
        <strong>{title}</strong>
        {detail && <span className="conversation-event-detail"> · {detail}</span>}
      </span>
    </div>
  )
}

export function ConversationInfoPanel({ title, summary, expanded, onToggle, children, tone = 'default' }) {
  const detailsId = useId()

  return (
    <section className={`conversation-info-panel is-${tone}`}>
      <button
        className="conversation-info-trigger"
        type="button"
        aria-expanded={expanded}
        aria-controls={detailsId}
        onClick={onToggle}
      >
        <span className="conversation-info-copy">
          <strong>{title}</strong>
          {summary && <span>{summary}</span>}
        </span>
        <Chevron expanded={expanded} />
      </button>
      <div className="conversation-info-details" id={detailsId} hidden={!expanded}>
        {children}
      </div>
    </section>
  )
}

export function ConversationActionCard({
  icon,
  title,
  description,
  status,
  completed = false,
  expanded = null,
  onClick,
  children,
  disabled = false,
}) {
  const detailsId = useId()
  const expandable = expanded !== null

  return (
    <section className={`conversation-action-card ${completed ? 'is-completed' : ''}`}>
      <button
        className="conversation-action-trigger"
        type="button"
        aria-expanded={expandable ? expanded : undefined}
        aria-controls={expandable ? detailsId : undefined}
        onClick={onClick}
        disabled={disabled}
      >
        <span className="conversation-action-icon" aria-hidden="true">{icon}</span>
        <span className="conversation-action-copy">
          <strong>{title}</strong>
          <span>{description}</span>
        </span>
        <span className="conversation-action-meta">
          <span>{status}</span>
          <Chevron expanded={expanded} />
        </span>
      </button>
      {expandable && (
        <div className="conversation-action-details" id={detailsId} hidden={!expanded}>
          {children}
        </div>
      )}
    </section>
  )
}
