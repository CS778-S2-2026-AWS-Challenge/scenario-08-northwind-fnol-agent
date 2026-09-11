import { useEffect, useId, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { ProjectedActionInput } from './ProjectedAction.jsx'

export default function ReopenClaimDialog({ action, onReopen }) {
  const [open, setOpen] = useState(false)
  const [reason, setReason] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [operationKey, setOperationKey] = useState('')
  const trigger = useRef(null)
  const dialog = useRef(null)
  const reasonInput = useRef(null)
  const titleId = useId()
  const descriptionId = useId()
  const reasonDefinition = action.inputs.find((input) => input.field_code === 'reason')
  const missingReason = !reason.trim()

  useEffect(() => {
    if (!open) return undefined
    const root = document.getElementById('root')
    const previouslyInert = root?.inert || false
    const returnFocusTarget = trigger.current
    if (root) root.inert = true
    reasonInput.current?.focus()
    return () => {
      if (root) root.inert = previouslyInert
      returnFocusTarget?.focus()
    }
  }, [open])

  useEffect(() => {
    if (!open || !dialog.current) return undefined
    const currentDialog = dialog.current
    function handleKeyDown(event) {
      if (event.key === 'Escape') {
        event.preventDefault()
        if (!busy) setOpen(false)
      }
    }
    currentDialog.addEventListener('keydown', handleKeyDown)
    return () => currentDialog.removeEventListener('keydown', handleKeyDown)
  }, [busy, open])

  function begin() {
    setError('')
    setOperationKey(crypto.randomUUID())
    setOpen(true)
  }

  function focusFirstControl() {
    reasonInput.current?.focus()
  }

  function focusLastControl() {
    const focusable = [...(dialog.current?.querySelectorAll('button:not(:disabled), textarea:not(:disabled), input:not(:disabled), select:not(:disabled), [href]') || [])]
    focusable.at(-1)?.focus()
  }

  function handleFirstControlKey(event) {
    if (event.key === 'Escape') {
      event.preventDefault()
      close()
    } else if (event.key === 'Tab' && event.shiftKey) {
      event.preventDefault()
      focusLastControl()
    }
  }

  function handleLastControlKey(event) {
    if (event.key === 'Escape') {
      event.preventDefault()
      close()
    } else if (event.key === 'Tab' && !event.shiftKey) {
      event.preventDefault()
      focusFirstControl()
    }
  }

  function close() {
    if (!busy) setOpen(false)
  }

  function changeReason(event) {
    setReason(event.target.value)
    setError('')
    setOperationKey(crypto.randomUUID())
  }

  async function submit(event) {
    event.preventDefault()
    if (busy || missingReason) return
    setBusy(true)
    setError('')
    try {
      await onReopen(action, { reason: reason.trim() }, operationKey)
      setOpen(false)
    } catch (nextError) {
      setError(reopenErrorMessage(nextError))
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      <button ref={trigger} className="button button--primary" type="button" onClick={begin}>Review reopen</button>
      {open && createPortal(
        <div className="confirmation-backdrop">
          <section ref={dialog} className="confirmation-dialog" role="dialog" aria-modal="true" aria-labelledby={titleId} aria-describedby={descriptionId}>
            <header>
              <p className="eyebrow">Confirm staff action</p>
              <h2 id={titleId}>{action.label}</h2>
              <p id={descriptionId}>{action.confirmation?.message || action.purpose}</p>
            </header>
            <form onSubmit={submit}>
              {reasonDefinition && <ProjectedActionInput input={reasonDefinition} inputRef={reasonInput} value={reason} onChange={changeReason} onKeyDown={handleFirstControlKey} />}
              {error && <p className="form-error" role="alert">{error}</p>}
              <div className="confirmation-dialog__actions">
                <button className="button button--quiet" type="button" disabled={busy} onClick={close} onKeyDown={missingReason ? handleLastControlKey : undefined}>Cancel</button>
                <button className="button button--primary" type="submit" disabled={busy || missingReason} onKeyDown={handleLastControlKey}>{busy ? 'Reopening...' : action.label}</button>
              </div>
            </form>
          </section>
        </div>,
        document.body,
      )}
    </>
  )
}

function reopenErrorMessage(error) {
  const reload = error?.projectionReloaded ? ' The latest server projection is now shown.' : ''
  if (error?.code === 'REVISION_CONFLICT') return `This Claim changed after you opened it, so it was not reopened. Review the latest revision and try again.${reload}`
  if (error?.code === 'ACCESS_DENIED') return `You are not authorised to reopen this Claim in its current state. Ask the primary owner to review it.${reload}`
  if (error?.code === 'RESOURCE_NOT_FOUND') return 'This Claim is no longer available to your staff account. Return to the queue and refresh it.'
  if (error?.code === 'IDEMPOTENCY_CONFLICT') return `This reopen attempt no longer matches the original request. Review the latest Claim before trying again.${reload}`
  return `The reopen result could not be confirmed. ${error?.message || 'The Workbench service did not return a usable result.'} Refresh the Claim before trying again.${reload}`
}
