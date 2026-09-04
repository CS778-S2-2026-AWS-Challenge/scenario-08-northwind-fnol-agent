import { AlertTriangle, Clock3, FileSearch } from 'lucide-react'
import { formatDateTime, words } from '../format.js'
import Activity from './Activity.jsx'
import Conversation from './Conversation.jsx'
import EvidenceRecords from './EvidenceRecords.jsx'
import ExternalServiceRecords from './ExternalServiceRecords.jsx'
import Overview from './Overview.jsx'
import ReferenceRecords from './ReferenceRecords.jsx'
import ResourceBoundary from './ResourceBoundary.jsx'
import { SignalReviews } from './ReviewActions.jsx'

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

export default function ClaimWorkspace({ detail, resources = {}, loading, error, section, draft, profile, onSection, onDraft, onAccept, onResolve, onSignalDecision, onUpdateAction, onLoadEvidence, onSend, onOwnershipAction }) {
  if (loading) return <main className="claim-state"><span className="loading-mark" /><p>Loading Claim...</p></main>
  if (error) return <main className="claim-state claim-state--error"><AlertTriangle /><h2>This Claim could not be opened</h2><p>{error}</p></main>
  if (!detail) return <EmptyWorkspace />

  return (
    <main className="claim-workspace">
      <ClaimHeader detail={detail} />
      <nav className="section-tabs" aria-label="Claim sections" role="tablist">
        {SECTIONS.map(([value, label], index) => <button className={section === value ? 'is-active' : ''} type="button" role="tab" id={`claim-tab-${value}`} aria-controls={`claim-panel-${value}`} aria-selected={section === value} tabIndex={section === value ? 0 : -1} key={value} onClick={() => onSection(value)} onKeyDown={(event) => moveTabFocus(event, index, onSection)}>{label}</button>)}
      </nav>
      <div role="tabpanel" id={`claim-panel-${section}`} aria-labelledby={`claim-tab-${section}`}>
        {section === 'summary' && <Overview detail={detail} handoffs={resources.handoffs?.items || []} collaborationRequests={resources.collaborationRequests?.items || []} profile={profile} onAccept={onAccept} onResolve={onResolve} onOwnershipAction={onOwnershipAction} onSection={onSection} />}
        {section === 'conversation' && <Conversation detail={detail} resource={resources.messages} draft={draft} onDraft={onDraft} onSend={onSend} />}
        {section === 'fields' && <ClaimFields resource={resources.fields} />}
        {section === 'evidence' && <ResourceBoundary resource={resources.evidence}><EvidenceRecords claimId={detail.claim_id} records={resources.evidence?.items || []} onLoadEvidence={onLoadEvidence} /></ResourceBoundary>}
        {section === 'references' && <ResourceBoundary resource={resources.retrievals}><ReferenceRecords records={resources.retrievals?.items || []} /></ResourceBoundary>}
        {section === 'external-services' && <ResourceBoundary resource={resources.externalRequests}><ExternalServiceRecords records={resources.externalRequests?.items || []} /></ResourceBoundary>}
        {section === 'signals' && <ResourceBoundary resource={resources.signals}><SignalReviews signals={resources.signals?.items || []} allowedActions={detail.allowed_actions || []} onDecision={onSignalDecision} /></ResourceBoundary>}
        {section === 'activity' && <Activity detail={detail} resources={resources} onResolve={onResolve} onUpdateAction={onUpdateAction} />}
      </div>
    </main>
  )
}

function ClaimHeader({ detail }) {
  return <header className="claim-heading"><div><p className="eyebrow">Claim {detail.display_reference}</p><h1>{detail.claimant?.display_name || detail.claimant?.customer_id}</h1><div className="claim-heading__meta"><span>{words(detail.incident?.family)} claim</span><span>{words(detail.lifecycle_state)}</span><span>Revision {detail.revision}</span></div></div><div className="claim-heading__status"><span className="status-indicator"><Clock3 size={16} /> Updated {formatDateTime(detail.updated_at)}</span></div></header>
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
  return <main className="empty-workspace"><div className="empty-workspace__symbol"><FileSearch size={28} /></div><p className="eyebrow">Workbench</p><h1>Select a Claim to begin.</h1><p>The queue keeps the work order visible. Opening a Claim does not accept or change it.</p></main>
}

function ClaimFields({ resource }) {
  return <ResourceBoundary resource={resource}><section className="resource-view"><header className="content-header"><div><p className="eyebrow">Source-linked data</p><h2>Claim information</h2></div><span>{resource?.items?.length || 0} fields</span></header><FieldLedger items={resource?.items} /></section></ResourceBoundary>
}

function FieldLedger({ items = [] }) {
  if (!items.length) return <p className="empty-note">No structured Claim Context is recorded.</p>
  return <dl className="fact-list">{items.map(({ code, field }) => <div key={code}><dt>{words(code.replaceAll('.', ' '))}</dt><dd><strong>{formatValue(field.value)}</strong><small>{words(field.status)} · {words(field.source)} · {words(field.needed_for)}</small></dd></div>)}</dl>
}

function formatValue(value) {
  if (value === null || value === undefined || value === '') return 'Not recorded'
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
