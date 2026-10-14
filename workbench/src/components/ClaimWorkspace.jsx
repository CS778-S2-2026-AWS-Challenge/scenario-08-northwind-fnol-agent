import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { AlertTriangle, Check, Clipboard, Clock3, FileSearch, Info, X } from 'lucide-react'
import { claimIdentity } from '../claim-identity.js'
import { failureReason, failureReference } from '../failure.js'
import {
  formatClaimFieldValue,
  formatDateTime,
  isClaimFieldValuePresent,
  words,
} from '../format.js'
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

const FIELD_GROUPS = {
  claimant: { key: 'claimant', label: 'Claimant', order: 10 },
  policyholder: { key: 'claimant', label: 'Claimant', order: 10 },
  claim: { key: 'claim', label: 'Claim and policy', order: 20 },
  policy: { key: 'claim', label: 'Claim and policy', order: 20 },
  incident: { key: 'incident', label: 'Incident', order: 30 },
  authorities: { key: 'incident', label: 'Incident', order: 30 },
  police: { key: 'incident', label: 'Incident', order: 30 },
  theft: { key: 'incident', label: 'Incident', order: 30 },
  vehicle: { key: 'vehicle', label: 'Vehicle', order: 40 },
  property: { key: 'property', label: 'Property', order: 40 },
  loss: { key: 'loss', label: 'Loss', order: 50 },
  contents: { key: 'loss', label: 'Loss', order: 50 },
  driver: { key: 'people', label: 'People involved', order: 60 },
  parties: { key: 'people', label: 'People involved', order: 60 },
  other_party: { key: 'people', label: 'People involved', order: 60 },
  witness: { key: 'people', label: 'People involved', order: 60 },
}

const LONG_FIELD_NAME = /(?:description|summary|details|notes|narrative|wording|address|location|circumstances|context)/i

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
  const groups = groupClaimFields(resource?.items)
  const fieldCount = groups.reduce((total, group) => total + group.fields.length, 0)
  return (
    <ResourceBoundary resource={resource} onRetry={onRetry}>
      <section className="resource-view claim-information">
        <header className="content-header">
          <div><p className="eyebrow">{t('Source-linked data')}</p><h2>{t('Claim information')}</h2></div>
          <span>{fieldCountLabel(fieldCount)}</span>
        </header>
        <FieldLedger groups={groups} />
      </section>
    </ResourceBoundary>
  )
}

