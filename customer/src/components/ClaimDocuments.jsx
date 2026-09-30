import { useId, useRef, useState } from 'react'
import {
  DOCUMENT_STATUS_DETAILS,
  DOCUMENT_STATUS_ORDER,
  DOCUMENT_UPLOAD_CONSTRAINTS,
  documentIsPhoto,
  documentIsProvided,
  documentMediaTypeLabel,
  documentProvidedCount,
  documentReason,
  documentRequirement,
  documentStatus,
  documentTaskDescription,
  documentTaskTitle,
  documentUploadLabel,
} from '../claimDocumentProjection.js'

function CameraIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M4 7.5h3l1.4-2h7.2l1.4 2h3a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2Z" />
      <circle cx="12" cy="13" r="3.5" />
    </svg>
  )
}

function FileIcon({ success = false }) {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M6 2.75h7l5 5v13.5H6z" />
      <path d="M13 2.75v5h5" />
      {success && <path d="m8.5 15 2 2 4.5-4.5" />}
    </svg>
  )
}

function UploadIcon() {
  return (
    <svg viewBox="0 0 24 24" aria-hidden="true">
      <path d="M12 16V4m0 0L7.5 8.5M12 4l4.5 4.5" />
      <path d="M4 15v4a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-4" />
    </svg>
  )
}

function taskFileState(item, localState) {
  if (localState?.status === 'uploading') {
    return {
      kind: 'uploading',
      filename: localState.filename,
      mediaType: localState.mediaType,
      label: 'Uploading…',
      message: 'Keep this page open while Northwind receives your file.',
    }
  }
  if (localState?.status === 'error') {
    return {
      kind: 'error',
      filename: localState.filename,
      mediaType: localState.mediaType,
      label: localState.label,
      message: localState.message,
    }
  }
  if (item.file_status === 'failed') {
    return {
      kind: 'error',
      filename: item.original_filename,
      mediaType: item.media_type,
      label: 'Upload failed',
      message: documentReason(item, documentStatus(item)),
    }
  }
  if (item.status === 'invalid') {
    return {
      kind: 'error',
      filename: item.original_filename,
      mediaType: item.media_type,
      label: 'File not accepted',
      message: documentReason(item, documentStatus(item)),
    }
  }
  if (['uploading', 'uploaded', 'processing'].includes(item.file_status)) {
    return {
      kind: 'uploading',
      filename: item.original_filename,
      mediaType: item.media_type,
      label: item.file_status === 'processing' ? 'Checking file…' : 'Uploading…',
      message: item.file_status === 'processing'
        ? 'Northwind has received this file and is checking that it can be used.'
        : 'Keep this page open while Northwind receives your file.',
    }
  }
  if (documentIsProvided(item)) {
    return {
      kind: 'success',
      filename: item.original_filename,
      mediaType: item.media_type,
      label: 'Upload complete',
      message: 'Uploaded successfully',
    }
  }
  return null
}

function DocumentFileState({ state }) {
  if (!state) return null
  const isError = state.kind === 'error'
  return (
    <div
      className={`document-file-state is-${state.kind}`}
      {...(isError ? { role: 'alert' } : { role: 'status', 'aria-live': 'polite' })}
    >
      <span className="document-file-icon"><FileIcon success={state.kind === 'success'} /></span>
      <span className="document-file-copy">
        <strong>{state.filename || 'Selected file'}</strong>
        <span>{documentMediaTypeLabel(state.mediaType)} · {state.label}</span>
        <small>{state.message}</small>
      </span>
    </div>
  )
}

function validationError(file) {
  if (!DOCUMENT_UPLOAD_CONSTRAINTS.allowedMediaTypes.includes(file.type)) {
    return {
      label: 'Unsupported file format',
      message: 'This file type cannot be uploaded. Choose a JPG, PNG or PDF file and try again.',
    }
  }
  if (file.size > DOCUMENT_UPLOAD_CONSTRAINTS.maxSizeBytes) {
    return {
      label: 'File is too large',
      message: 'This file is larger than 10 MB. Choose a smaller JPG, PNG or PDF file and try again.',
    }
  }
  return null
}

