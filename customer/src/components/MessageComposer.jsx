import { useEffect, useId, useRef, useState } from 'react'

function OptionMenu({
  value,
  options,
  onChange,
  disabled = false,
  label,
  className = '',
  placement = 'bottom',
}) {
  const rootRef = useRef(null)
  const triggerRef = useRef(null)
  const optionRefs = useRef([])
  const restoreTriggerFocus = useRef(false)
  const listboxId = useId()
  const [open, setOpen] = useState(false)
  const [activeIndex, setActiveIndex] = useState(0)
  const selected = options.find((option) => option.value === value)

  function enabledIndex(preferredIndex, direction = 1) {
    if (options.length === 0) return -1
    let index = Math.min(Math.max(preferredIndex, 0), options.length - 1)
    while (index >= 0 && index < options.length && options[index].disabled) index += direction
    return index >= 0 && index < options.length ? index : -1
  }

  function focusOption(index) {
    const nextIndex = enabledIndex(index, index < activeIndex ? -1 : 1)
    if (nextIndex < 0) return
    setActiveIndex(nextIndex)
    optionRefs.current[nextIndex]?.focus()
  }

  function openMenu(preferredIndex) {
    const selectedIndex = options.findIndex((option) => option.value === value && !option.disabled)
    const nextIndex = enabledIndex(
      preferredIndex ?? (selectedIndex >= 0 ? selectedIndex : 0),
      preferredIndex === options.length - 1 ? -1 : 1,
    )
    setActiveIndex(Math.max(nextIndex, 0))
    setOpen(true)
    requestAnimationFrame(() => optionRefs.current[nextIndex]?.focus())
  }

  function selectOption(option) {
    if (option.disabled) return
    restoreTriggerFocus.current = true
    onChange(option.value)
    setOpen(false)
  }

  function handleTriggerKeyDown(event) {
    if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
      event.preventDefault()
      openMenu(event.key === 'ArrowUp' ? options.length - 1 : undefined)
    }
  }

  function handleOptionKeyDown(event, index, option) {
    if (event.key === 'ArrowDown') {
      event.preventDefault()
      focusOption(Math.min(index + 1, options.length - 1))
    } else if (event.key === 'ArrowUp') {
      event.preventDefault()
      focusOption(Math.max(index - 1, 0))
    } else if (event.key === 'Home') {
      event.preventDefault()
      focusOption(0)
    } else if (event.key === 'End') {
      event.preventDefault()
      focusOption(options.length - 1)
    } else if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault()
      selectOption(option)
    } else if (event.key === 'Escape') {
      event.preventDefault()
      setOpen(false)
      triggerRef.current?.focus()
    } else if (event.key === 'Tab') {
      setOpen(false)
    }
  }

  useEffect(() => {
    function closeOnOutside(event) {
      if (!rootRef.current?.contains(event.target)) setOpen(false)
    }
    function closeOnEscape(event) {
      if (event.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', closeOnOutside)
    document.addEventListener('keydown', closeOnEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOnOutside)
      document.removeEventListener('keydown', closeOnEscape)
    }
  }, [])

  useEffect(() => {
    if (!open && restoreTriggerFocus.current) {
      restoreTriggerFocus.current = false
      triggerRef.current?.focus()
    }
  }, [open, value])

  return (
    <div className={`token-select token-select-${placement} ${open ? 'is-open' : ''} ${className}`} ref={rootRef}>
      <button
        ref={triggerRef}
        type="button"
        className="token-select-trigger"
        aria-label={label}
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-controls={open ? listboxId : undefined}
        disabled={disabled}
        onClick={() => (open ? setOpen(false) : openMenu())}
        onKeyDown={handleTriggerKeyDown}
      >
        <span>{selected?.label || value || label}</span>
        <span className="token-select-chevron" aria-hidden="true">⌄</span>
      </button>
      {open && (
        <div className="token-select-menu" id={listboxId} role="listbox" aria-label={label}>
          {options.map((option, index) => (
            <button
              ref={(node) => { optionRefs.current[index] = node }}
              type="button"
              role="option"
              aria-selected={option.value === value}
              aria-disabled={option.disabled || undefined}
              className={`token-select-option ${option.value === value ? 'is-selected' : ''}`}
              key={option.value || 'empty'}
              disabled={option.disabled}
              tabIndex={index === activeIndex ? 0 : -1}
              onFocus={() => setActiveIndex(index)}
              onKeyDown={(event) => handleOptionKeyDown(event, index, option)}
              onClick={() => selectOption(option)}
            >
              <span className="token-select-option-copy">
                <span>{option.label}</span>
                {option.meta && <small>{option.meta}</small>}
              </span>
              {option.value === value && <span className="token-select-check" aria-hidden="true">✓</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  )
}

export default function MessageComposer({
  draft,
  setDraft,
  onSubmit,
  inputLabel,
  busy,
  disabled = false,
  disabledNote = 'Confirm or correct the details before continuing.',
  buttonLabel,
  error,
  placeholder = 'Write the details you know...',
  variant = 'default',
  showClaimTypeControl = false,
  showModelControl = false,
  claimType = '',
  setClaimType,
  claimTypes = ['motor', 'home', 'contents'],
  claimTypeLocked = false,
  models = [],
  selectedModel = '',
  setSelectedModel,
  attachments = [],
  onFileSelected,
  onRemoveAttachment,
}) {
  const isWorkspace = variant === 'workspace'
  const fileInput = useRef(null)
  const textareaRef = useRef(null)
  const [voiceStatus, setVoiceStatus] = useState('')
  const [selectedAttachmentId, setSelectedAttachmentId] = useState(null)

  useEffect(() => {
    const textarea = textareaRef.current
    if (!textarea) return
    textarea.style.height = 'auto'
    textarea.style.height = `${textarea.scrollHeight}px`
  }, [draft, attachments.length])

  function startVoiceInput() {
    const SpeechRecognition = globalThis.SpeechRecognition || globalThis.webkitSpeechRecognition
    if (!SpeechRecognition) {
      setVoiceStatus('Voice input is not available in this browser.')
      return
    }
    const recognition = new SpeechRecognition()
    recognition.lang = 'en-NZ'
    recognition.interimResults = false
    setVoiceStatus('Listening...')
    recognition.onresult = (event) => {
      const transcript = event.results?.[0]?.[0]?.transcript || ''
      if (transcript) setDraft((current) => `${current}${current ? ' ' : ''}${transcript}`)
      setVoiceStatus('')
    }
    recognition.onerror = () => setVoiceStatus('Voice input could not be started.')
    recognition.onend = () => setVoiceStatus('')
    recognition.start()
  }

  function removeAttachment(attachment) {
    if (!onRemoveAttachment) return
    onRemoveAttachment(attachment)
    setSelectedAttachmentId(null)
    textareaRef.current?.focus()
  }

  function handleAttachmentKeyDown(event, attachment) {
    if (event.key !== 'Backspace') return
    event.preventDefault()
    removeAttachment(attachment)
  }

  const modelDisplayName = (model) => model?.label || model?.id
  const selectedModelOption = models.find((model) => model.id === selectedModel)
  const modelLabel = modelDisplayName(selectedModelOption) || selectedModel || modelDisplayName(models[0]) || 'Model unavailable'
  const modelSelectionDisabled = busy || disabled || models.length === 0
  const claimTypeOptions = [
    {
      value: '',
      label: 'Let Agent identify',
      disabled: claimTypeLocked && claimType !== '',
    },
    ...claimTypes.map((type) => ({
      value: type,
      label: `${type[0].toUpperCase()}${type.slice(1)}`,
      disabled: claimTypeLocked && type !== claimType,
    })),
  ]
  const modelOptions = models.map((model) => ({
    value: model.id,
    label: modelDisplayName(model),
    meta: [
      model.label !== model.id ? model.id : null,
      model.availability === 'unavailable' ? 'Unavailable' : null,
    ].filter(Boolean).join(' · ') || undefined,
    disabled: model.availability === 'unavailable',
  }))

  return (
    <form className={`composer ${isWorkspace ? 'workspace-composer' : ''}`} onSubmit={onSubmit}>
      <label className="sr-only" htmlFor={isWorkspace ? 'workspace-incident-input' : 'incident-input'}>{inputLabel}</label>
      <div className={isWorkspace ? 'composer-input-surface' : undefined}>
        {attachments.length > 0 && (
          <div className="composer-attachments" aria-label="Attached files">
            {attachments.map((attachment) => {
              const attachmentId = attachment.id || attachment.name
              const canRemoveFromDraft = Boolean(onRemoveAttachment) && (
                attachment.status === 'staged'
                || attachment.status === 'uploading'
                || (attachment.status === 'failed' && !attachment.evidenceId)
              )
              const content = (
                <>
                  <span className="composer-file-icon" aria-hidden="true">↗</span>
                  <span className="composer-file-copy">
                    <strong>{attachment.name}</strong>
                    <small>{attachment.statusLabel || attachment.status || 'Uploaded'}</small>
                  </span>
                </>
              )
              return (
                <div
                  className={`composer-file composer-file-${attachment.status || 'uploaded'} ${selectedAttachmentId === attachmentId ? 'is-selected' : ''}`}
                  key={attachmentId}
                >
                  {canRemoveFromDraft ? (
                    <button
                      type="button"
                      className="composer-file-select"
                      aria-label={`Select ${attachment.name}`}
                      aria-pressed={selectedAttachmentId === attachmentId}
                      onClick={() => setSelectedAttachmentId(attachmentId)}
                      onFocus={() => setSelectedAttachmentId(attachmentId)}
                      onKeyDown={(event) => handleAttachmentKeyDown(event, attachment)}
                    >
                      {content}
                    </button>
                  ) : (
                    <div className="composer-file-static">{content}</div>
                  )}
                {attachment.retry && <button type="button" className="text-button" onClick={attachment.retry}>{attachment.retryLabel || 'Retry'}</button>}
                {canRemoveFromDraft && (
                  <button
                    type="button"
                    className="composer-file-remove"
                    aria-label={`Remove ${attachment.name}`}
                    onClick={() => removeAttachment(attachment)}
                  >
                    <span aria-hidden="true">×</span>
                  </button>
                )}
                </div>
              )
            })}
          </div>
        )}
        <textarea
          ref={textareaRef}
          id={isWorkspace ? 'workspace-incident-input' : 'incident-input'}
          className={isWorkspace ? 'input-field' : 'report-text'}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={placeholder}
          rows="2"
          disabled={busy || disabled}
        />
        <div className="input-toolbar">
        <div className="toolbar-left">
          <input
            ref={fileInput}
            className="sr-only"
            type="file"
            accept="image/jpeg,image/png,application/pdf"
            onChange={(event) => {
              const file = event.target.files?.[0]
              if (file && onFileSelected) onFileSelected(file)
              event.target.value = ''
            }}
          />
          <button
            className="tool-btn tool-attach"
            type="button"
            aria-label="Attach a file"
            title="Attach a file"
            onClick={() => fileInput.current?.click()}
          >
            <svg className="tool-icon" viewBox="0 0 24 24" aria-hidden="true">
              <path d="M12 5v14M5 12h14" />
            </svg>
          </button>
          <button
            className="tool-btn tool-voice"
            type="button"
            aria-label="Use voice input"
            title="Use voice input"
            onClick={startVoiceInput}
          >
            <svg className="tool-icon" viewBox="0 0 24 24" aria-hidden="true">
              <rect x="9" y="3" width="6" height="11" rx="3" />
              <path d="M6 11a6 6 0 0 0 12 0M12 17v4M9 21h6" />
            </svg>
          </button>
          {(isWorkspace || showClaimTypeControl) && setClaimType && (
            <OptionMenu
              value={claimType}
              options={claimTypeOptions}
              onChange={setClaimType}
              disabled={busy || disabled}
              label="Claim type (optional)"
              className="claim-type-control"
              placement={isWorkspace ? 'top' : 'bottom'}
            />
          )}
          {(isWorkspace || showModelControl) && setSelectedModel && (
            <div className="model-control">
              <OptionMenu
                value={selectedModel}
                options={modelOptions.length > 0 ? modelOptions : [{ value: '', label: modelLabel, disabled: true }]}
                onChange={setSelectedModel}
                disabled={modelSelectionDisabled}
                label="Model"
                className="model-select"
                placement={isWorkspace ? 'top' : 'bottom'}
              />
            </div>
          )}
        </div>
        <button className="send-btn" type="submit" disabled={!draft.trim() || busy || disabled}>
          {buttonLabel}
          <span aria-hidden="true">→</span>
        </button>
        </div>
      </div>
      {disabled && <p className="composer-note">{disabledNote}</p>}
      {error && (
        <div className="backend-status is-error" role="alert">
          <span className="status-dot" />
          <span>{error}</span>
        </div>
      )}
      {voiceStatus && <p className="composer-note" role="status">{voiceStatus}</p>}
    </form>
  )
}
