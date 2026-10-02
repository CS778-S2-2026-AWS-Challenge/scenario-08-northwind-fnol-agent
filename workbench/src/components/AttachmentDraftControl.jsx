import { FileText, Image as ImageIcon, Paperclip, X } from 'lucide-react'
import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'

const MAX_PENDING_ATTACHMENTS = 5
const MAX_PENDING_ATTACHMENT_BYTES = 10 * 1024 * 1024
const ACCEPTED_ATTACHMENT_TYPES = 'image/*,.pdf,.doc,.docx,.xls,.xlsx,.csv,.txt'
const ACCEPTED_DOCUMENT_EXTENSIONS = new Set(['pdf', 'doc', 'docx', 'xls', 'xlsx', 'csv', 'txt'])

const AttachmentDraftControl = forwardRef(function AttachmentDraftControl({
  available = true,
  children,
  idPrefix,
  triggerClassName,
}, controllerRef) {
  const fileInputRef = useRef(null)
  const attachmentsRef = useRef([])
  const [pendingAttachments, setPendingAttachments] = useState([])
  const [attachmentError, setAttachmentError] = useState('')
  const attachmentsPending = pendingAttachments.length > 0
  const statusId = `${idPrefix}-status`
  const errorId = `${idPrefix}-error`

  useImperativeHandle(controllerRef, () => ({
    clear: () => {
      attachmentsRef.current.forEach(revokeAttachmentPreview)
      attachmentsRef.current = []
      setPendingAttachments([])
      setAttachmentError('')
    },
    hasPendingAttachments: () => attachmentsRef.current.length > 0,
  }), [])

  useEffect(() => () => {
    attachmentsRef.current.forEach(revokeAttachmentPreview)
  }, [])

  function replaceAttachments(nextAttachments) {
    attachmentsRef.current = nextAttachments
    setPendingAttachments(nextAttachments)
  }

  function chooseAttachments(event) {
    const selectedFiles = [...(event.target.files || [])]
    event.target.value = ''
    if (!selectedFiles.length) return

    const nextAttachments = [...attachmentsRef.current]
    const errors = []
    for (const file of selectedFiles) {
      if (nextAttachments.length >= MAX_PENDING_ATTACHMENTS) {
        errors.push(`You can attach up to ${MAX_PENDING_ATTACHMENTS} files.`)
        break
      }
      if (!isSupportedAttachment(file)) {
        errors.push(`${file.name} is not a supported file type.`)
        continue
      }
      if (file.size > MAX_PENDING_ATTACHMENT_BYTES) {
        errors.push(`${file.name} is larger than 10 MB.`)
        continue
      }
      const key = attachmentKey(file)
      if (nextAttachments.some((attachment) => attachment.key === key)) {
        errors.push(`${file.name} is already attached.`)
        continue
      }
      nextAttachments.push({
        file,
        key,
        previewUrl: canPreviewImage(file) && typeof URL.createObjectURL === 'function'
          ? URL.createObjectURL(file)
          : null,
      })
    }
    replaceAttachments(nextAttachments)
    setAttachmentError([...new Set(errors)].join(' '))
  }

  function removeAttachment(key) {
    const attachment = attachmentsRef.current.find((item) => item.key === key)
    revokeAttachmentPreview(attachment)
    replaceAttachments(attachmentsRef.current.filter((item) => item.key !== key))
    setAttachmentError('')
  }

  const trigger = (
    <>
      <input
        ref={fileInputRef}
        className="sr-only"
        type="file"
        disabled={!available}
        multiple
        accept={ACCEPTED_ATTACHMENT_TYPES}
        aria-label="Choose photos or files"
        tabIndex={-1}
        onChange={chooseAttachments}
      />
      <button
        className={triggerClassName}
        type="button"
        disabled={!available}
        aria-label="Attach photos or files"
        aria-describedby={attachmentsPending ? statusId : undefined}
        title="Attach photos or files"
        onClick={() => fileInputRef.current?.click()}
      >
        <Paperclip aria-hidden="true" />
      </button>
    </>
  )
  const preview = (
    <>
      {attachmentsPending && (
        <ul className="staff-composer__attachments" aria-label="Selected attachments">
          {pendingAttachments.map((attachment) => (
            <li key={attachment.key}>
              <span className="staff-composer__attachment-preview" aria-hidden="true">
                {attachment.previewUrl
                  ? <img src={attachment.previewUrl} alt="" />
                  : attachment.file.type.startsWith('image/')
                    ? <ImageIcon />
                    : <FileText />}
              </span>
              <span className="staff-composer__attachment-copy">
                <strong>{attachment.file.name}</strong>
                <small>{formatFileType(attachment.file)} · {formatFileSize(attachment.file.size)}</small>
              </span>
              <button type="button" aria-label={`Remove ${attachment.file.name}`} onClick={() => removeAttachment(attachment.key)}>
                <X aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
      {attachmentsPending && (
        <p className="staff-composer__attachment-status" id={statusId} role="status">
          {pendingAttachments.length} {pendingAttachments.length === 1 ? 'attachment' : 'attachments'} selected locally. Remove {pendingAttachments.length === 1 ? 'it' : 'them'} to send text; file delivery is not available yet.
        </p>
      )}
      {attachmentError && <p className="form-error" id={errorId} role="alert">{attachmentError}</p>}
    </>
  )

  return children({
    attachmentsPending,
    describedBy: [attachmentsPending ? statusId : null, attachmentError ? errorId : null].filter(Boolean).join(' ') || undefined,
    pendingCount: pendingAttachments.length,
    preview,
    trigger,
  })
})

function attachmentKey(file) {
  return `${file.name}:${file.size}:${file.lastModified}`
}

function fileExtension(name) {
  return name.includes('.') ? name.split('.').pop().toLocaleLowerCase() : ''
}

function isSupportedAttachment(file) {
  return file.type.startsWith('image/') || ACCEPTED_DOCUMENT_EXTENSIONS.has(fileExtension(file.name))
}

function canPreviewImage(file) {
  return ['image/gif', 'image/jpeg', 'image/png', 'image/webp'].includes(file.type)
}

function revokeAttachmentPreview(attachment) {
  if (attachment?.previewUrl && typeof URL.revokeObjectURL === 'function') {
    URL.revokeObjectURL(attachment.previewUrl)
  }
}

function formatFileSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.ceil(bytes / 1024)} KB`
  return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
}

function formatFileType(file) {
  const extension = fileExtension(file.name)
  if (extension) return extension.toLocaleUpperCase()
  if (file.type.startsWith('image/')) return 'IMAGE'
  return 'FILE'
}

export default AttachmentDraftControl
