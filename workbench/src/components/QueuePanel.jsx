import { ChevronDown, Clock3, Filter, Inbox, Search } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { claimIdentity } from '../claim-identity.js'
import { failureReason, failureReference } from '../failure.js'
import { formatDateTime, formatQueueDateTime, words } from '../format.js'
import { translate as t } from '../i18n.js'

export default function QueuePanel({ queueKind = 'legacy', claims, loading, error, onRetry, selectedId, filterMetadata, viewCounts, activeClaimCounts, view, onView, activeStatus = '', onActiveStatus, workflowState, onWorkflowState, priority, onPriority, tagFilter, onTag, search, onSearch, additionalFiltersActive, onClearFilters, nextCursor, onLoadMore, onOpen }) {
  const isActiveQueue = queueKind === 'active'
  const isDraftQueue = queueKind === 'drafts'
  const isSubmittedQueue = queueKind === 'submitted'
  const hasSecondaryFilters = Boolean(activeStatus || workflowState || priority || tagFilter)
  const [filtersOpen, setFiltersOpen] = useState(hasSecondaryFilters)
  const searchInput = useRef(null)
  const searchTimer = useRef(null)
  const hasResultFilters = hasSecondaryFilters || search || additionalFiltersActive
  const hasActiveFilters = queueKind === 'legacy' ? view !== 'all' || hasResultFilters : hasResultFilters
  const countByView = new Map(
    viewCounts?.status === 'available'
      ? viewCounts.items.map((item) => [item.view, item.count])
      : [],
  )
  const activeCountByStatus = new Map(
    activeClaimCounts?.status === 'available'
      ? activeClaimCounts.items.map((item) => [item.status, item.count])
      : [],
  )
  const selectedCount = isActiveQueue
    ? activeStatus
      ? activeCountByStatus.get(activeStatus)
      : activeClaimCounts?.total
    : countByView.get(view)
  const noPublishedClaims = viewCounts?.status === 'available'
    && viewCounts.items.every((item) => item.count === 0)
  const countProjection = isActiveQueue ? activeClaimCounts : viewCounts
  const selectedQueueEmpty = countProjection?.status === 'available' && selectedCount === 0
  const trulyEmpty = !loading
    && !error
    && !hasActiveFilters
    && claims.length === 0
    && (queueKind === 'legacy' ? noPublishedClaims : selectedQueueEmpty)
  const countLabel = selectedCount === undefined || selectedCount === null
    ? t('Total unavailable')
    : t(error ? '{count} total · stale' : loading ? '{count} total · updating' : '{count} total', { count: selectedCount })
  const viewGroups = groupViews(filterMetadata.views)
  useEffect(() => {
    window.clearTimeout(searchTimer.current)
    if (searchInput.current && searchInput.current.value !== search) {
      searchInput.current.value = search
    }
    return () => window.clearTimeout(searchTimer.current)
  }, [search])

  function changeSearch(event) {
    const value = event.target.value
    window.clearTimeout(searchTimer.current)
    searchTimer.current = window.setTimeout(() => onSearch(value), 275)
  }

  function clearFilters() {
    onClearFilters()
  }

  return (
    <aside
      className={`queue-panel${isActiveQueue || isDraftQueue || queueKind === 'legacy' ? ' queue-panel--five-rows' : ''}`}
      aria-label={t('Claim queue')}
    >
      <header className="queue-panel__header">
        <div>
          <p className="eyebrow">{t('My work')}</p>
          <h2>{t(isActiveQueue ? 'Active claims' : isDraftQueue ? 'Draft claims' : isSubmittedQueue ? 'Submitted claims' : 'Claim queue')}</h2>
        </div>
        <span className="queue-count">{countLabel}</span>
      </header>
      {isDraftQueue && (
        <p className="queue-context-note">
          {t('Customers are still completing these claims. They have not entered the formal work queue.')}
        </p>
      )}
      {isActiveQueue && (
        <p className="queue-context-note">
          {t('Claims needing continued attention or staff action.')}
        </p>
      )}
      {!trulyEmpty && <>
        {queueKind === 'legacy' && (
          <label className="queue-work-view">
            <span>{t('Current work')}</span>
            <select value={view} onChange={(event) => onView(event.target.value)}>
              {viewGroups.map(({ group, options }) => (
                <optgroup label={words(group)} key={group}>
                  {options.map((option) => (
                    <option value={option.value} key={option.value}>
                      {option.label}{countByView.has(option.value) ? ` (${countByView.get(option.value)})` : ''}
                    </option>
                  ))}
                </optgroup>
              ))}
            </select>
          </label>
        )}
        <label className="search-field">
          <Search size={16} aria-hidden="true" />
          <span className="sr-only">{t('Search claims')}</span>
          <input
            type="search"
            placeholder={t('Search claims')}
            defaultValue={search}
            ref={searchInput}
            onChange={changeSearch}
          />
        </label>
        <div className="queue-filter-disclosure">
          <button
            className="queue-filter-disclosure__toggle"
            type="button"
            aria-expanded={filtersOpen}
            aria-controls="queue-secondary-filters"
            onClick={() => setFiltersOpen((open) => !open)}
          >
            <Filter size={16} aria-hidden="true" />
            {t(hasSecondaryFilters ? 'Filters applied' : 'Filters')}
            <ChevronDown size={16} aria-hidden="true" />
          </button>
          {filtersOpen && <div id="queue-secondary-filters" className="queue-filters" aria-label={t('Queue filters')}>
            <label><span className="sr-only">{t('Claim status')}</span><select value={isActiveQueue ? activeStatus : workflowState} onChange={(event) => isActiveQueue ? onActiveStatus(event.target.value) : onWorkflowState(event.target.value)}>
              <option value="">{t(isActiveQueue ? 'All Active claim statuses' : 'All statuses')}</option>
              {(isActiveQueue ? filterMetadata.active_claim_statuses || [] : filterMetadata.workflow_states).map((option) => <option value={option.value} key={option.value}>{t(option.label)}</option>)}
            </select></label>
            <label><span className="sr-only">{t('Claim priority')}</span><select value={priority} onChange={(event) => onPriority(event.target.value)}>
              <option value="">{t('All priorities')}</option>
              {filterMetadata.priorities.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}
            </select></label>
            <label><span className="sr-only">{t('Staff tag')}</span><select value={tagFilter} onChange={(event) => onTag(event.target.value)}><option value="">{t('All classifications')}</option>{filterMetadata.tags.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}</select></label>
          </div>}
        </div>
      </>}
      <div className="queue-list" aria-live="polite" aria-busy={loading}>
        {loading && <p className="queue-state" role="status">{t(claims.length ? 'Updating current work...' : 'Loading current work...')}</p>}
        {!loading && !error && countProjection?.status === 'unavailable' && (
          <div className="queue-limitation" role="status">
            <span><strong>{t('Queue totals unavailable.')}</strong> {countProjection.limitation || t('The current rows are usable, but the service could not calculate totals.')}</span>
            <button className="button button--quiet" type="button" onClick={onRetry}>{t('Refresh totals')}</button>
          </div>
        )}
        {!loading && error && (
          <div className="queue-state" role="alert">
            <strong>{t('Claim queue unavailable')}</strong>
            <p>{claims.length
              ? t('The latest queue query could not be loaded. The Claims below are from the last successful load.')
              : t('Current work could not be loaded because the queue service did not return a usable projection.')}</p>
            <p>{failureReason(error)}</p>
            {failureReference(error) && <small>{failureReference(error)}</small>}
            <button className="button button--quiet" type="button" onClick={onRetry}>{t('Retry')}</button>
          </div>
        )}
        {!loading && !error && !claims.length && (
          <div className="queue-state">
            <Inbox size={20} aria-hidden="true" />
            <p>{trulyEmpty
              ? t(isDraftQueue
                ? 'No Draft claims are waiting for a customer to finish.'
                : isActiveQueue
                  ? 'No Active claims currently need attention.'
                : isSubmittedQueue
                  ? 'No submitted claims currently need work.'
                  : 'No claims currently need active work.')
              : hasResultFilters
                ? t('No claims match the current filters.')
                : t('No claims are currently in this queue.')}</p>
            {hasResultFilters && <button className="button button--quiet" type="button" onClick={clearFilters}>{t('Clear filters')}</button>}
          </div>
        )}
        {claims.map((claim) => {
          const identity = claimIdentity(claim)
          const reason = queueReason(claim)
          const updatedLabel = t('Updated {date}', { date: formatDateTime(claim.updated_at) })
          const claimantActivityAt = draftClaimantActivityAt(claim)
          const claimantActivityLabel = claimantActivityAt
            ? t('Last customer activity {date}', { date: formatDateTime(claimantActivityAt) })
            : t('Customer activity unavailable')
          return (
            <button
              className={`queue-item${selectedId === claim.claim_id ? ' is-selected' : ''}${error ? ' is-stale' : ''}`}
              type="button"
              key={claim.claim_id}
              aria-current={selectedId === claim.claim_id ? 'true' : undefined}
              onClick={() => onOpen(claim)}
            >
              <span className="queue-item__topline">
                <strong title={identity.cardTitle}>{identity.cardTitle}</strong>
                {isDraftQueue ? (
                  <span className="draft-status">{t('Draft')}</span>
                ) : isActiveQueue ? (
                  <span className={`active-claim-status active-claim-status--${claim.active_claim?.status}`}>
                    {t(activeClaimStatusLabel(claim.active_claim?.status))}
                  </span>
                ) : (
                  <span
                    className={`priority priority--${claim.priority_projection?.level}`}
                    aria-label={t('Priority {priority}', { priority: words(claim.priority_projection?.level) })}
                  >
                    {words(claim.priority_projection?.level)}
                  </span>
                )}
              </span>
              <span className="queue-item__status">
                {isDraftQueue
                  ? `${t('Not submitted')} · ${claimTypeLabel(claim)}`
                  : isActiveQueue
                    ? `${activeCustomerLabel(claim, identity)} · ${ownershipLabel(claim.ownership)}`
                  : isSubmittedQueue
                    ? `${t('Submitted')} · ${claimTypeLabel(claim)} · ${ownershipLabel(claim.ownership)}`
                    : `${queueStatus(claim)} · ${ownershipLabel(claim.ownership)}`}
              </span>
              {isDraftQueue ? (
                <span className="queue-item__reason queue-item__activity">
                  <Clock3 size={14} aria-hidden="true" />
                  {claimantActivityLabel}
                </span>
              ) : reason !== identity.cardTitle ? <span className="queue-item__reason">{reason}</span> : null}
              <span className="queue-item__meta">
                <span className="queue-item__reference">{identity.referenceLabel}</span>
                {!isDraftQueue && <time dateTime={claim.updated_at} aria-label={updatedLabel} title={updatedLabel}>{formatQueueDateTime(claim.updated_at)}</time>}
              </span>
            </button>
          )
        })}
        {!loading && !error && nextCursor && <button className="queue-load-more" type="button" onClick={onLoadMore}>{t('Load more Claims')}</button>}
      </div>
    </aside>
  )
}

