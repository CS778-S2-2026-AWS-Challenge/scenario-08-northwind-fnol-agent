import { useRef } from 'react'
import {
  DOCUMENT_STATUS_DETAILS,
  DOCUMENT_STATUS_ORDER,
  documentAttentionCount,
  documentName,
  documentReason,
  documentStatus,
} from '../claimDocumentProjection.js'

function UploadAction({ disabled, item, onUpload }) {
  const inputRef = useRef(null)
  const name = documentName(item)

  return (
    <>
      <input
        ref={inputRef}
        hidden
        type="file"
        accept="image/jpeg,image/png,application/pdf"
        onChange={(event) => {
          const file = event.target.files?.[0]
          if (file) onUpload(item, file)
          event.target.value = ''
        }}
      />
      <button
        className="document-row-action"
        type="button"
        disabled={disabled}
        aria-label={`Upload ${name}`}
        onClick={() => inputRef.current?.click()}
      >
        Upload
      </button>
    </>
  )
}

export default function ClaimDocuments({
  items,
  loadStatus,
  busy = false,
  onUpload,
  onView,
}) {
  if (loadStatus === 'loading' || loadStatus === 'idle') {
    return <p className="document-panel-state" role="status">Checking document guidance…</p>
  }

  if (loadStatus === 'error') {
    return (
      <div className="document-panel-state is-error" role="alert">
        <strong>Document guidance is temporarily unavailable.</strong>
        <span>Your claim is still saved. Continue in the conversation and try again later.</span>
      </div>
    )
  }

  const sortedItems = [...items].sort((left, right) => {
    const statusDifference = DOCUMENT_STATUS_ORDER[documentStatus(left)]
      - DOCUMENT_STATUS_ORDER[documentStatus(right)]
    return statusDifference || documentName(left).localeCompare(documentName(right))
  })
  const attentionCount = documentAttentionCount(sortedItems)

  return (
    <section className="claim-documents" aria-labelledby="claim-documents-title">
      <div className="document-attention-summary" role="status">
        <span aria-hidden="true">!</span>
        <strong id="claim-documents-title">
          {attentionCount} {attentionCount === 1 ? 'item needs' : 'items need'} your attention
        </strong>
      </div>

      {sortedItems.length === 0 ? (
        <div className="document-panel-state">
          <strong>No claim-specific documents are recorded yet.</strong>
          <span>Any materials Northwind identifies will appear here.</span>
        </div>
      ) : (
        <ul className="claim-document-list">
          {sortedItems.map((item) => {
            const status = documentStatus(item)
            const statusDetails = DOCUMENT_STATUS_DETAILS[status]
            const name = documentName(item)
            return (
              <li className="claim-document-row" key={item.evidence_id}>
                <div className="document-row-main">
                  <strong>{name}</strong>
                  <span>{documentReason(item, status)}</span>
                </div>
                <span className={`document-status document-status-${status}`}>
                  <span aria-hidden="true">{statusDetails.symbol}</span>
                  {statusDetails.label}
                </span>
                <div className="document-row-action-slot">
                  {['required', 'recommended'].includes(status) && onUpload ? (
                    <UploadAction disabled={busy} item={item} onUpload={onUpload} />
                  ) : status === 'received' && onView ? (
                    <button
                      className="document-row-action"
                      type="button"
                      aria-label={`View ${name}`}
                      onClick={() => onView(item)}
                    >
                      View
                    </button>
                  ) : (
                    <span className="document-row-next-step">
                      {status === 'later' ? 'Add later' : 'No action needed'}
                    </span>
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}
    </section>
  )
}
