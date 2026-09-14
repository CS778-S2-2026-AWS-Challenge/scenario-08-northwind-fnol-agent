import { useEffect, useRef, useState } from 'react'

import { getClaimEvidence, listEvidenceHistory } from '../api.js'
import { formatDateTime, formatIdentifierLabel } from '../formatters.js'

const FILE_STATUS_LABELS = {
  uploaded: 'Uploaded',
  processing: 'Processing',
  ready: 'Ready',
  failed: 'Processing failed',
}

const SOURCE_LABELS = {
  claimant: 'Uploaded by you',
}

const PROVENANCE_LABELS = {
  claimant_upload: 'Uploaded by you',
}

function errorState(error) {
  if (error?.status === 401 || error?.status === 403) return 'denied'
  if (error?.status === 503 || error?.code === 'NETWORK_ERROR') return 'unavailable'
  return 'failed'
}

function formatFileSize(value) {
  if (!Number.isFinite(value)) return null
  if (value < 1024) return `${value} B`
  if (value < 1024 * 1024) return `${Math.round(value / 1024)} KB`
  return `${(value / (1024 * 1024)).toFixed(1)} MB`
}

async function requestEvidenceHistory({ claimId, cursor, signal }) {
  if (!claimId) return listEvidenceHistory({ cursor, signal })
  const response = await getClaimEvidence(claimId, { signal })
  return {
    items: response.items.map((item) => ({ ...item, source_claim_id: claimId })),
    page: { next_cursor: null },
  }
}

function EvidenceHistoryItem({ accountScoped, item, currentClaimId }) {
  const statusLabel = FILE_STATUS_LABELS[item.file_status] || item.file_status || item.status
  const metadata = [item.media_type, formatFileSize(item.size_bytes)].filter(Boolean)
  const provenanceLabel = item.provenance_summary
    ?.map((entry) => PROVENANCE_LABELS[entry])
    .find(Boolean) || SOURCE_LABELS[item.source] || 'Source recorded by Northwind'

  return (
    <li className="evidence-history-item">
      <div className="evidence-history-heading">
        <div>
          <strong>{item.original_filename || formatIdentifierLabel(item.kind)}</strong>
          <span>{metadata.join(' · ') || 'File metadata unavailable'}</span>
        </div>
        <span className={`evidence-status evidence-status-${item.file_status || 'unknown'}`}>
          <span aria-hidden="true">●</span> {statusLabel}
        </span>
      </div>
      <dl className="evidence-history-details">
        {accountScoped && (
          <div>
            <dt>Source claim</dt>
            <dd>{item.source_claim_id}{item.source_claim_id === currentClaimId ? ' · Current claim' : ''}</dd>
          </div>
        )}
        <div>
          <dt>Added</dt>
          <dd>{formatDateTime(item.created_at)}</dd>
        </div>
        <div>
          <dt>Last updated</dt>
          <dd>{formatDateTime(item.updated_at)}</dd>
        </div>
        <div>
          <dt>Provenance</dt>
          <dd>{provenanceLabel}</dd>
        </div>
        {accountScoped && (
          <>
            <div>
              <dt>Reuse</dt>
              <dd>{item.can_reuse ? 'Eligible' : 'Not eligible'}</dd>
            </div>
            <div>
              <dt>Removal</dt>
              <dd>{item.can_remove ? 'Permitted' : 'Not available for this item'}</dd>
            </div>
          </>
        )}
      </dl>
    </li>
  )
}

