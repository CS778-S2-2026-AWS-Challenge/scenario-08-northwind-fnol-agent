import {
  AlertTriangle,
  ChevronRight,
  Clock3,
  FileSearch,
  Send,
  ShieldAlert,
  ShieldCheck,
  UserRoundCheck,
} from 'lucide-react'
import { useState } from 'react'
import { formatDateTime, words } from '../format.js'
import { TagList } from './TagList.jsx'
import EvidenceRecords from './EvidenceRecords.jsx'
import ExternalServiceRecords from './ExternalServiceRecords.jsx'
import OwnershipActions from './OwnershipActions.jsx'
import ReferenceRecords from './ReferenceRecords.jsx'
import { HandoffResolution, SignalReviews, StaffActions } from './ReviewActions.jsx'

const SECTIONS = [
  ['summary', 'Overview'],
  ['conversation', 'Conversation'],
  ['fields', 'Claim information'],
  ['evidence', 'Evidence'],
  ['references', 'Reference checks'],
  ['external-services', 'External services'],
  ['signals', 'Signals'],
  ['activity', 'Activity'],
]

export default function ClaimWorkspace({
  detail,
  resources = {},
  loading,
  error,
  section,
  draft,
  profile,
  onSection,
  onDraft,
  onAccept,
  onResolve,
  onSignalDecision,
  onCreateAction,
  onUpdateAction,
  onLoadEvidence,
  onSend,
  onCoworkRequest,
  onTransferRequest,
  onRequeue,
  onCollaborationDecision,
}) {
  if (loading) return <main className="claim-state"><span className="loading-mark" /><p>Loading Claim...</p></main>
  if (error) return <main className="claim-state claim-state--error"><AlertTriangle /><h2>This Claim could not be opened</h2><p>{error}</p></main>
  if (!detail) return <EmptyWorkspace />

  return (
    <main className="claim-workspace">
      <header className="claim-heading">
        <div>
          <p className="eyebrow">Claim {detail.display_reference}</p>
          <h1>{detail.claimant?.display_name || detail.claimant?.customer_id}</h1>
          <div className="claim-heading__meta">
            <span>{words(detail.incident?.family)} claim</span>
            <span>{words(detail.lifecycle_state)}</span>
            <span>Revision {detail.revision}</span>
          </div>
        </div>
        <div className="claim-heading__status">
          <span className="status-indicator"><Clock3 size={15} /> Updated {formatDateTime(detail.updated_at)}</span>
        </div>
      </header>

      <nav className="section-tabs" aria-label="Claim sections" role="tablist">
        {SECTIONS.map(([value, label], index) => (
          <button className={section === value ? 'is-active' : ''} type="button" role="tab" id={`claim-tab-${value}`} aria-controls={`claim-panel-${value}`} aria-selected={section === value} tabIndex={section === value ? 0 : -1} key={value} onClick={() => onSection(value)} onKeyDown={(event) => moveTabFocus(event, index, onSection)}>
            {label}
          </button>
        ))}
      </nav>

      <div role="tabpanel" id={`claim-panel-${section}`} aria-labelledby={`claim-tab-${section}`}>
        {section === 'summary' && <Summary detail={detail} handoffs={resources.handoffs?.items || []} collaborationRequests={resources.collaborationRequests?.items || []} profile={profile} onAccept={onAccept} onResolve={onResolve} onCoworkRequest={onCoworkRequest} onTransferRequest={onTransferRequest} onRequeue={onRequeue} onCollaborationDecision={onCollaborationDecision} />}
        {section === 'conversation' && <Conversation detail={detail} resource={resources.messages} draft={draft} onDraft={onDraft} onSend={onSend} />}
        {section === 'fields' && <ClaimFields resource={resources.fields} />}
        {section === 'evidence' && <ResourceBoundary resource={resources.evidence}><EvidenceRecords claimId={detail.claim_id} records={resources.evidence?.items || []} onLoadEvidence={onLoadEvidence} /></ResourceBoundary>}
        {section === 'references' && <ResourceBoundary resource={resources.retrievals}><ReferenceRecords records={resources.retrievals?.items || []} /></ResourceBoundary>}
        {section === 'external-services' && <ResourceBoundary resource={resources.externalRequests}><ExternalServiceRecords records={resources.externalRequests?.items || []} /></ResourceBoundary>}
        {section === 'signals' && <ResourceBoundary resource={resources.signals}><SignalReviews signals={resources.signals?.items || []} onDecision={onSignalDecision} /></ResourceBoundary>}
        {section === 'activity' && <Activity resources={resources} onCreateAction={onCreateAction} onUpdateAction={onUpdateAction} />}
      </div>
    </main>
  )
}

function moveTabFocus(event, currentIndex, onSection) {
  if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
  event.preventDefault()
  let nextIndex = currentIndex
  if (event.key === 'ArrowLeft') nextIndex = (currentIndex - 1 + SECTIONS.length) % SECTIONS.length
  if (event.key === 'ArrowRight') nextIndex = (currentIndex + 1) % SECTIONS.length
  if (event.key === 'Home') nextIndex = 0
  if (event.key === 'End') nextIndex = SECTIONS.length - 1
  onSection(SECTIONS[nextIndex][0])
  event.currentTarget.parentElement?.querySelectorAll('[role="tab"]')[nextIndex]?.focus()
}

