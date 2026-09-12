import { UserRoundCheck } from 'lucide-react'
import { failureReason, failureReference } from '../failure.js'
import { formatDateTime, words } from '../format.js'
import OwnershipActions from './OwnershipActions.jsx'
import { findPrimaryProjectedAction, findProjectedAction } from '../projected-action.js'
import { HandoffResolution } from './ReviewActions.jsx'
import MissingInformation from './MissingInformation.jsx'
import PrimaryAction from './PrimaryAction.jsx'
import SignalsSummary from './SignalsSummary.jsx'
import SourceSummary from './SourceSummary.jsx'
import { TagList } from './TagList.jsx'

export default function Overview({ detail, handoffs, collaborationRequests, supportingState = [], profile, onAccept, onResolve, onOwnershipAction, onReopen, onSection, onRetry }) {
  const [handoffState, collaborationState] = supportingState
  const allowedActions = (detail.allowed_actions || []).filter((action) => {
    if (action.target_type === 'handoff' && actionContextUnavailable(handoffState)) return false
    if (action.target_type === 'collaboration_request' && actionContextUnavailable(collaborationState)) return false
    return true
  })
  const openHandoff = [...handoffs].reverse().find((item) => !['resolved', 'cancelled'].includes(item.status))
  const primaryAction = findPrimaryProjectedAction(allowedActions, detail.work_summary?.primary_action_code, detail.work_summary?.primary_action_target_ref, detail.revision)
  const resolveAction = findProjectedAction(allowedActions, 'human.resolve_handoff', openHandoff?.handoff_id)
  const primaryKey = primaryAction ? `${primaryAction.action_code}:${primaryAction.target_ref}` : null
  const summaries = detail.section_summaries || {}
  const supportingIssue = supportingState.find((resource) => (
    resource?.error || ['partial', 'unavailable'].includes(resource?.status)
  ))
  const supportingError = supportingIssue?.error
  const supportingLoading = supportingState.some((resource) => resource?.loading)

  return (
    <div className="claim-content">
      <WorkSummary detail={detail} profile={profile} />
      {(supportingLoading || supportingIssue) && (
        <div className={`resource-notice${supportingError ? ' resource-notice--error' : ''}`} role={supportingError ? 'alert' : 'status'}>
          <div><strong>{supportingLoading ? 'Loading action context' : 'Some action context is unavailable'}</strong><p>{supportingLoading ? 'Handoff and collaboration records are loading.' : `The Claim remains readable, but affected actions stay unavailable. ${supportingIssue?.limitation || failureReason(supportingError)}`}</p>{failureReference(supportingError) && <small>{failureReference(supportingError)}</small>}</div>
          {!supportingLoading && <button className="button button--quiet" type="button" onClick={onRetry}>Refresh Claim</button>}
        </div>
      )}
      <PrimaryAction key={primaryKey || 'no-primary-action'} action={primaryAction} handoff={openHandoff} request={collaborationRequests.find((item) => item.request_id === primaryAction?.target_ref)} onAccept={onAccept} onOwnershipAction={onOwnershipAction} onReopen={onReopen} onSection={onSection} />
      <SourceSummary summary={detail.source_summary} />
      <MissingInformation items={detail.work_summary?.missing_information || []} />

      <details className="purpose-disclosure">
        <summary>Ownership and handoff actions</summary>
        {primaryAction?.action_code !== 'human.resolve_handoff' && <HandoffResolution handoff={openHandoff} allowedAction={resolveAction} onResolve={onResolve} />}
        <OwnershipActions actions={allowedActions} requests={collaborationRequests} excludeAction={primaryKey} onAction={onOwnershipAction} />
        {!resolveAction && !allowedActions.some((action) => action.action_code.startsWith('ownership.')) && <p className="empty-note">No secondary ownership action is projected.</p>}
      </details>

      <details className="purpose-disclosure">
        <summary>Supporting Claim context</summary>
        <div className="section-summary-grid">
          <SectionLink label="Claim information" summary={summaries.fields} onOpen={() => onSection('fields')} />
          <SectionLink label="Evidence" summary={summaries.evidence} onOpen={() => onSection('evidence')} />
          <SectionLink label="Reference checks" summary={summaries.reference_checks} onOpen={() => onSection('references')} />
          <SectionLink label="External services" summary={summaries.external_services} onOpen={() => onSection('external-services')} />
        </div>
      </details>

      <details className="purpose-disclosure">
        <summary>Signals and classification</summary>
        <SignalsSummary items={detail.work_summary?.risk_signals || []} onOpen={() => onSection('signals')} />
        <section className="disclosure-summary"><div className="section-heading"><div><p className="eyebrow">Classification</p><h2>Claim tags</h2></div><span className="count-badge">{detail.tags?.length || 0}</span></div><TagList tags={detail.tags || []} grouped /></section>
      </details>
    </div>
  )
}

