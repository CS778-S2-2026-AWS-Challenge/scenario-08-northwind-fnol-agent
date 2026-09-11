import { formatDateTime, words } from '../format.js'
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
      <ResourceBoundary resource={resources.events} onRetry={onRetry}><section className="resource-view"><header className="content-header"><div><p className="eyebrow">Audit trail</p><h2>Claim activity</h2></div></header><RecordList items={resources.events?.items} empty="No activity is recorded." render={(event) => <article className="reference-card" key={event.event_id}><strong>{words(event.event_type)}</strong><p>{event.summary}</p><small>{formatDateTime(event.created_at)}</small></article>} /></section></ResourceBoundary>
      <ResourceBoundary resource={resources.customerUpdates} onRetry={onRetry}><section className="resource-view"><header className="content-header"><div><p className="eyebrow">Claimant-visible</p><h2>Customer updates</h2></div></header><RecordList items={resources.customerUpdates?.items} empty="No claimant-visible update is recorded." render={(update) => <article className="reference-card" key={update.update_id}><strong>{words(update.responsible_party)}</strong><p>{update.summary}</p><small>{formatDateTime(update.created_at)}</small></article>} /></section></ResourceBoundary>
    </div>
  )
}

function RecordList({ items = [], empty, render }) {
  return items.length ? <div className="reference-grid">{items.map(render)}</div> : <p className="empty-note">{empty}</p>
}
