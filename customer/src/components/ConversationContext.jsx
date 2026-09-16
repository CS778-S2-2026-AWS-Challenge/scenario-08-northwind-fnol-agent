import { useId } from 'react'

function Chevron({ expanded = null }) {
  const symbol = expanded === null ? '›' : expanded ? '⌃' : '⌄'
  return <span className="conversation-card-chevron" aria-hidden="true">{symbol}</span>
}

export function ClaimProgressDisclosure({ progress, expanded, onToggle }) {
  const detailsId = useId()
  const items = progress.items || []
  const countLabel = progress.available
    ? `${progress.current} of ${progress.total} required details`
    : 'Claim details starting'
  const progressLabel = progress.available
    ? `${progress.current} of ${progress.total} required details complete`
    : 'Claim requirements are not available yet'

  return (
    <section className={`claim-progress-disclosure ${expanded ? 'is-expanded' : ''}`}>
      <button
        className="claim-progress-trigger"
        type="button"
        aria-expanded={expanded}
        aria-controls={detailsId}
        aria-label={`Claim progress: ${progressLabel}${progress.label ? `. ${progress.label}` : ''}`}
        onClick={onToggle}
      >
        <span className="claim-progress-copy">
          <span>{countLabel}</span>
          {progress.label && <strong>{progress.label}</strong>}
        </span>
        <Chevron expanded={expanded} />
      </button>
      <span
        className="claim-progress-track"
        role={progress.available && progress.total > 0 ? 'progressbar' : undefined}
        aria-label={progress.available && progress.total > 0 ? progressLabel : undefined}
        aria-valuemin={progress.available && progress.total > 0 ? 0 : undefined}
        aria-valuemax={progress.available && progress.total > 0 ? progress.total : undefined}
        aria-valuenow={progress.available && progress.total > 0 ? progress.current : undefined}
      >
        <span
          className="claim-progress-fill"
          aria-hidden="true"
          style={{
            '--progress-width': progress.total > 0
              ? `${(progress.current / progress.total) * 100}%`
              : '0%',
          }}
        />
      </span>
      <div className="claim-progress-details" id={detailsId} hidden={!expanded}>
        {items.length > 0 ? (
          <ul className="claim-progress-requirements" aria-label="Claim requirements">
            {items.map((item) => (
              <li className={`is-${item.state}`} key={item.fieldCode}>
                <span className="claim-requirement-icon" aria-hidden="true">
                  {item.state === 'complete' ? '✓' : '○'}
                </span>
                <span>
                  <span className="sr-only">
                    {item.state === 'complete'
                      ? 'Complete: '
                      : item.state === 'later'
                        ? 'Needed later: '
                        : 'Required: '}
                  </span>
                  {item.label}
                </span>
                {item.state === 'later' && <small>Needed later</small>}
              </li>
            ))}
          </ul>
        ) : (
          <p>{progress.available
            ? 'Northwind will show each required detail here as it is identified.'
            : 'Describe what happened and Northwind will identify what is needed next.'}</p>
        )}
      </div>
    </section>
  )
}

export function ConversationEvent({ icon = '✓', title, detail, tone = 'success' }) {
  return (
    <div
      className={`conversation-event is-${tone}`}
      role={tone === 'urgent' ? 'alert' : 'status'}
      aria-label={detail ? `${title}. ${detail}` : title}
    >
      <span className="conversation-event-icon" aria-hidden="true">{icon}</span>
      <div className="conversation-event-copy">
        <strong>{title}</strong>
        {detail && <span className="conversation-event-detail"> · {detail}</span>}
      </div>
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
