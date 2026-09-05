import { ChevronDown, Filter, Inbox, Search } from 'lucide-react'
import { useState } from 'react'
import { formatDateTime, words } from '../format.js'
import { TagList } from './TagList.jsx'

export default function QueuePanel({ claims, loading, selectedId, filterMetadata, view, onView, workflowState, onWorkflowState, priority, onPriority, tagFilter, onTag, search, onSearch, onClearFilters, nextCursor, onLoadMore, onOpen }) {
  const hasSecondaryFilters = Boolean(workflowState || priority || tagFilter)
  const [filtersOpen, setFiltersOpen] = useState(hasSecondaryFilters)
  const hasActiveFilters = view !== 'all' || hasSecondaryFilters || search

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
        <span className="queue-count">{claims.length}</span>
      </header>
      <>
        <label className="queue-work-view">
          <span>Current work</span>
          <select value={view} onChange={(event) => onView(event.target.value)}>
            {filterMetadata.views.map((option) => <option value={option.value} key={option.value}>{option.label}</option>)}
          </select>
        </label>
        <label className="search-field">
          <Search size={16} aria-hidden="true" />
          <span className="sr-only">Search claims</span>
          <input
            type="search"
            placeholder="Search claims"
            value={search}
            onChange={(event) => onSearch(event.target.value)}
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
      </>
      <div className="queue-list" aria-live="polite" aria-busy={loading}>
        {loading && <p className="queue-state">Loading current work...</p>}
        {!loading && !claims.length && (
          <div className="queue-state">
            <Inbox size={20} aria-hidden="true" />
            <p>{hasActiveFilters ? 'No claims match the current filters.' : 'No claims are currently in this queue.'}</p>
            {hasActiveFilters && <button className="button button--quiet" type="button" onClick={clearFilters}>Clear filters</button>}
          </div>
        )}
        {!loading && claims.map((claim) => (
          <button
            className={`queue-item${selectedId === claim.claim_id ? ' is-selected' : ''}`}
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
              {words(claim.incident?.family)} · Status: {words(claim.workflow_state)}
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
        {!loading && nextCursor && <button className="queue-load-more" type="button" onClick={onLoadMore}>Load more Claims</button>}
      </div>
    </aside>
  )
}

function ownershipLabel(ownership) {
  if (ownership?.current_staff_access === 'primary') return 'Assigned to you'
  if (ownership?.primary_assignee?.display_name) return ownership.primary_assignee.display_name
  if (ownership?.primary_assignee?.staff_id) return ownership.primary_assignee.staff_id
  return words(ownership?.state || 'unassigned')
}
