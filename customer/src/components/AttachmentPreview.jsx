import { useEffect, useState } from 'react'

function localAttachmentFile(attachment) {
  return attachment?.previewFile || attachment?.stagedFile || attachment?.retryFile || null
}

function LocalAttachmentPreview({ attachment, file, fallbackClassName, className }) {
  const [objectUrl, setObjectUrl] = useState('')
  const name = attachment?.name || file.name || 'attached file'

  useEffect(() => {
    const createObjectUrl = globalThis.URL.createObjectURL
    const revokeObjectUrl = globalThis.URL?.revokeObjectURL
    let nextUrl
    try {
      nextUrl = createObjectUrl.call(globalThis.URL, file)
    } catch {
      return undefined
    }

    // The URL only exists after the browser allocates the external Blob resource.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setObjectUrl(nextUrl)
    return () => {
      if (typeof revokeObjectUrl === 'function') {
        revokeObjectUrl.call(globalThis.URL, nextUrl)
      }
    }
  }, [file])

  if (!objectUrl) return <span className={fallbackClassName} aria-hidden="true">↗</span>

  const isImage = file.type?.startsWith('image/')
  return (
    <a
      className={`attachment-preview ${className}`.trim()}
      href={objectUrl}
      target="_blank"
      rel="noreferrer"
      aria-label={`Open ${name} in a new tab`}
      title={`Open ${name} in a new tab`}
    >
      {isImage ? (
        <img className="attachment-preview-image" src={objectUrl} alt="" />
      ) : (
        <span className="attachment-preview-glyph" aria-hidden="true">↗</span>
      )}
    </a>
  )
}

export default function AttachmentPreview({
  attachment,
  fallbackClassName,
  className = '',
}) {
  const file = localAttachmentFile(attachment)
  if (!file || typeof globalThis.URL?.createObjectURL !== 'function') {
    return <span className={fallbackClassName} aria-hidden="true">↗</span>
  }

  return (
    <LocalAttachmentPreview
      attachment={attachment}
      file={file}
      fallbackClassName={fallbackClassName}
      className={className}
    />
  )
}
