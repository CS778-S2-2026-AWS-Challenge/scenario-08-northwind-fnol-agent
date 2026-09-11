import { ChevronDown, Filter, Inbox, Search } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'
import { failureReason, failureReference } from '../failure.js'
import { formatDateTime, words } from '../format.js'
import { TagList } from './TagList.jsx'

export default function QueuePanel({ claims, loading, error, onRetry, selectedId, filterMetadata, viewCounts, view, onView, workflowState, onWorkflowState, priority, onPriority, tagFilter, onTag, search, onSearch, additionalFiltersActive, onClearFilters, nextCursor, onLoadMore, onOpen }) {
  const hasSecondaryFilters = Boolean(workflowState || priority || tagFilter)
  const [filtersOpen, setFiltersOpen] = useState(hasSecondaryFilters)
  const searchInput = useRef(null)
  const searchTimer = useRef(null)
  const hasResultFilters = hasSecondaryFilters || search || additionalFiltersActive
  const hasActiveFilters = view !== 'all' || hasResultFilters
  const countByView = new Map(
    viewCounts?.status === 'available'
      ? viewCounts.items.map((item) => [item.view, item.count])
      : [],
  )
  const selectedCount = countByView.get(view)
  const noPublishedClaims = viewCounts?.status === 'available'
    && viewCounts.items.every((item) => item.count === 0)
  const trulyEmpty = !loading && !error && !hasActiveFilters && claims.length === 0 && noPublishedClaims
  const countLabel = selectedCount === undefined
    ? 'Total unavailable'
    : `${selectedCount} total${error ? ' · stale' : loading ? ' · updating' : ''}`
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
    <aside className="queue-panel" aria-label="Claim queue">
      <header className="queue-panel__header">
        <div>
          <p className="eyebrow">My work</p>
          <h2>Claim queue</h2>
        </div>
        <span className="queue-count">{countLabel}</span>
      </header>
      {!trulyEmpty && <>
        <label className="queue-work-view">
          <span>Current work</span>
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
        <label className="search-field">
          <Search size={16} aria-hidden="true" />
          <span className="sr-only">Search claims</span>
          <input
            type="search"
            placeholder="Search claims"
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
            Filters{hasSecondaryFilters ? ' applied' : ''}
            <ChevronDown size={16} aria-hidden="true" />
          </button>
          {filtersOpen && <div id="queue-secondary-filters" className="queue-filters" aria-label="Queue filters">
            <label><span className="sr-only">Claim status</span><select value={workflowState} onChange={(event) => onWorkflowState(event.target.value)}>
              <option value="">All statuses</option>
              {filterMetadata.workflow_states.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}
            </select></label>
            <label><span className="sr-only">Claim priority</span><select value={priority} onChange={(event) => onPriority(event.target.value)}>
              <option value="">All priorities</option>
              {filterMetadata.priorities.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}
            </select></label>
            <label><span className="sr-only">Staff tag</span><select value={tagFilter} onChange={(event) => onTag(event.target.value)}><option value="">All classifications</option>{filterMetadata.tags.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}</select></label>
          </div>}
        </div>
      </>}
      <div className="queue-list" aria-live="polite" aria-busy={loading}>
        {loading && <p className="queue-state" role="status">{claims.length ? 'Updating current work...' : 'Loading current work...'}</p>}
        {!loading && !error && viewCounts?.status === 'unavailable' && (
          <div className="queue-limitation" role="status">
            <span><strong>Queue totals unavailable.</strong> {viewCounts.limitation || 'The current rows are usable, but the service could not calculate totals.'}</span>
            <button className="button button--quiet" type="button" onClick={onRetry}>Refresh totals</button>
          </div>
        )}
        {!loading && error && (
          <div className="queue-state" role="alert">
            <strong>Claim queue unavailable</strong>
            <p>{claims.length
              ? 'The latest queue query could not be loaded. The Claims below are from the last successful load.'
              : 'Current work could not be loaded because the queue service did not return a usable projection.'}</p>
            <p>{failureReason(error)}</p>
            {failureReference(error) && <small>{failureReference(error)}</small>}
            <button className="button button--quiet" type="button" onClick={onRetry}>Retry</button>
          </div>
        )}
        {!loading && !error && !claims.length && (
          <div className="queue-state">
            <Inbox size={20} aria-hidden="true" />
            <p>{trulyEmpty
              ? 'No claims currently need active work.'
              : hasResultFilters
                ? 'No claims match the current filters.'
                : 'No claims are currently in this queue.'}</p>
            {hasResultFilters && <button className="button button--quiet" type="button" onClick={clearFilters}>Clear filters</button>}
          </div>
        )}
        {claims.map((claim) => (
          <button
            className={`queue-item${selectedId === claim.claim_id ? ' is-selected' : ''}${error ? ' is-stale' : ''}`}
            type="button"
            key={claim.claim_id}
            onClick={() => onOpen(claim)}
          >
            <span className="queue-item__topline">
              <strong>{claim.display_reference || claim.claim_id}</strong>
              <span className={`priority priority--${claim.priority_projection?.level}`}>
                Priority: {words(claim.priority_projection?.level)}
              </span>
            </span>
            <span className="queue-item__incident">
              {words(claim.incident?.family)} · {claim.terminal_disposition
                ? `Terminal: ${words(claim.terminal_disposition.value)} · Retained status: ${words(claim.workflow_state)}`
                : `Status: ${words(claim.workflow_state)}`}
            </span>
            <span className="queue-item__summary">
              {claim.work_summary?.current_work_item?.requested_outcome || claim.incident?.summary}
            </span>
            <TagList tags={claim.tags} limit={3} />
            <span className="queue-item__meta">
              <span>{ownershipLabel(claim.ownership)}</span>
              <time dateTime={claim.updated_at}>{formatDateTime(claim.updated_at)}</time>
            </span>
          </button>
        ))}
        {!loading && !error && nextCursor && <button className="queue-load-more" type="button" onClick={onLoadMore}>Load more Claims</button>}
      </div>
    </aside>
  )
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
  if (ownership?.current_staff_access === 'primary') return 'Assigned to you'
  if (ownership?.primary_assignee?.display_name) return ownership.primary_assignee.display_name
  if (ownership?.primary_assignee?.staff_id) return ownership.primary_assignee.staff_id
  return words(ownership?.state || 'unassigned')
}
