import { formatDate, formatDateTime, formatTime, words } from '../format.js'
import { HandoffResolution, StaffActions } from './ReviewActions.jsx'
import { findProjectedAction } from '../projected-action.js'
import ResourceBoundary from './ResourceBoundary.jsx'
import { translate as t } from '../i18n.js'

export default function Activity({ detail, resources, onResolve, onUpdateAction, onRetry }) {
  const openHandoff = [...(resources.handoffs?.items || [])].reverse().find((item) => !['resolved', 'cancelled'].includes(item.status))
  const resolveAction = findProjectedAction(detail.allowed_actions, 'human.resolve_handoff', openHandoff?.handoff_id)
  const events = resources.events?.items || []
  const updates = resources.customerUpdates?.items || []
  const sourceItems = detail.source_summary?.items || []
  return (
    <div className="activity-view">
      <HandoffResolution handoff={openHandoff} allowedAction={resolveAction} onResolve={onResolve} />
      <ResourceBoundary resource={resources.workItems} onRetry={onRetry}><StaffActions actions={resources.workItems?.items || []} hasMore={Boolean(resources.workItems?.page?.next_cursor)} allowedActions={detail.allowed_actions || []} onUpdate={onUpdateAction} /></ResourceBoundary>
      <ResourceBoundary resource={resources.events} onRetry={onRetry}>
        <section className="resource-view activity-section" aria-labelledby="claim-activity-title">
          <header className="content-header activity-section__header">
            <p className="eyebrow">{t('Audit trail')}</p>
            <h2 id="claim-activity-title">{t('Claim activity')}</h2>
            <span className="activity-section__count">{resourceCountLabel(events.length, 'event', Boolean(resources.events?.page?.next_cursor))}</span>
          </header>
          <EventTimeline events={events} sourceItems={sourceItems} />
        </section>
      </ResourceBoundary>
      <ResourceBoundary resource={resources.customerUpdates} onRetry={onRetry}>
        <section className="resource-view activity-section" aria-labelledby="customer-updates-title">
          <header className="content-header activity-section__header">
            <p className="eyebrow">{t('Claimant-visible')}</p>
            <h2 id="customer-updates-title">{t('Customer updates')}</h2>
            <span className="activity-section__count">{resourceCountLabel(updates.length, 'update', Boolean(resources.customerUpdates?.page?.next_cursor))}</span>
          </header>
          <CustomerUpdateList updates={updates} />
        </section>
      </ResourceBoundary>
    </div>
  )
}