function claimTypeLabel(claim) {
  return claim.incident?.family ? words(claim.incident.family) : t('Type not confirmed')
}

function activeClaimStatusLabel(status) {
  return {
    urgent: 'Urgent',
    human_assistance: 'Human assistance',
    professional_review: 'Professional review',
    pending_creation: 'Pending creation',
  }[status] || words(status)
}

function activeCustomerLabel(claim, identity) {
  if (identity.claimantName) return identity.claimantName
  if (claim.claimant?.customer_id) {
    return t('Customer {customerId}', { customerId: claim.claimant.customer_id })
  }
  return t('Customer unavailable')
}

function queueStatus(claim) {
  const claimType = claimTypeLabel(claim)

  if (claim.terminal_disposition) {
    return `${words(claim.terminal_disposition.value)} · ${claimType} · ${words(claim.workflow_state)} retained`
  }

  return `${words(claim.workflow_state)} · ${claimType}`
}

function queueReason(claim) {
  const workSummary = claim.work_summary || {}
  const priorityReason = claim.priority_projection?.reasons?.[0]?.summary

  if (priorityReason) return priorityReason
  if (workSummary.primary_blocker) return `${t('Needs attention')} · ${workSummary.primary_blocker}`
  if (workSummary.current_work_item?.requested_outcome) {
    return workSummary.current_work_item.requested_outcome
  }
  if (workSummary.incomplete_context?.resume_point) {
    return `${t('Incomplete')} · ${t('Resume')} ${words(workSummary.incomplete_context.resume_point)}`
  }
  if (workSummary.incomplete_context) return t('Incomplete claim')
  if (workSummary.external_wait_count > 0) {
    return t(workSummary.external_wait_count === 1
      ? 'Waiting on {count} external service'
      : 'Waiting on {count} external services', { count: workSummary.external_wait_count })
  }

  return claim.incident?.summary || t('No further context available.')
}

function draftClaimantActivityAt(claim) {
  return claim.work_summary?.last_claimant_activity_at
    || claim.work_summary?.incomplete_context?.last_meaningful_activity_at
    || null
}

function groupViews(views) {
  const groups = []
  for (const option of views) {
    const existing = groups.find((entry) => entry.group === option.group)
    if (existing) existing.options.push(option)
    else groups.push({ group: option.group, options: [option] })
  }
  return groups
}

function ownershipLabel(ownership) {
  if (ownership?.current_staff_access === 'primary') return t('Assigned to you')
  if (ownership?.primary_assignee?.display_name) return ownership.primary_assignee.display_name
  if (ownership?.primary_assignee?.staff_id) return ownership.primary_assignee.staff_id
  return words(ownership?.state || 'unassigned')
}