function DocumentTaskCard({ emphasized, item, onUpload }) {
  const inputRef = useRef(null)
  const tipsId = useId()
  const [tipsOpen, setTipsOpen] = useState(false)
  const [localState, setLocalState] = useState(null)
  const lifecycle = documentStatus(item)
  const requirement = documentRequirement(item)
  const fileState = taskFileState(item, localState)
  const isUploading = fileState?.kind === 'uploading'
  const canReplace = fileState?.kind === 'error'
  const canUpload = Boolean(onUpload) && !fileState
  const showFilePicker = canUpload || canReplace
  const uploadLabel = documentUploadLabel(item, canReplace)
  const isPhoto = documentIsPhoto(item)
  const statusDetails = DOCUMENT_STATUS_DETAILS[
    lifecycle === 'later' ? 'later' : requirement
  ]

  async function handleFile(file) {
    const invalid = validationError(file)
    if (invalid) {
      setLocalState({
        status: 'error',
        filename: file.name,
        mediaType: file.type,
        ...invalid,
      })
      return
    }

    setLocalState({ status: 'uploading', filename: file.name, mediaType: file.type })
    try {
      const result = await onUpload(item, file)
      if (result?.succeeded === false) {
        setLocalState({
          status: 'error',
          filename: file.name,
          mediaType: file.type,
          label: 'Upload failed',
          message: result.message
            || 'Northwind could not upload this file. Check your connection, then choose Replace and try again.',
        })
        return
      }
      setLocalState(null)
    } catch (error) {
      setLocalState({
        status: 'error',
        filename: file.name,
        mediaType: file.type,
        label: 'Upload failed',
        message: `${error?.message || 'Northwind could not upload this file.'} Choose Replace and try again.`,
      })
    }
  }

  return (
    <li className="claim-document-card">
      <div className="document-card-heading">
        <span className="document-type-icon">
          {isPhoto ? <CameraIcon /> : <FileIcon />}
        </span>
        <div className="document-card-title-row">
          <h4>{documentTaskTitle(item)}</h4>
          <span className={`document-status document-status-${lifecycle === 'later' ? 'later' : requirement}`}>
            <span aria-hidden="true">{statusDetails.symbol}</span>
            {statusDetails.label}
          </span>
        </div>
      </div>

      <p className="document-card-description">{documentTaskDescription(item)}</p>
      <p className="document-card-formats">
        <span className="document-format-icon"><FileIcon /></span>
        <span>{DOCUMENT_UPLOAD_CONSTRAINTS.summary}</span>
      </p>

      <DocumentFileState state={fileState} />

      {isPhoto && (
        <div className="document-photo-help">
          <button
            className="document-text-action"
            type="button"
            aria-expanded={tipsOpen}
            aria-controls={tipsId}
            onClick={() => setTipsOpen((open) => !open)}
          >
            {tipsOpen ? 'Hide photo tips' : 'See photo tips'}
          </button>
          <p id={tipsId} hidden={!tipsOpen}>
            Include one photo of the full damaged area and clear close-ups in good light.
          </p>
        </div>
      )}

      {showFilePicker && (
        <div className="document-card-actions">
          <input
            ref={inputRef}
            hidden
            type="file"
            accept={DOCUMENT_UPLOAD_CONSTRAINTS.accept}
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file) handleFile(file)
              event.target.value = ''
            }}
          />
          <button
            className={`document-upload-action ${emphasized ? 'is-primary' : ''}`}
            type="button"
            aria-label={`${uploadLabel} for ${documentTaskTitle(item)}`}
            onClick={() => inputRef.current?.click()}
          >
            <UploadIcon />
            {uploadLabel}
          </button>
        </div>
      )}

      {isUploading && (
        <div className="document-card-actions">
          <button className="document-upload-action is-primary" type="button" disabled>
            <span aria-hidden="true">…</span>
            {isPhoto ? 'Uploading photos…' : 'Uploading file…'}
          </button>
        </div>
      )}
    </li>
  )
}