function EventTimeline({ events = [], sourceItems = [] }) {
  if (!events.length) {
    return (
      <div className="activity-empty activity-empty--compact">
        <span className="activity-empty__marker" aria-hidden="true" />
        <div>
          <strong>{t('No claim activity yet')}</strong>
          <p>{t('Audit events will appear here as this claim progresses.')}</p>
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
                const title = event.summary || eventTitle(event.event_type)
                return (
                  <li className="audit-event" key={event.event_id}>
                    <span className="audit-event__rail" aria-hidden="true"><span /></span>
                    <article className="audit-event__content">
                      <div className="audit-event__primary">
                        <h4>{title}</h4>
                        <time dateTime={timestamp || undefined}>{formatTime(timestamp)}</time>
                      </div>
                      <p className="audit-event__code">{words(event.event_type)}</p>
                      <EventContext event={event} sourceItems={sourceItems} title={title} />
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
        <span className="activity-empty__marker" aria-hidden="true" />
        <div>
          <strong>{t('No customer updates yet')}</strong>
          <p>{t('Claimant-visible updates will appear here after they are recorded.')}</p>
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

function EventContext({ event, sourceItems, title }) {
  const sourceRefs = event.source_refs || []
  const actor = actorLabel(event.actor_id)
  const sourceLabels = [...new Set(sourceRefs.map((reference, index) => (
    sourceReferenceLabel(event, reference, index, sourceItems)
  )))]
  return (
    <>
      {(actor || event.resulting_revision != null || sourceLabels.length) ? (
        <dl className="audit-event__context" aria-label={t('Event context')}>
          {actor ? <div><dt>{t('Recorded by')}</dt><dd>{actor}</dd></div> : null}
          {sourceLabels.length ? <div><dt>{t(sourceRefs.length === 1 ? 'Related record' : 'Related records')}</dt><dd>{sourceLabels.join(' · ')}</dd></div> : null}
          {event.resulting_revision != null ? <div><dt>{t('Claim version')}</dt><dd>{event.resulting_revision}</dd></div> : null}
        </dl>
      ) : null}
      <details className="audit-event__technical">
        <summary>{t('Technical details')}<span className="sr-only"> {t('for {title}', { title })}</span></summary>
        <dl>
          <div><dt>{t('Event reference')}</dt><dd><code>{event.event_id}</code></dd></div>
          <div><dt>{t('Event code')}</dt><dd><code>{event.event_type}</code></dd></div>
          {event.actor_id ? <div><dt>{t('Actor reference')}</dt><dd><code>{event.actor_id}</code></dd></div> : null}
          {sourceRefs.length ? (
            <div>
              <dt>{t('Source references')}</dt>
              <dd>
                <ul className="audit-event__reference-list">
                  {sourceRefs.map((reference, index) => (
                    <li key={`${reference}-${index}`}>
                      <span>{sourceReferenceLabel(event, reference, index, sourceItems)}</span>
                      <code>{reference}</code>
                    </li>
                  ))}
                </ul>
              </dd>
            </div>
          ) : null}
        </dl>
      </details>
    </>
  )
}

function actorLabel(actorId) {
  const actor = String(actorId || '').toLowerCase()
  if (actor === 'claimant' || actor.startsWith('cus_')) return t('Claimant')
  if (actor === 'agent') return t('Agent')
  if (actor === 'staff' || actor.startsWith('stf_')) return t('Claims professional')
  if (actor === 'system') return t('System')
  if (actor.startsWith('adm_')) return t('Administrator')
  return null
}

function sourceReferenceLabel(event, reference, index, sourceItems) {
  const authoritativeItem = sourceItems.find((item) => item.record_ref === reference)
  if (authoritativeItem?.label) return authoritativeItem.label

  const projectedLabel = projectedSourceLabel(event.event_type, index)
  if (projectedLabel) return projectedLabel

  const matchedPrefix = REFERENCE_LABELS.find(([prefix]) => String(reference).startsWith(prefix))
  return t(matchedPrefix?.[1] || 'Supporting record')
}

function projectedSourceLabel(eventType, index) {
  const type = String(eventType || '')
  if (type === 'claim.created' && index === 0) return t('Claim record')
  if (type === 'message.appended' && index === 0) return t('Message')
  if (type === 'message.appended' && index === 1) return t('Conversation')
  if (type.startsWith('handoff.') && index === 0) return t('Handoff record')
  if (type.startsWith('work_item.') && index === 0) return t('Staff work item')
  if (type === 'customer_update.recorded' && index === 0) return t('Customer update')
  if (type.startsWith('ownership.') && index === 0) {
    const requestKind = type.split('.')[1]
    return t({
      cowork: 'Cowork request',
      transfer: 'Transfer request',
      requeue: 'Queue return',
    }[requestKind] || 'Ownership request')
  }
  return null
}

const REFERENCE_LABELS = [
  ['claim:', 'Claim record'],
  ['field:', 'Claim field'],
  ['session:', 'Conversation'],
  ['evidence:', 'Evidence item'],
  ['asset:', 'Asset revision'],
  ['retrieval:', 'Reference check'],
  ['handoff:', 'Handoff record'],
  ['clm_', 'Claim record'],
  ['ses_', 'Conversation'],
  ['msg_', 'Message'],
  ['hnd_', 'Handoff record'],
  ['act_', 'Staff work item'],
  ['upd_', 'Customer update'],
  ['col_', 'Ownership request'],
  ['evd_', 'Evidence item'],
  ['tsk_', 'External service task'],
  ['asr_op_', 'External service operation'],
  ['res_', 'Result record'],
  ['pol_', 'Policy record'],
  ['his_', 'Claim history record'],
  ['sig_', 'Review signal'],
  ['sdec_', 'Signal decision'],
]

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

function resourceCountLabel(count, singular, hasMore = false) {
  const noun = count === 1 && !hasMore ? singular : `${singular}s`
  return t('{count} {noun}', { count: `${count}${hasMore ? '+' : ''}`, noun: t(noun) })
}
