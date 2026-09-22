import { MessageCircle } from 'lucide-react'
import { formatDate, formatDateTime, formatTime, words } from '../format.js'
import { HandoffResolution, StaffActions } from './ReviewActions.jsx'
import { findProjectedAction } from '../projected-action.js'
import ResourceBoundary from './ResourceBoundary.jsx'

export default function Activity({ detail, resources, onResolve, onUpdateAction, onRetry }) {
  const openHandoff = [...(resources.handoffs?.items || [])].reverse().find((item) => !['resolved', 'cancelled'].includes(item.status))
  const resolveAction = findProjectedAction(detail.allowed_actions, 'human.resolve_handoff', openHandoff?.handoff_id)
  return (
    <div className="activity-view">
      <HandoffResolution handoff={openHandoff} allowedAction={resolveAction} onResolve={onResolve} />
      <ResourceBoundary resource={resources.workItems} onRetry={onRetry}><StaffActions actions={resources.workItems?.items || []} allowedActions={detail.allowed_actions || []} onUpdate={onUpdateAction} /></ResourceBoundary>
      <ResourceBoundary resource={resources.events} onRetry={onRetry}>
        <section className="resource-view activity-section" aria-labelledby="claim-activity-title">
          <header className="content-header activity-section__header">
            <div><p className="eyebrow">Audit trail</p><h2 id="claim-activity-title">Claim activity</h2></div>
          </header>
          <EventTimeline events={resources.events?.items} />
        </section>
      </ResourceBoundary>
      <ResourceBoundary resource={resources.customerUpdates} onRetry={onRetry}>
        <section className="resource-view activity-section" aria-labelledby="customer-updates-title">
          <header className="content-header activity-section__header">
            <div><p className="eyebrow">Claimant-visible</p><h2 id="customer-updates-title">Customer updates</h2></div>
          </header>
          <CustomerUpdateList updates={resources.customerUpdates?.items} />
        </section>
      </ResourceBoundary>
    </div>
  )
}

function EventTimeline({ events = [] }) {
  if (!events.length) {
    return (
      <div className="activity-empty activity-empty--compact">
        <div>
          <strong>No claim activity yet</strong>
          <p>Audit events will appear here as this Claim progresses.</p>
        </div>
      </div>
    )
  }

  return (
    <div className="audit-timeline">
      {groupEventsByDate(events).map((group, groupIndex) => {
        const headingId = `claim-activity-date-${groupIndex}`
        return (
          <section className="audit-timeline__day" aria-labelledby={headingId} key={`${group.date}-${groupIndex}`}>
            <h3 id={headingId}>{group.date}</h3>
            <ol className="audit-timeline__events">
              {group.events.map((event) => {
                const timestamp = eventTimestamp(event)
                return (
                  <li className="audit-event" key={event.event_id}>
                    <span className="audit-event__rail" aria-hidden="true"><span /></span>
                    <article className="audit-event__content">
                      <h4>{event.summary || eventTitle(event.event_type)}</h4>
                      <div className="audit-event__meta">
                        <span>{words(event.event_type)}</span>
                        <time dateTime={timestamp || undefined}>{formatTime(timestamp)}</time>
                      </div>
                    </article>
                  </li>
                )
              })}
            </ol>
          </section>
        )
      })}
    </div>
  )
}

function CustomerUpdateList({ updates = [] }) {
  if (!updates.length) {
    return (
      <div className="activity-empty">
        <span className="activity-empty__icon" aria-hidden="true"><MessageCircle /></span>
        <div>
          <strong>No customer updates yet</strong>
          <p>Claimant-visible updates will appear here after they are recorded.</p>
        </div>
      </div>
    )
  }

  return (
    <ul className="activity-update-list">
      {updates.map((update) => (
        <li key={update.update_id}>
          <article className="activity-update">
            <p>{update.summary}</p>
            <div className="activity-update__meta">
              <span>{words(update.responsible_party)}</span>
              <time dateTime={update.created_at}>{formatDateTime(update.created_at)}</time>
            </div>
          </article>
        </li>
      ))}
    </ul>
  )
}

function groupEventsByDate(events) {
  return events.reduce((groups, event) => {
    const date = formatDate(eventTimestamp(event))
    const currentGroup = groups.at(-1)
    if (currentGroup?.date === date) {
      currentGroup.events.push(event)
      return groups
    }
    groups.push({ date, events: [event] })
    return groups
  }, [])
}

function eventTimestamp(event) {
  return event.created_at
}

function eventTitle(eventType) {
  return words(String(eventType || '').replaceAll('.', '_'))
}
