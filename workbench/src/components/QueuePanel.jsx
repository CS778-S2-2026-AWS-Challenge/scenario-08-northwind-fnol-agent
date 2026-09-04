import { Inbox, Search } from 'lucide-react'
import { useMemo, useState } from 'react'
import { formatDateTime, words } from '../format.js'
import { TagList } from './TagList.jsx'

const VIEWS = [
  ['all', 'All active work'],
  ['human_requests', 'Staff assistance'],
  ['urgent', 'Urgent'],
  ['awaiting_evidence', 'Awaiting evidence'],
]

const WORKFLOW_STATES = [
  ['', 'All statuses'],
  ['collecting', 'Collecting'],
  ['ready_for_next', 'Ready for next'],
  ['awaiting_evidence', 'Awaiting evidence'],
  ['professional_review', 'Professional review'],
  ['created', 'Created'],
]

const PRIORITIES = [
  ['', 'All priorities'],
  ['standard', 'Standard'],
  ['high', 'High'],
  ['urgent', 'Urgent'],
  ['immediate', 'Immediate'],
]

export default function QueuePanel({ claims, loading, selectedId, view, onView, workflowState, onWorkflowState, priority, onPriority, tagFilter, tags, onTag, nextCursor, onLoadMore, onOpen }) {
  const [query, setQuery] = useState('')
  const filtered = useMemo(() => {
    const normalized = query.trim().toLowerCase()
    if (!normalized) return claims
    return claims.filter((claim) =>
      [
        claim.claim_id,
        claim.display_reference,
        claim.claimant?.display_name,
        claim.incident?.family,
        claim.incident?.summary,
        claim.work_summary?.current_work_item?.requested_outcome,
      ]
        .filter(Boolean)
        .some((value) => String(value).toLowerCase().includes(normalized)),
    )
  }, [claims, query])
  const hasActiveFilters = view !== 'all' || workflowState || priority || tagFilter || query.trim()
  const showControls = loading || claims.length > 0 || hasActiveFilters

  function clearFilters() {
    setQuery('')
    onView('all')
    onWorkflowState('')
    onPriority('')
    onTag('')
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
      {showControls && <>
        <label className="search-field">
          <Search size={16} aria-hidden="true" />
          <span className="sr-only">Search claims</span>
          <input
            type="search"
            placeholder="Search claims"
            value={query}
            onChange={(event) => setQuery(event.target.value)}
          />
        </label>
        <div className="queue-filters" aria-label="Queue filters">
          <label><span className="sr-only">Work queue</span><select value={view} onChange={(event) => onView(event.target.value)}>
            {VIEWS.map(([value, label]) => <option value={value} key={value}>{label}</option>)}
          </select></label>
          <label><span className="sr-only">Claim status</span><select value={workflowState} onChange={(event) => onWorkflowState(event.target.value)}>
            {WORKFLOW_STATES.map(([value, label]) => <option value={value} key={value}>{label}</option>)}
          </select></label>
          <label><span className="sr-only">Claim priority</span><select value={priority} onChange={(event) => onPriority(event.target.value)}>
            {PRIORITIES.map(([value, label]) => <option value={value} key={value}>{label}</option>)}
          </select></label>
          <label><span className="sr-only">Staff tag</span><select value={tagFilter} onChange={(event) => onTag(event.target.value)}><option value="">All classifications</option>{tags.map((tag) => <option value={tag.code} key={tag.code}>{tag.label}</option>)}</select></label>
        </div>
      </>}
      <div className="queue-list" aria-live="polite" aria-busy={loading}>
        {loading && <p className="queue-state">Loading current work...</p>}
        {!loading && !filtered.length && (
          <div className="queue-state">
            <Inbox size={20} aria-hidden="true" />
            <p>{hasActiveFilters ? 'No claims match the current filters.' : 'No claims are currently in this queue.'}</p>
            {hasActiveFilters && <button className="button button--quiet" type="button" onClick={clearFilters}>Clear filters</button>}
          </div>
        )}
        {!loading && filtered.map((claim) => (
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
