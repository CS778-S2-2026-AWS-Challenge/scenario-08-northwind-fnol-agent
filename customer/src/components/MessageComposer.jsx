import { useEffect, useRef, useState } from 'react'

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
  claimType = 'motor',
  setClaimType,
  claimTypes = ['motor', 'home', 'contents'],
  models = [],
  selectedModel = '',
  setSelectedModel,
  modelLocked = false,
  attachments = [],
  onFileSelected,
}) {
  const isWorkspace = variant === 'workspace'
  const fileInput = useRef(null)
  const textareaRef = useRef(null)
  const [voiceStatus, setVoiceStatus] = useState('')

  useEffect(() => {
    const textarea = textareaRef.current
    if (!textarea) return
    textarea.style.height = 'auto'
    const minHeight = 52
    const maxHeight = 220
    textarea.style.height = `${Math.min(Math.max(textarea.scrollHeight, minHeight), maxHeight)}px`
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

  const modelLabel = selectedModel || models[0]?.label || 'Model unavailable'

  return (
    <form className={`composer ${isWorkspace ? 'workspace-composer' : ''}`} onSubmit={onSubmit}>
      <label className="sr-only" htmlFor={isWorkspace ? 'workspace-incident-input' : 'incident-input'}>{inputLabel}</label>
      <div className={isWorkspace ? 'composer-input-surface' : undefined}>
        {isWorkspace && attachments.length > 0 && (
          <div className="composer-attachments" aria-label="Attached files">
            {attachments.map((attachment) => (
              <div className={`composer-file composer-file-${attachment.status || 'uploaded'}`} key={attachment.id || attachment.name}>
                <span className="composer-file-icon" aria-hidden="true">↗</span>
                <span className="composer-file-copy">
                  <strong>{attachment.name}</strong>
                  <small>{attachment.statusLabel || attachment.status || 'Uploaded'}</small>
                </span>
                {attachment.retry && <button type="button" className="text-button" onClick={attachment.retry}>{attachment.retryLabel || 'Retry'}</button>}
              </div>
            ))}
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
          <button className="tool-btn tool-attach" type="button" aria-label="Attach a file" onClick={() => fileInput.current?.click()}><span aria-hidden="true">+</span></button>
          <button className="tool-btn tool-voice" type="button" aria-label="Voice input" onClick={startVoiceInput}>Voice</button>
          {isWorkspace && setClaimType && (
            <label className="claim-type-control">
              <span className="sr-only">Claim type (optional)</span>
              <select
                className="claim-type-select"
                aria-label="Claim type (optional)"
                value={claimType}
                onChange={(event) => setClaimType(event.target.value)}
                disabled={busy || disabled}
              >
                {claimTypes.map((type) => <option value={type} key={type}>{type[0].toUpperCase() + type.slice(1)}</option>)}
              </select>
            </label>
          )}
          {isWorkspace && setSelectedModel && (
            <label className="model-control">
              <span className="sr-only">Model</span>
              <select
                className="model-select"
                aria-label="Model"
                value={selectedModel}
                onChange={(event) => setSelectedModel(event.target.value)}
                disabled={busy || disabled || modelLocked || models.length === 0}
              >
                {models.length === 0 ? <option value="">{modelLabel}</option> : models.map((model) => <option value={model.id} key={model.id}>{model.label}</option>)}
              </select>
            </label>
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
