import { AlertTriangle, Clock3, FileSearch } from 'lucide-react'
import { claimIdentity } from '../claim-identity.js'
import { failureReason, failureReference } from '../failure.js'
import { formatDateTime, words } from '../format.js'
import { translate as t } from '../i18n.js'
import Activity from './Activity.jsx'
import Conversation from './Conversation.jsx'
import EvidenceRecords from './EvidenceRecords.jsx'
import ExternalServiceRecords from './ExternalServiceRecords.jsx'
import Overview from './Overview.jsx'
import ReferenceRecords from './ReferenceRecords.jsx'
import ResourceBoundary from './ResourceBoundary.jsx'
import WaitingList from './WaitingList.jsx'
import { openWaitingCount } from '../waiting-list.js'
import { SignalReviews } from './ReviewActions.jsx'

const SECTIONS = [
  ['summary', 'Overview'],
  ['waiting', 'Waiting list'],
  ['conversation', 'Conversation'],
  ['fields', 'Claim information'],
  ['evidence', 'Evidence'],
  ['references', 'Reference checks'],
  ['external-services', 'External services'],
  ['signals', 'Signals'],
  ['activity', 'Activity'],
]

export default function ClaimWorkspace({ detail, resources = {}, loading, error, stale, externalActionNotices = [], section, conversationSessionId, draft, profile, readOnly = false, onSection, onDraft, onAccept, onAcceptClaim, onResolve, onSignalDecision, onUpdateAction, onLoadEvidence, onSend, onOwnershipAction, onReopen, onClaimDecision, onAnswerQuestion, onCorrectReading, onExternalTaskAction, onRetry, onRetrySection, onRetryExternalActionContext }) {
  if (loading && !detail) return <main className="claim-state" role="status"><span className="loading-mark" /><p>{t('Loading Claim...')}</p></main>
  if (error && !detail) return <ClaimUnavailable error={error} onRetry={onRetry} />
  if (!detail) return <EmptyWorkspace />
  const baseInteractionDetail = readOnly || stale || error ? { ...detail, allowed_actions: [] } : detail
  const guardedExternalTaskIds = new Set(
    externalActionNotices.map((notice) => notice.taskId).filter(Boolean),
  )
  const interactionDetail = guardedExternalTaskIds.size
    ? {
        ...baseInteractionDetail,
        allowed_actions: (baseInteractionDetail.allowed_actions || []).filter(
          (action) => !(
            action.target_type === 'external_task'
            && guardedExternalTaskIds.has(action.target_ref)
          ),
        ),
      }
    : baseInteractionDetail
  const waitingCount = openWaitingCount(detail.open_items || [])
  const externalActions = resourceActionContextUnavailable(resources.externalRequests)
    ? []
    : interactionDetail.allowed_actions

  return (
    <main className="claim-workspace">
      {(loading || stale || error) && <ClaimSyncNotice loading={loading} error={error} onRetry={onRetry} />}
      {externalActionNotices.map((notice) => (
        <section className="claim-sync-notice" role="alert" aria-live="assertive" key={`${notice.claimId}:${notice.taskId}`}>
          <strong>{t('External-service action outcome not confirmed')}</strong>
          <p>{notice.message}</p>
          <p><strong>{t('External task:')}</strong> {notice.taskId}</p>
          <button
            className="button button--quiet"
            type="button"
            disabled={notice.recovering}
            onClick={() => onRetryExternalActionContext(notice.taskId)}
          >
            {t(notice.recovering ? 'Refreshing Claim and External Services...' : 'Refresh Claim and External Services')}
          </button>
        </section>
      ))}
      {readOnly && (
        <div className="draft-read-only-notice" role="status">
          <strong>{t('Draft Claim · Read only')}</strong>
          <span>{t('This customer is still completing the Claim. Review the current information without accepting work or changing its state.')}</span>
        </div>
      )}
      {section !== 'conversation' && <ClaimHeader detail={detail} />}
      <nav className="section-tabs" aria-label={t('Claim sections')} role="tablist">
        {SECTIONS.map(([value, label], index) => <button className={section === value ? 'is-active' : ''} type="button" role="tab" id={`claim-tab-${value}`} aria-controls={`claim-panel-${value}`} aria-selected={section === value} tabIndex={section === value ? 0 : -1} key={value} onClick={() => onSection(value)} onKeyDown={(event) => moveTabFocus(event, index, onSection)}>{t(label)}{value === 'waiting' && waitingCount > 0 && <span className="count-badge">{waitingCount}</span>}</button>)}
      </nav>
      <div role="tabpanel" id={`claim-panel-${section}`} aria-labelledby={`claim-tab-${section}`}>
        {section === 'summary' && <Overview key={detail.claim_id} detail={interactionDetail} handoffs={resources.handoffs?.items || []} collaborationRequests={resources.collaborationRequests?.items || []} supportingState={[resources.handoffs, resources.collaborationRequests]} profile={profile} readOnly={readOnly} onAccept={onAccept} onAcceptClaim={onAcceptClaim} onResolve={onResolve} onOwnershipAction={onOwnershipAction} onReopen={onReopen} onClaimDecision={onClaimDecision} onSection={onSection} onRetry={onRetry} />}
        {section === 'waiting' && <WaitingList key={detail.claim_id} items={detail.open_items || []} actions={interactionDetail.allowed_actions} readOnly={readOnly} onDecide={onAnswerQuestion} />}
        {section === 'conversation' && <Conversation key={detail.claim_id} detail={interactionDetail} handoffs={resources.handoffs?.items || []} profile={profile} resource={resources.messages} requestedSessionId={conversationSessionId} draft={draft} readOnly={readOnly} onDraft={onDraft} onAccept={onAccept} onResolve={onResolve} onSend={onSend} onRetry={onRetrySection} />}
        {section === 'fields' && <ClaimFields resource={resources.fields} onRetry={onRetrySection} />}
        {section === 'evidence' && <ResourceBoundary resource={resources.evidence} onRetry={onRetrySection}><EvidenceRecords claimId={detail.claim_id} records={resources.evidence?.items || []} readings={detail.file_readings || {}} staffReadings={detail.staff_file_readings || []} actions={interactionDetail.allowed_actions} onLoadEvidence={onLoadEvidence} onCorrectReading={readOnly ? undefined : onCorrectReading} /></ResourceBoundary>}
        {section === 'references' && <ResourceBoundary resource={resources.retrievals} onRetry={onRetrySection}><ReferenceRecords records={resources.retrievals?.items || []} /></ResourceBoundary>}
        {section === 'external-services' && <ResourceBoundary resource={resources.externalRequests} onRetry={onRetrySection}><ExternalServiceRecords records={resources.externalRequests?.items || []} capabilities={detail.external_capabilities || []} allowedActions={externalActions} claimRevision={interactionDetail.revision} onAction={readOnly ? undefined : onExternalTaskAction} /></ResourceBoundary>}
        {section === 'signals' && <ResourceBoundary resource={resources.signals} onRetry={onRetrySection}><SignalReviews key={detail.claim_id} signals={resources.signals?.items || []} allowedActions={interactionDetail.allowed_actions} onDecision={readOnly ? undefined : onSignalDecision} /></ResourceBoundary>}
        {section === 'activity' && <Activity key={detail.claim_id} detail={interactionDetail} resources={resources} onResolve={readOnly ? undefined : onResolve} onUpdateAction={readOnly ? undefined : onUpdateAction} onRetry={onRetrySection} />}
      </div>
    </main>
  )
}

