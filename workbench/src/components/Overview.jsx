import { UserRoundCheck } from 'lucide-react'
import { formatDateTime, words } from '../format.js'
import OwnershipActions from './OwnershipActions.jsx'
import { findPrimaryProjectedAction, findProjectedAction } from '../projected-action.js'
import { HandoffResolution } from './ReviewActions.jsx'
import MissingInformation from './MissingInformation.jsx'
import PrimaryAction from './PrimaryAction.jsx'
import SignalsSummary from './SignalsSummary.jsx'
import SourceSummary from './SourceSummary.jsx'
import { TagList } from './TagList.jsx'

export default function Overview({ detail, handoffs, collaborationRequests, profile, onAccept, onResolve, onOwnershipAction, onSection }) {
  const openHandoff = [...handoffs].reverse().find((item) => !['resolved', 'cancelled'].includes(item.status))
  const primaryAction = findPrimaryProjectedAction(detail.allowed_actions, detail.work_summary?.primary_action_code, detail.work_summary?.primary_action_target_ref)
  const resolveAction = findProjectedAction(detail.allowed_actions, 'human.resolve_handoff', openHandoff?.handoff_id)
  const primaryKey = primaryAction ? `${primaryAction.action_code}:${primaryAction.target_ref}` : null
  const summaries = detail.section_summaries || {}

  return (
    <div className="claim-content">
      <WorkSummary detail={detail} profile={profile} />
      <PrimaryAction action={primaryAction} handoff={openHandoff} request={collaborationRequests.find((item) => item.request_id === primaryAction?.target_ref)} onAccept={onAccept} onOwnershipAction={onOwnershipAction} onSection={onSection} />
      <SourceSummary summary={detail.source_summary} />
      <MissingInformation items={detail.work_summary?.missing_information || []} />

      <details className="purpose-disclosure">
        <summary>Ownership and handoff actions</summary>
        {primaryAction?.action_code !== 'human.resolve_handoff' && <HandoffResolution handoff={openHandoff} allowedAction={resolveAction} onResolve={onResolve} />}
        <OwnershipActions actions={detail.allowed_actions || []} requests={collaborationRequests} excludeAction={primaryKey} onAction={onOwnershipAction} />
        {!resolveAction && !(detail.allowed_actions || []).some((action) => action.action_code.startsWith('ownership.')) && <p className="empty-note">No secondary ownership action is projected.</p>}
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
      <div className="summary-callout"><div><p className="summary-callout__label">Customer-safe next step</p><p>{detail.customer_next_step?.summary || 'No next-step summary is available.'}</p></div>{detail.customer_next_step?.expected_by && <time>{formatDateTime(detail.customer_next_step.expected_by)}</time>}</div>
    </section>
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