function DocumentGroup({ emphasizedId, items, label, onUpload }) {
  if (!items.length) return null
  const headingId = `document-group-${label.toLowerCase().replaceAll(' ', '-')}`
  return (
    <section className="claim-document-group" aria-labelledby={headingId}>
      <div className="document-group-heading">
        <h3 id={headingId}>{label}</h3>
        <span>{items.length} {items.length === 1 ? 'item' : 'items'}</span>
      </div>
      <ul className="claim-document-list">
        {items.map((item) => (
          <DocumentTaskCard
            emphasized={item.evidence_id === emphasizedId}
            item={item}
            key={item.evidence_id}
            onUpload={onUpload}
          />
        ))}
      </ul>
    </section>
  )
}

export default function ClaimDocuments({ items, loadStatus, onUpload, compact = false }) {
  const sortedItems = [...items].sort((left, right) => {
    const requirementDifference = (documentRequirement(left) === 'required' ? 0 : 1)
      - (documentRequirement(right) === 'required' ? 0 : 1)
    const statusDifference = DOCUMENT_STATUS_ORDER[documentStatus(left)]
      - DOCUMENT_STATUS_ORDER[documentStatus(right)]
    return requirementDifference || statusDifference || documentTaskTitle(left).localeCompare(documentTaskTitle(right))
  })
  const providedCount = documentProvidedCount(sortedItems)
  const totalCount = sortedItems.length
  const requiredItems = sortedItems.filter((item) => documentRequirement(item) === 'required')
  const recommendedItems = sortedItems.filter((item) => documentRequirement(item) === 'recommended')
  const emphasizedItem = sortedItems.find((item) => {
    const state = taskFileState(item, null)
    return !state || state.kind === 'error'
  })
  const progressText = loadStatus === 'loading' || loadStatus === 'idle'
    ? 'Checking progress…'
    : `${providedCount} of ${totalCount} provided`

  if (compact && totalCount === 0) {
    return (
      <section className="claim-documents is-compact-empty" aria-labelledby="claim-documents-title" aria-busy={loadStatus === 'loading'}>
        <h3 id="claim-documents-title">Documents and evidence</h3>
        {loadStatus === 'loading' || loadStatus === 'idle' ? (
          <p role="status">Checking what may help with this claim…</p>
        ) : loadStatus === 'error' ? (
          <p className="is-error" role="alert">Document guidance could not be loaded. Your claim is still saved.</p>
        ) : (
          <p>No documents required yet.</p>
        )}
      </section>
    )
  }

  return (
    <section className="claim-documents" aria-labelledby="claim-documents-title" aria-busy={loadStatus === 'loading'}>
      <div className="document-overview">
        <div className="document-overview-heading">
          <h3 id="claim-documents-title">Documents and evidence</h3>
          <span aria-live="polite">{progressText}</span>
        </div>
        <progress
          aria-label="Documents and evidence provided"
          max={Math.max(totalCount, 1)}
          value={providedCount}
        />
      </div>

      {loadStatus === 'loading' || loadStatus === 'idle' ? (
        <p className="document-panel-state" role="status">Checking what may help with this claim…</p>
      ) : loadStatus === 'error' ? (
        <div className="document-panel-state is-error" role="alert">
          <strong>Document guidance could not be loaded.</strong>
          <span>Your claim is still saved. Check your connection and return to Next steps to try again.</span>
        </div>
      ) : sortedItems.length === 0 ? (
        <div className="document-panel-state">
          <strong>Nothing to provide right now.</strong>
          <span>Any documents or evidence that may help will appear here.</span>
        </div>
      ) : (
        <>
          <DocumentGroup
            emphasizedId={emphasizedItem?.evidence_id}
            items={requiredItems}
            label="Required for this claim"
            onUpload={onUpload}
          />
          <DocumentGroup
            emphasizedId={emphasizedItem?.evidence_id}
            items={recommendedItems}
            label="Recommended for this claim"
            onUpload={onUpload}
          />
        </>
      )}
    </section>
  )
}