function EmptyWorkspace() {
  return (
    <main className="empty-workspace">
      <div className="empty-workspace__symbol"><FileSearch size={28} /></div>
      <p className="eyebrow">Workbench</p>
      <h1>Select a Claim to begin.</h1>
      <p>The queue keeps the work order visible. Opening a Claim does not accept or change it.</p>
    </main>
  )
}

function Summary({ detail, handoffs, collaborationRequests, profile, onAccept, onResolve, onCoworkRequest, onTransferRequest, onRequeue, onCollaborationDecision }) {
  const openHandoff = [...handoffs].reverse().find((item) => !['resolved', 'cancelled'].includes(item.status))
  const missing = detail.work_summary?.missing_information || []
  const attention = detail.work_summary?.risk_signals || []
  const primaryAction = detail.allowed_actions?.find((action) => action.action_code === 'human.accept_handoff')
    || detail.allowed_actions?.find((action) => action.availability !== 'blocked')
  const canAccept = primaryAction?.action_code === 'human.accept_handoff'
    && primaryAction.availability !== 'blocked'
    && openHandoff

  return (
    <div className="claim-content">
      <section className="work-summary" aria-labelledby="work-summary-title">
        <div className="section-heading">
          <div><p className="eyebrow">Work summary</p><h2 id="work-summary-title">What needs attention now</h2></div>
          <span className="responsibility"><UserRoundCheck size={16} />{ownershipLabel(detail.ownership, profile)}</span>
        </div>
        <p className="record-summary">{detail.incident?.summary}</p>
        <div className="summary-grid">
          <SummaryItem label="Lifecycle" value={words(detail.lifecycle_state)} />
          <SummaryItem label="Workflow" value={words(detail.workflow_state)} />
          <SummaryItem label="Priority" value={words(detail.priority_projection?.level)} />
          <SummaryItem label="Queue" value={words(detail.work_summary?.queue_key)} />
        </div>
        <div className="summary-callout">
          <div><p className="summary-callout__label">Customer-safe next step</p><p>{detail.customer_next_step?.summary || 'No next-step summary is available.'}</p></div>
          {detail.customer_next_step?.expected_by && <time>{formatDateTime(detail.customer_next_step.expected_by)}</time>}
        </div>
      </section>

      <section className="primary-action" aria-labelledby="primary-action-title">
        <div className="primary-action__icon"><ShieldCheck size={22} /></div>
        <div className="primary-action__copy">
          <p className="eyebrow">Current action</p>
          <h2 id="primary-action-title">{primaryAction?.label || 'Review the Claim summary'}</h2>
          <p>{primaryAction?.purpose || detail.work_summary?.primary_blocker || 'No controlled action currently requires staff input.'}</p>
          {primaryAction?.blocked_reason && <small>{primaryAction.blocked_reason}</small>}
        </div>
        {canAccept && <button className="button button--primary" type="button" onClick={() => onAccept(openHandoff)}>{primaryAction.label}</button>}
      </section>

      <HandoffResolution handoff={openHandoff} profile={profile} onResolve={onResolve} />

      <OwnershipActions
        actions={detail.allowed_actions || []}
        requests={collaborationRequests}
        onCoworkRequest={onCoworkRequest}
        onTransferRequest={onTransferRequest}
        onRequeue={onRequeue}
        onDecision={onCollaborationDecision}
      />

      <div className="detail-columns">
        <section className="detail-section">
          <div className="section-heading"><div><p className="eyebrow">Incomplete</p><h2>Missing information</h2></div><span className="count-badge">{missing.length}</span></div>
          {missing.length ? <ul className="missing-list">{missing.slice(0, 6).map((item) => <li key={`${item.kind}:${item.code}`}><ChevronRight size={15} /><span><strong>{item.label}</strong><small>{words(item.attention)} · {words(item.responsible_party)}</small></span></li>)}</ul> : <p className="empty-note">No blocking or upcoming information gap is projected.</p>}
        </section>
        <section className="detail-section">
          <div className="section-heading"><div><p className="eyebrow">Signals</p><h2>Needs attention</h2></div><ShieldAlert size={19} /></div>
          {attention.length ? <ul className="missing-list">{attention.map((item) => <li key={item.signal_id}><AlertTriangle size={15} /><span><strong>{item.label}</strong><small>{words(item.attention_level)} · {item.summary}</small></span></li>)}</ul> : <p className="empty-note">No risk signal currently needs attention.</p>}
        </section>
      </div>
      <section className="detail-section"><div className="section-heading"><div><p className="eyebrow">Classification</p><h2>Claim tags</h2></div></div><TagList tags={detail.tags || []} grouped /></section>
    </div>
  )
}

