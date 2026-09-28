import { useMemo, useState } from 'react'
import { FilterX } from 'lucide-react'
import { getToken, withQuery } from '../api.js'
import CollectionState from '../components/CollectionState.jsx'
import PageHeader from '../components/PageHeader.jsx'
import ResourceWorkspace from '../components/ResourceWorkspace.jsx'
import useAdminCollection from '../hooks/useAdminCollection.js'
import useSelection from '../hooks/useSelection.js'

export default function FeedbackPage() {
  const [staffId, setStaffId] = useState('')
  const [cursors, setCursors] = useState([''])
  const cursor = cursors.at(-1)
  const endpoint = useMemo(
    () => withQuery('/internal/v1/admin/feedback', {
      staff_id: staffId.trim(),
      cursor,
    }),
    [cursor, staffId],
  )
  const collection = useAdminCollection(endpoint, getToken())
  const [selected, setSelected] = useSelection(collection.items)

  return (
    <>
      <PageHeader
        title="Staff feedback"
        summary={`${collection.items.length} feedback record${collection.items.length === 1 ? '' : 's'} visible on this page`}
        onRefresh={collection.reload}
      />
      <div className="filter-grid">
        <label className="field">
          <span>Submitted by staff ID</span>
          <input
            value={staffId}
            onChange={(event) => {
              setStaffId(event.target.value)
              setCursors([''])
            }}
            placeholder="All staff"
          />
        </label>
        <button type="button" className="secondary" onClick={() => {
          setStaffId('')
          setCursors([''])
        }}>
          <FilterX aria-hidden="true" />Clear filter
        </button>
      </div>
      <CollectionState {...collection} label="Staff feedback">
        <>
          <ResourceWorkspace
            label="Staff feedback"
            items={collection.items}
            selected={selected}
            onSelect={setSelected}
            emptyMessage="No staff feedback matches this filter."
          />
          <nav className="pagination-controls" aria-label="Staff feedback pages">
            <button
              type="button"
              className="secondary"
              disabled={cursors.length === 1}
              onClick={() => setCursors((value) => value.slice(0, -1))}
            >
              Previous page
            </button>
            <span aria-live="polite">Page {cursors.length}</span>
            <button
              type="button"
              className="secondary"
              disabled={!collection.page.next_cursor}
              onClick={() => setCursors((value) => [...value, collection.page.next_cursor])}
            >
              Next page
            </button>
          </nav>
        </>
      </CollectionState>
    </>
  )
}