function FieldLedger({ groups = [] }) {
  if (!groups.length) return <p className="empty-note">{t('No structured Claim Context is recorded.')}</p>
  return (
    <div className="claim-field-groups">
      {groups.map((group) => {
        const headingId = `claim-field-group-${group.key.replace(/[^a-z0-9_-]/gi, '-')}`
        return (
          <section className="claim-field-group" aria-labelledby={headingId} key={group.key}>
            <header className="claim-field-group__header">
              <h3 id={headingId}>{t(group.label)}</h3>
            </header>
            <div className="claim-field-table-wrap">
              <table className="claim-field-table">
                <caption className="sr-only">{t(group.label)} — {t('Claim information')}</caption>
                <colgroup>
                  <col className="claim-field-table__label-column" />
                  <col />
                  <col className="claim-field-table__status-column" />
                </colgroup>
                <thead>
                  <tr>
                    <th scope="col">{t('Field')}</th>
                    <th scope="col">{t('Value')}</th>
                    <th scope="col">{t('Status')}</th>
                  </tr>
                </thead>
                <tbody>
                  {group.fields.map(({ code, field, label, wide }) => (
                    <tr className={`claim-field${wide ? ' claim-field--wide' : ''}`} data-field-code={code} key={code}>
                      <th className="claim-field__label" scope="row">{label}</th>
                      <td className="claim-field__content">
                        <span className="claim-field__value">{formatClaimFieldValue(code, field.value)}</span>
                      </td>
                      <td className="claim-field__metadata"><FieldMetadata field={field} label={label} /></td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>
        )
      })}
    </div>
  )
}

function FieldMetadata({ field, label }) {
  const sourceRefs = (field.source_refs || []).filter(isClaimFieldValuePresent)
  const status = field.status ? t(words(field.status)) : null
  const source = field.source ? t(words(field.source)) : null
  const neededFor = field.needed_for ? t(words(field.needed_for)) : null
  const statusClass = String(field.status || 'unknown').replace(/[^a-z0-9_-]/gi, '-')
  const hasDetails = source || neededFor || field.updated_at || sourceRefs.length

  if (!status && !hasDetails) return null
  return (
    <div className="claim-field__metadata-inner">
      {status && <span className={`claim-field__status claim-field__status--${statusClass}`}>{status}</span>}
      {hasDetails && <FieldDetailsPopover field={field} label={label} neededFor={neededFor} source={source} sourceRefs={sourceRefs} />}
    </div>
  )
}

function FieldDetailsPopover({ field, label, neededFor, source, sourceRefs }) {
  const [open, setOpen] = useState(false)
  const [copiedIndex, setCopiedIndex] = useState(null)
  const [position, setPosition] = useState(null)
  const triggerRef = useRef(null)
  const popoverRef = useRef(null)
  const titleId = useId()
  const popoverId = useId()
  const status = field.status ? t(words(field.status)) : t('Review before use')
  const statusClass = String(field.status || 'unknown').replace(/[^a-z0-9_-]/gi, '-')
  const guidance = fieldStatusGuidance(field.status)
  const sourceSummary = fieldSourceSummary(field.source, source)
  const workflowSummary = fieldWorkflowSummary(field.needed_for, neededFor)

  const closePopover = useCallback((restoreFocus = false) => {
    setOpen(false)
    setCopiedIndex(null)
    setPosition(null)
    if (restoreFocus) triggerRef.current?.focus()
  }, [])

  const updatePosition = useCallback(() => {
    const trigger = triggerRef.current
    const popover = popoverRef.current
    if (!trigger || !popover) return
    const rootStyles = window.getComputedStyle(document.documentElement)
    const margin = cssPixel(rootStyles, '--space-4', 16)
    const gap = cssPixel(rootStyles, '--space-2', 8)
    const maxWidth = cssPixel(rootStyles, '--size-select-menu-max', 320)
    const width = Math.min(maxWidth, window.innerWidth - (margin * 2))
    const triggerRect = trigger.getBoundingClientRect()
    const popoverHeight = popover.getBoundingClientRect().height
    const spaceBelow = window.innerHeight - triggerRect.bottom - margin - gap
    const spaceAbove = triggerRect.top - margin - gap
    const placement = spaceBelow < popoverHeight && spaceAbove > spaceBelow ? 'above' : 'below'
    const idealTop = placement === 'above'
      ? triggerRect.top - popoverHeight - gap
      : triggerRect.bottom + gap
    const top = clamp(idealTop, margin, window.innerHeight - popoverHeight - margin)
    const left = clamp(triggerRect.left, margin, window.innerWidth - width - margin)
    setPosition({ left, placement, top, width })
  }, [])

  useLayoutEffect(() => {
    if (!open) return undefined
    updatePosition()
    const frame = window.requestAnimationFrame(updatePosition)
    window.addEventListener('resize', updatePosition)
    window.addEventListener('scroll', updatePosition, true)
    return () => {
      window.cancelAnimationFrame(frame)
      window.removeEventListener('resize', updatePosition)
      window.removeEventListener('scroll', updatePosition, true)
    }
  }, [open, updatePosition])

  useEffect(() => {
    if (!open) return undefined
    const focusFrame = window.requestAnimationFrame(() => popoverRef.current?.focus())
    const onPointerDown = (event) => {
      if (!triggerRef.current?.contains(event.target) && !popoverRef.current?.contains(event.target)) closePopover()
    }
    const onKeyDown = (event) => {
      if (event.key === 'Escape') closePopover(true)
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKeyDown)
    return () => {
      window.cancelAnimationFrame(focusFrame)
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKeyDown)
    }
  }, [closePopover, open])

  async function copySourceReference(reference, index) {
    try {
      await navigator.clipboard.writeText(reference)
      setCopiedIndex(index)
    } catch {
      setCopiedIndex(null)
    }
  }

  const popover = open ? createPortal(
    <aside
      aria-labelledby={titleId}
      className="claim-field-popover"
      data-placement={position?.placement || 'below'}
      id={popoverId}
      ref={popoverRef}
      role="dialog"
      style={{
        left: `${position?.left || 0}px`,
        top: `${position?.top || 0}px`,
        visibility: position ? 'visible' : 'hidden',
        width: `${position?.width || 320}px`,
      }}
      tabIndex={-1}
    >
      <header className="claim-field-popover__header">
        <strong id={titleId}>{t('Review guidance for {label}', { label })}</strong>
        <button type="button" onClick={() => closePopover(true)} aria-label={t('Close details for {label}', { label })}>
          <X aria-hidden="true" size={14} />
        </button>
      </header>
      <div className="claim-field-popover__body">
        <section className={`claim-field-popover__guidance claim-field-popover__guidance--${statusClass}`}>
          <strong>{status}</strong>
          <p>{guidance}</p>
        </section>
        {(sourceSummary || workflowSummary || field.updated_at) && (
          <dl className="claim-field-popover__facts">
            {sourceSummary && <><dt>{t('Origin')}</dt><dd>{sourceSummary}</dd></>}
            {workflowSummary && <><dt>{t('Workflow use')}</dt><dd>{workflowSummary}</dd></>}
            {field.updated_at && <><dt>{t('Last updated')}</dt><dd><time dateTime={field.updated_at}>{formatDateTime(field.updated_at)}</time></dd></>}
          </dl>
        )}
        {sourceRefs.length > 0 && (
          <details className="claim-field-popover__technical">
            <summary>
              <span>{t('Technical sources')}</span>
              <small>{t('{count} references', { count: sourceRefs.length })}</small>
            </summary>
            <ul className="claim-field__source-list">
              {sourceRefs.map((reference, index) => (
                <li key={`${reference}-${index}`}>
                  <code title={reference}>{reference}</code>
                  <button
                    type="button"
                    onClick={() => copySourceReference(reference, index)}
                    aria-label={`${t(copiedIndex === index ? 'Copied source reference' : 'Copy source reference')}: ${reference}`}
                  >
                    {copiedIndex === index ? <Check aria-hidden="true" size={14} /> : <Clipboard aria-hidden="true" size={14} />}
                  </button>
                </li>
              ))}
            </ul>
          </details>
        )}
      </div>
    </aside>,
    document.body,
  ) : null

  return (
    <>
      <button
        aria-controls={popoverId}
        aria-expanded={open}
        aria-haspopup="dialog"
        aria-label={t('View details for {label}', { label })}
        className="claim-field__details-trigger"
        onClick={() => setOpen((current) => !current)}
        ref={triggerRef}
        type="button"
      >
        <Info aria-hidden="true" size={15} />
      </button>
      {popover}
    </>
  )
}

function fieldStatusGuidance(status) {
  const guidance = {
    confirmed: 'This value has been confirmed and can be used in the current review.',
    proposed: 'This value is proposed. Verify it against the Claim record before relying on it.',
    pending_generation: 'This value is still being prepared. Do not rely on it yet.',
    disputed: 'This value is disputed. Resolve the discrepancy before relying on it.',
    missing: 'This value is missing. Collect it before completing the relevant action.',
    unavailable: 'This value is unavailable. Check supporting records or request it if required.',
  }
  return t(guidance[status] || 'Review this value and its supporting context before relying on it.')
}

function fieldSourceSummary(sourceCode, sourceLabel) {
  if (!sourceCode) return null
  const summaries = {
    claimant: 'Provided directly by the claimant.',
    document: 'Taken from supporting evidence.',
    inference: 'Inferred from the available Claim information.',
    system: 'Generated from Northwind system records.',
    staff: 'Recorded by a staff member.',
    external_service: 'Returned by an external service.',
  }
  return t(summaries[sourceCode] || 'Recorded from {source}.', { source: sourceLabel })
}

function fieldWorkflowSummary(workflowCode, workflowLabel) {
  if (!workflowCode) return null
  const summaries = {
    current_action: 'Needed for the current review step.',
    later_action: 'Useful for a later Claim step.',
  }
  return t(summaries[workflowCode] || 'Used for {purpose}.', { purpose: workflowLabel })
}

function cssPixel(styles, property, fallback) {
  const value = Number.parseFloat(styles.getPropertyValue(property))
  return Number.isFinite(value) ? value : fallback
}

function clamp(value, minimum, maximum) {
  return Math.min(Math.max(value, minimum), Math.max(minimum, maximum))
}

function fieldCountLabel(count) {
  return count === 1 ? t('1 field') : t('{count} fields', { count })
}

function groupClaimFields(items = []) {
  const groups = new Map()

  items.forEach((item) => {
    if (!item?.field || !isClaimFieldValuePresent(item.field.value)) return
    const namespace = fieldNamespace(item.code)
    const definition = FIELD_GROUPS[namespace] || {
      key: namespace,
      label: words(namespace),
      order: 100,
    }
    const group = groups.get(definition.key) || { ...definition, fields: [] }
    const formattedValue = formatClaimFieldValue(item.code, item.field.value)
    group.fields.push({
      ...item,
      label: fieldLabel(item.code, definition.key),
      wide: isWideField(item.code, item.field.value, formattedValue),
    })
    groups.set(definition.key, group)
  })

  return [...groups.values()]
    .map((group) => ({ ...group, fields: group.fields.sort((left, right) => left.code.localeCompare(right.code)) }))
    .sort((left, right) => left.order - right.order || left.label.localeCompare(right.label))
}

function fieldNamespace(code = '') {
  return String(code).split('.')[0] || 'other'
}

function fieldLabel(code, groupKey) {
  const parts = String(code).split('.').filter(Boolean)
  if (parts.length <= 1) return t(words(parts[0] || 'Field'))
  const namespace = parts.shift()
  const descriptiveParts = namespace === groupKey ? parts : [namespace, ...parts]
  return t(words(descriptiveParts.join(' ')))
}

function isWideField(code, value, formattedValue) {
  if (Array.isArray(value) || (value !== null && typeof value === 'object')) return true
  if (typeof value !== 'string') return false
  return value.includes('\n') || LONG_FIELD_NAME.test(code) || formattedValue.length > 96
}