export default function EvidenceHistory({ claimId = null, currentClaimId = null }) {
  const [items, setItems] = useState([])
  const [nextCursor, setNextCursor] = useState(null)
  const [viewState, setViewState] = useState('loading')
  const [message, setMessage] = useState('')
  const controllerRef = useRef(null)
  const itemsRef = useRef([])

  function replaceItems(nextItems) {
    itemsRef.current = nextItems
    setItems(nextItems)
  }

  async function load({ cursor = null, append = false } = {}) {
    controllerRef.current?.abort()
    const controller = new AbortController()
    controllerRef.current = controller
    setMessage('')
    setViewState(append ? 'loading-more' : itemsRef.current.length ? 'refreshing' : 'loading')

    try {
      const response = await requestEvidenceHistory({ claimId, cursor, signal: controller.signal })
      if (controller.signal.aborted) return
      const nextItems = append
        ? [...itemsRef.current, ...response.items.filter((candidate) => (
          !itemsRef.current.some((item) => item.evidence_id === candidate.evidence_id)
        ))]
        : response.items
      replaceItems(nextItems)
      setNextCursor(response.page?.next_cursor || null)
      setViewState(nextItems.length ? 'ready' : 'empty')
    } catch (error) {
      if (error?.name === 'AbortError') return
      if (itemsRef.current.length) {
        setViewState('stale')
        setMessage('We could not refresh this history because the service did not respond. The results below may be out of date. Try again before acting on them.')
      } else {
        setViewState(errorState(error))
        setMessage(error?.message || 'The evidence service could not load this history.')
      }
    }
  }

  useEffect(() => {
    const controller = new AbortController()
    controllerRef.current = controller
    requestEvidenceHistory({ claimId, signal: controller.signal })
      .then((response) => {
        if (controller.signal.aborted) return
        itemsRef.current = response.items
        setItems(response.items)
        setNextCursor(response.page?.next_cursor || null)
        setViewState(response.items.length ? 'ready' : 'empty')
      })
      .catch((error) => {
        if (error?.name === 'AbortError') return
        setViewState(errorState(error))
        setMessage(error?.message || 'The evidence service could not load this history.')
      })
    return () => controller.abort()
  }, [claimId])

  if (viewState === 'loading') {
    return <p className="evidence-history-state" role="status">Loading your evidence history…</p>
  }

  if (viewState === 'empty') {
    return (
      <section className="evidence-history-state" aria-labelledby="evidence-history-empty-title">
        <h2 id="evidence-history-empty-title">No uploaded evidence yet</h2>
        <p>Files that finish uploading to your claims will appear here. You can return to your conversation to add supporting material.</p>
      </section>
    )
  }

  if (viewState === 'denied') {
    return (
      <section className="evidence-history-state is-error" role="alert">
        <h2>Evidence history is not available for this account</h2>
        <p>{message} Your session does not have permission to read this history. Return to your account and sign in again.</p>
      </section>
    )
  }

  if (viewState === 'unavailable' || viewState === 'failed') {
    return (
      <section className="evidence-history-state is-error" role="alert">
        <h2>{viewState === 'unavailable' ? 'Evidence history is temporarily unavailable' : 'Evidence history could not be loaded'}</h2>
        <p>{message} Your files have not been changed.</p>
        <button className="secondary-button" type="button" onClick={() => load()}>Try again</button>
      </section>
    )
  }

  return (
    <section className="evidence-history-results" aria-labelledby="evidence-history-results-title">
      <div className="evidence-history-toolbar">
        <div>
          <h2 id="evidence-history-results-title">{claimId ? 'Evidence for this Claim' : 'Uploaded evidence'}</h2>
          <p>{items.length} {items.length === 1 ? 'item' : 'items'} {claimId ? 'recorded for this Claim' : 'from your Claims'}</p>
        </div>
        <button className="secondary-button" type="button" onClick={() => load()} disabled={viewState === 'refreshing'}>
          {viewState === 'refreshing' ? 'Refreshing…' : 'Refresh'}
        </button>
      </div>
      {viewState === 'stale' && (
        <div className="evidence-history-stale" role="status">
          <strong>Showing earlier results</strong>
          <p>{message}</p>
        </div>
      )}
      <ul className="evidence-history-list">
        {items.map((item) => (
          <EvidenceHistoryItem
            accountScoped={!claimId}
            key={item.evidence_id}
            item={item}
            currentClaimId={currentClaimId}
          />
        ))}
      </ul>
      {nextCursor && (
        <button className="secondary-button" type="button" onClick={() => load({ cursor: nextCursor, append: true })} disabled={viewState === 'loading-more'}>
          {viewState === 'loading-more' ? 'Loading more…' : 'Load more'}
        </button>
      )}
    </section>
  )
}