function ownershipLabel(ownership, profile) {
  const assignee = ownership?.primary_assignee
  if (assignee?.staff_id === profile?.staff_id) return 'Assigned to you'
  return assignee?.display_name || assignee?.staff_id || words(ownership?.state || 'unassigned')
}

function SummaryItem({ label, value }) {
  return <div><span>{label}</span><strong>{value || 'Not recorded'}</strong></div>
}

function ClaimFields({ resource }) {
  return (
    <ResourceBoundary resource={resource}>
      <section className="resource-view">
        <header className="content-header"><div><p className="eyebrow">Source-linked data</p><h2>Claim information</h2></div><span>{resource?.items?.length || 0} fields</span></header>
        <dl className="field-ledger">{(resource?.items || []).map(({ code, field }) => <div key={code}><dt>{words(code.replaceAll('.', ' '))}</dt><dd><strong>{formatValue(field.value)}</strong><small>{words(field.status)} · {words(field.source)} · {words(field.needed_for)}</small></dd></div>)}</dl>
      </section>
    </ResourceBoundary>
  )
}

function Conversation({ detail, resource, draft, onDraft, onSend }) {
  const [sending, setSending] = useState(false)
  const [sendError, setSendError] = useState('')
  const canSend = detail.allowed_actions?.some((action) => action.action_code === 'conversation.send_claimant_message' && action.availability !== 'blocked')

  async function submit(event) {
    event.preventDefault()
    if (!draft.trim() || !canSend) return
    setSending(true)
    setSendError('')
    try {
      await onSend(draft.trim())
      onDraft('')
    } catch (nextError) {
      setSendError(nextError.message)
    } finally {
      setSending(false)
    }
  }

  return (
    <ResourceBoundary resource={resource}>
      <section className="conversation-view">
        <header className="content-header"><div><p className="eyebrow">Shared Claim context</p><h2>Claimant conversation</h2></div><span>{resource?.items?.length || 0} messages</span></header>
        <div className="message-ledger">{(resource?.items || []).map((message) => <article className={`message message--${message.actor}`} key={message.message_id}><div><strong>{words(message.actor)}</strong><time>{formatDateTime(message.created_at)}</time></div><p>{message.content?.text || words(message.content?.type)}</p></article>)}</div>
        <form className="staff-reply" onSubmit={submit}><label htmlFor="staff-reply">Reply to claimant</label><textarea id="staff-reply" rows="3" value={draft} onChange={(event) => onDraft(event.target.value)} disabled={!canSend} placeholder={canSend ? 'Write a clear claimant-safe update' : 'Accept the staff handoff before replying'} /><div><span>This message will be visible to the claimant.</span><button className="button button--primary" type="submit" disabled={!canSend || !draft.trim() || sending}><Send size={16} />{sending ? 'Sending...' : 'Send message'}</button></div>{sendError && <p className="form-error" role="alert">{sendError}</p>}</form>
      </section>
    </ResourceBoundary>
  )
}

function Activity({ resources, onCreateAction, onUpdateAction }) {
  return (
    <div className="activity-view">
      <ResourceBoundary resource={resources.workItems}><StaffActions actions={resources.workItems?.items || []} onCreate={onCreateAction} onUpdate={onUpdateAction} /></ResourceBoundary>
      <ResourceBoundary resource={resources.events}><section className="resource-view"><header className="content-header"><div><p className="eyebrow">Audit trail</p><h2>Claim activity</h2></div></header><RecordList items={resources.events?.items} empty="No activity is recorded." render={(event) => <article className="reference-card" key={event.event_id}><strong>{words(event.event_type)}</strong><p>{event.summary}</p><small>{formatDateTime(event.created_at)}</small></article>} /></section></ResourceBoundary>
      <ResourceBoundary resource={resources.customerUpdates}><section className="resource-view"><header className="content-header"><div><p className="eyebrow">Claimant-visible</p><h2>Customer updates</h2></div></header><RecordList items={resources.customerUpdates?.items} empty="No claimant-visible update is recorded." render={(update) => <article className="reference-card" key={update.update_id}><strong>{words(update.responsible_party)}</strong><p>{update.summary}</p><small>{formatDateTime(update.created_at)}</small></article>} /></section></ResourceBoundary>
    </div>
  )
}

function ResourceBoundary({ resource, children }) {
  if (resource?.loading) return <div className="queue-state"><span className="loading-mark" /><p>Loading current records...</p></div>
  if (resource?.error) return <div className="claim-state claim-state--error" role="alert"><AlertTriangle /><h2>This section is unavailable</h2><p>{resource.error}</p></div>
  if (resource?.status === 'unavailable') return <div className="claim-state claim-state--error"><AlertTriangle /><h2>This source is unavailable</h2><p>{resource.limitation || 'The source did not provide a usable result.'}</p></div>
  return children
}

function RecordList({ items = [], empty, render }) {
  return items.length ? <div className="reference-grid">{items.map(render)}</div> : <p className="empty-note">{empty}</p>
}

function formatValue(value) {
  if (value === null || value === undefined || value === '') return 'Not recorded'
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