function actionContextUnavailable(resource) {
  return Boolean(resource?.loading || resource?.error || ['partial', 'unavailable'].includes(resource?.status))
}

function WorkSummary({ detail, profile }) {
  return (
    <section className="work-summary" aria-labelledby="work-summary-title">
      <div className="section-heading"><div><p className="eyebrow">Work summary</p><h2 id="work-summary-title">What needs attention now</h2></div><span className="responsibility"><UserRoundCheck size={16} />{ownershipLabel(detail.ownership, profile)}</span></div>
      <p className="record-summary">{detail.incident?.summary}</p>
      <div className="summary-grid">
        <SummaryItem label="Lifecycle" value={words(detail.lifecycle_state)} />
        <SummaryItem label="Workflow" value={words(detail.workflow_state)} />
        <SummaryItem label="Priority" value={words(detail.priority_projection?.level)} />
        <SummaryItem label="Queue" value={words(detail.work_summary?.queue_key)} />
      </div>
      {detail.terminal_disposition && <TerminalSummary terminal={detail.terminal_disposition} />}
      <div className="summary-callout"><div><p className="summary-callout__label">Customer-safe next step</p><p>{detail.customer_next_step?.summary || 'No next-step summary is available.'}</p></div>{detail.customer_next_step?.expected_by && <time>{formatDateTime(detail.customer_next_step.expected_by)}</time>}</div>
    </section>
  )
}

function TerminalSummary({ terminal }) {
  return (
    <div className="terminal-summary" role="status">
      <div>
        <p className="terminal-summary__label">Terminal status · {words(terminal.value)}</p>
        <p>{words(terminal.reason_code)} · Recorded {formatDateTime(terminal.recorded_at)} at revision {terminal.recorded_revision}.</p>
        <small>Sources: {terminal.source_refs?.join(', ') || 'Not recorded'}</small>
      </div>
    </div>
  )
}

function SectionLink({ label, summary = {}, onOpen }) {
  const count = summary.total ?? 0
  const attention = summary.needs_attention ?? 0
  const unavailable = summary.status === 'unavailable'
  return (
    <article>
      <div>
        <strong>{label}</strong>
        <p>{count} records{attention ? ` · ${attention} need attention` : ''}{unavailable ? ' · Unavailable' : ''}</p>
        {summary.limitation && <small>{summary.limitation}</small>}
      </div>
      <button className="button button--quiet" type="button" onClick={onOpen}>Open</button>
    </article>
  )
}

function SummaryItem({ label, value }) {
  return <div className="summary-item"><span>{label}</span><strong>{value || 'Not recorded'}</strong></div>
}

function ownershipLabel(ownership, profile) {
  const assignee = ownership?.primary_assignee
  if (assignee?.staff_id === profile?.staff_id) return 'Assigned to you'
  return assignee?.display_name || assignee?.staff_id || words(ownership?.state || 'unassigned')
}