function resourceActionContextUnavailable(resource) {
  return Boolean(
    resource?.loading
    || resource?.error
    || resource?.stale
    || ['partial', 'unavailable'].includes(resource?.status),
  )
}

function ClaimHeader({ detail }) {
  const identity = claimIdentity(detail)
  return (
    <header className="claim-heading">
      <div className="claim-heading__identity">
        <p className="eyebrow">{identity.typeLabel}</p>
        <h1>{identity.title}</h1>
        {identity.incidentSummary && identity.incidentSummary !== identity.title
          ? <p className="claim-heading__summary">{identity.incidentSummary}</p>
          : null}
        {detail.work_summary?.conversation_turn && (
          <p className={`claim-heading__turn ${detail.work_summary.conversation_turn === 'claimant_replied' ? 'is-replied' : ''}`}>
            {detail.work_summary.conversation_turn === 'claimant_replied'
              ? `${t('Claimant replied')} · ${detail.work_summary.unread_claimant_messages}`
              : t('Waiting on the claimant')}
          </p>
        )}
        <div className="claim-heading__meta">
          {detail.terminal_disposition && <span>{t('Terminal')}: {words(detail.terminal_disposition.value)}</span>}
          <span>{words(detail.lifecycle_state)}</span>
          <span>{t('Revision')} {detail.revision}</span>
          <span className="claim-heading__reference">{t('Claim')} {identity.referenceLabel}</span>
        </div>
        {(identity.reference || detail.claimant?.customer_id) ? (
          <details className="claim-heading__references">
            <summary>{t('Record references')}<span className="sr-only"> {t('for {title}', { title: identity.title })}</span></summary>
            <dl>
              {identity.reference ? <div><dt>{t('Claim reference')}</dt><dd><code>{identity.reference}</code></dd></div> : null}
              {identity.claimId && identity.claimId !== identity.reference
                ? <div><dt>{t('Working Claim ID')}</dt><dd><code>{identity.claimId}</code></dd></div>
                : null}
              {detail.claimant?.customer_id
                ? <div><dt>{t('Claimant reference')}</dt><dd><code>{detail.claimant.customer_id}</code></dd></div>
                : null}
            </dl>
          </details>
        ) : null}
      </div>
      <div className="claim-heading__status">
        <span className="status-indicator"><Clock3 size={16} /> {t('Updated')} {formatDateTime(detail.updated_at)}</span>
      </div>
    </header>
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
  return <main className="empty-workspace"><div className="empty-workspace__symbol"><FileSearch size={28} /></div><p className="eyebrow">{t('Workbench')}</p><h1>{t('Select a Claim to begin.')}</h1><p>{t('The queue keeps the work order visible. Opening a Claim does not accept or change it.')}</p></main>
}

function ClaimUnavailable({ error, onRetry }) {
  const inaccessible = error?.status === 403
    || error?.status === 404
    || error?.code === 'ACCESS_DENIED'
    || error?.code === 'RESOURCE_NOT_FOUND'
  return (
    <main className="claim-state claim-state--error" role="alert">
      <AlertTriangle />
      <h2>{t(inaccessible ? 'This Claim is not available' : 'This Claim could not be opened')}</h2>
      <p>{inaccessible
        ? t('It may have been removed or is no longer visible to this staff account. Return to the queue and refresh current work.')
        : t('The Claim service did not return a usable projection. Retry without leaving this route.')}</p>
      <p>{failureReason(error)}</p>
      {failureReference(error) && <small>{failureReference(error)}</small>}
      {!inaccessible && <button className="button button--quiet" type="button" onClick={onRetry}>{t('Retry Claim')}</button>}
    </main>
  )
}

function ClaimSyncNotice({ loading, error, onRetry }) {
  return (
    <div className={`claim-sync-notice${error ? ' claim-sync-notice--error' : ''}`} role={error ? 'alert' : 'status'}>
      <div>
        <strong>{t(loading ? 'Refreshing this Claim' : 'Showing a saved Claim snapshot')}</strong>
        <p>{loading
          ? t('The current projection remains visible while the latest revision is loaded.')
          : t('The background refresh failed, so this Claim may be out of date. Review a refreshed projection before acting.')}</p>
        {error && <small>{failureReason(error)}</small>}
        {failureReference(error) && <small>{failureReference(error)}</small>}
      </div>
      {!loading && <button className="button button--quiet" type="button" onClick={onRetry}>{t('Refresh Claim')}</button>}
    </div>
  )
}

function ClaimFields({ resource, onRetry }) {
  return <ResourceBoundary resource={resource} onRetry={onRetry}><section className="resource-view"><header className="content-header"><div><p className="eyebrow">{t('Source-linked data')}</p><h2>{t('Claim information')}</h2></div><span>{t('{count} fields', { count: resource?.items?.length || 0 })}</span></header><FieldLedger items={resource?.items} /></section></ResourceBoundary>
}

function FieldLedger({ items = [] }) {
  if (!items.length) return <p className="empty-note">{t('No structured Claim Context is recorded.')}</p>
  return <dl className="fact-list">{items.map(({ code, field }) => <div key={code}><dt>{words(code.replaceAll('.', ' '))}</dt><dd><strong>{formatValue(field.value)}</strong><small>{words(field.status)} · {words(field.source)} · {words(field.needed_for)}</small></dd></div>)}</dl>
}

function formatValue(value) {
  if (value === null || value === undefined || value === '') return t('Not recorded')
  if (Array.isArray(value)) return value.join(', ')
  if (typeof value === 'object') return JSON.stringify(value)
  return String(value)
}
