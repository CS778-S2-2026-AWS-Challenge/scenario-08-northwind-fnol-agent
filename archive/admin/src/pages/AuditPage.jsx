import { useMemo, useState } from 'react'
import { FilterX } from 'lucide-react'
import { getToken, withQuery } from '../api.js'
import CollectionState from '../components/CollectionState.jsx'
import PageHeader from '../components/PageHeader.jsx'
import ResourceWorkspace from '../components/ResourceWorkspace.jsx'
import useAdminCollection from '../hooks/useAdminCollection.js'
import useSelection from '../hooks/useSelection.js'

export default function AuditPage() {
  const [filters, setFilters] = useState({ event_type: '', subject_type: '', actor_id: '', start_at: '', end_at: '' })
  const endpoint = useMemo(() => withQuery('/internal/v1/admin/audit', filters), [filters])
  const collection = useAdminCollection(endpoint, getToken())
  const [selected, setSelected] = useSelection(collection.items)
  const update = (key) => (event) => setFilters((value) => ({ ...value, [key]: event.target.value }))
  const clear = () => setFilters({ event_type: '', subject_type: '', actor_id: '', start_at: '', end_at: '' })

  return (
    <>
      <PageHeader title="Audit" summary={`${collection.items.length} administration-visible events`} onRefresh={collection.reload} />
      <div className="filter-grid">
        <label className="field"><span>Event type</span><input value={filters.event_type} onChange={update('event_type')} /></label>
        <label className="field"><span>Subject type</span><input value={filters.subject_type} onChange={update('subject_type')} /></label>
        <label className="field"><span>Actor ID</span><input value={filters.actor_id} onChange={update('actor_id')} /></label>
        <label className="field"><span>From</span><input type="datetime-local" value={filters.start_at} onChange={update('start_at')} /></label>
        <label className="field"><span>To</span><input type="datetime-local" value={filters.end_at} onChange={update('end_at')} /></label>
        <button type="button" className="secondary" onClick={clear}><FilterX aria-hidden="true" />Clear filters</button>
      </div>
      <CollectionState {...collection} label="Audit"><ResourceWorkspace label="Audit events" items={collection.items} selected={selected} onSelect={setSelected} emptyMessage="No events match these filters." /></CollectionState>
    </>
  )
}
