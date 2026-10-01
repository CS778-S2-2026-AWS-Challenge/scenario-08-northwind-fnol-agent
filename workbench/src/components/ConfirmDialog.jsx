import { useEffect, useId, useRef } from 'react'
import { createPortal } from 'react-dom'
import { translate as t, useLanguage } from '../i18n.js'

function focusableElements(container) {
  return [...container.querySelectorAll(
    'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
  )]
}

export default function ConfirmDialog({
  open,
  title,
  description,
  children = null,
  cancelLabel = null,
  confirmLabel = null,
  busyLabel = null,
  busy = false,
  confirmDisabled = false,
  danger = false,
  error = null,
  dialogClassName = '',
  returnFocusRef = null,
  onCancel,
  onConfirm,
}) {
  useLanguage()
  const dialogRef = useRef(null)
  const cancelRef = useRef(null)
  const triggerRef = useRef(null)
  const busyRef = useRef(busy)
  const cancelHandlerRef = useRef(onCancel)
  const titleId = useId()
  const descriptionId = useId()

  useEffect(() => {
    busyRef.current = busy
    cancelHandlerRef.current = onCancel
  }, [busy, onCancel])

  useEffect(() => {
    if (!open) return undefined
    const root = document.getElementById('root')
    const previouslyInert = root?.inert || false
    triggerRef.current = returnFocusRef?.current || document.activeElement
    if (root) root.inert = true
    cancelRef.current?.focus()

    function onKeyDown(event) {
      if (event.key === 'Escape' && !busyRef.current) {
        event.preventDefault()
        cancelHandlerRef.current()
        return
      }
      if (event.key !== 'Tab') return
      const elements = focusableElements(dialogRef.current)
      if (!elements.length) {
        event.preventDefault()
        dialogRef.current?.focus()
        return
      }
      const first = elements[0]
      const last = elements.at(-1)
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault()
        last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault()
        first.focus()
      }
    }

    document.addEventListener('keydown', onKeyDown)
    return () => {
      document.removeEventListener('keydown', onKeyDown)
      if (root) root.inert = previouslyInert
      if (triggerRef.current && document.contains(triggerRef.current)) {
        triggerRef.current.focus()
      }
    }
  }, [open, returnFocusRef])

  if (!open) return null

  return createPortal(
    <div className="confirmation-backdrop settings-dialog-backdrop" onMouseDown={(event) => {
      if (event.target === event.currentTarget && !busy) onCancel()
    }}>
      <div
        className={['confirmation-dialog', 'settings-dialog', dialogClassName].filter(Boolean).join(' ')}
        role="alertdialog"
        aria-modal="true"
        aria-labelledby={titleId}
        aria-describedby={descriptionId}
        tabIndex={-1}
        ref={dialogRef}
      >
        <header>
          <h2 id={titleId}>{title}</h2>
          <p id={descriptionId}>{description}</p>
        </header>
        {children}
        {error && <p className="settings-feedback settings-feedback--error" role="alert">{error}</p>}
        <div className="confirmation-dialog__actions">
          <button ref={cancelRef} className="button button--secondary" type="button" disabled={busy} onClick={onCancel}>
            {cancelLabel || t('Cancel')}
          </button>
          <button
            className={`button ${danger ? 'button--danger' : 'button--primary'}`}
            type="button"
            disabled={busy || confirmDisabled}
            onClick={onConfirm}
          >
            {busy ? busyLabel || t('Working...') : confirmLabel || t('Confirm')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  )
}
