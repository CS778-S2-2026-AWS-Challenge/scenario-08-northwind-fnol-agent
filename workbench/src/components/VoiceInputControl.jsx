import { Mic, Square, X } from 'lucide-react'
import { forwardRef, useEffect, useImperativeHandle, useLayoutEffect, useRef, useState } from 'react'

const VoiceInputControl = forwardRef(function VoiceInputControl({
  available,
  draft,
  onDraft,
  textareaRef,
}, controllerRef) {
  const [voiceState, setVoiceState] = useState('idle')
  const [voiceStatus, setVoiceStatus] = useState('')
  const currentDraftRef = useRef(draft)
  const recognitionRef = useRef(null)
  const voiceEndReasonRef = useRef(null)

  useLayoutEffect(() => {
    currentDraftRef.current = draft
  }, [draft])

  useEffect(() => () => {
    const recognition = recognitionRef.current
    recognitionRef.current = null
    voiceEndReasonRef.current = 'unmount'
    if (!recognition) return
    try {
      recognition.abort()
    } catch {
      // The browser may already have released the recognition session.
    }
  }, [])

  useImperativeHandle(controllerRef, () => ({
    cancel: (options) => cancelVoiceInput(options),
  }))

  function cancelVoiceInput({ announce = true, restoreFocus = true } = {}) {
    const recognition = recognitionRef.current
    if (!recognition) return
    recognitionRef.current = null
    voiceEndReasonRef.current = 'cancelled'
    try {
      recognition.abort()
    } catch {
      // The browser may already have released the recognition session.
    }
    setVoiceState('idle')
    setVoiceStatus(
      announce
        ? 'Voice input cancelled. Any text already added remains in your draft.'
        : '',
    )
    if (restoreFocus) textareaRef.current?.focus()
  }

  function stopVoiceInput() {
    const recognition = recognitionRef.current
    if (!recognition || voiceState === 'stopping') return
    voiceEndReasonRef.current = 'stopped'
    setVoiceState('stopping')
    setVoiceStatus('Finishing voice input…')
    try {
      recognition.stop()
    } catch {
      recognitionRef.current = null
      voiceEndReasonRef.current = null
      setVoiceState('error')
      setVoiceStatus('Voice input could not be stopped cleanly. Review your draft and try again.')
    }
  }

  function startVoiceInput() {
    if (!available) return
    if (recognitionRef.current) {
      stopVoiceInput()
      return
    }
    const SpeechRecognition = globalThis.SpeechRecognition || globalThis.webkitSpeechRecognition
    if (!SpeechRecognition) {
      setVoiceState('unsupported')
      setVoiceStatus('Voice input is not available in this browser. You can continue typing your message.')
      return
    }

    const recognition = new SpeechRecognition()
    recognitionRef.current = recognition
    voiceEndReasonRef.current = null
    recognition.lang = 'en-NZ'
    recognition.interimResults = false
    recognition.continuous = true
    recognition.maxAlternatives = 1
    let lastTranscript = ''

    recognition.onresult = (event) => {
      if (recognitionRef.current !== recognition) return
      const startIndex = Number.isInteger(event.resultIndex) ? event.resultIndex : 0
      const transcript = Array.from(event.results || [])
        .slice(startIndex)
        .filter((result) => result?.isFinal !== false)
        .map((result) => result?.[0]?.transcript || '')
        .join(' ')
        .trim()
      if (!transcript || transcript === lastTranscript) return
      lastTranscript = transcript
      const normalizedDraft = currentDraftRef.current.replace(/\s+$/, '')
      const nextDraft = `${normalizedDraft}${normalizedDraft ? ' ' : ''}${transcript}`
      currentDraftRef.current = nextDraft
      onDraft(nextDraft)
      setVoiceStatus('Listening… Voice input is being added to your draft.')
    }
    recognition.onerror = (event) => {
      if (recognitionRef.current !== recognition) return
      const expectedEnd = voiceEndReasonRef.current
      recognitionRef.current = null
      voiceEndReasonRef.current = null
      if (event.error === 'aborted' && expectedEnd) return
      setVoiceState('error')
      setVoiceStatus(
        event.error === 'aborted'
          ? 'Voice input stopped unexpectedly. Review your draft and try again.'
          : voiceErrorMessage(event.error),
      )
    }
    recognition.onend = () => {
      if (recognitionRef.current !== recognition) return
      const expectedEnd = voiceEndReasonRef.current
      recognitionRef.current = null
      voiceEndReasonRef.current = null
      if (expectedEnd === 'stopped') {
        setVoiceState('idle')
        setVoiceStatus('Voice input stopped. Review the transcript before sending.')
        textareaRef.current?.focus()
        return
      }
      setVoiceState('error')
      setVoiceStatus('Voice input stopped unexpectedly. Review your draft and try again.')
    }

    setVoiceState('listening')
    setVoiceStatus('Listening… Speak naturally, then stop and review the transcript before sending.')
    try {
      recognition.start()
    } catch {
      recognitionRef.current = null
      voiceEndReasonRef.current = null
      setVoiceState('error')
      setVoiceStatus('Voice input could not be started. You can continue typing or try again.')
    }
  }

  return (
    <>
      <button
        className={`staff-composer__voice${voiceState === 'listening' ? ' is-listening' : ''}`}
        type="button"
        disabled={!available || voiceState === 'stopping'}
        aria-label={voiceState === 'listening' ? 'Stop voice input' : 'Use voice input'}
        aria-pressed={voiceState === 'listening'}
        title={voiceState === 'listening' ? 'Stop voice input' : 'Use voice input'}
        onClick={startVoiceInput}
      >
        {voiceState === 'listening'
          ? <Square size={16} aria-hidden="true" />
          : <Mic size={18} aria-hidden="true" />}
      </button>
      {voiceStatus && (
        <div
          className={`staff-composer__voice-status${['error', 'unsupported'].includes(voiceState) ? ' is-error' : ''}`}
        >
          <span
            id="staff-voice-status"
            role={['error', 'unsupported'].includes(voiceState) ? 'alert' : 'status'}
            aria-live={['error', 'unsupported'].includes(voiceState) ? 'assertive' : 'polite'}
            aria-atomic="true"
          >
            {voiceStatus}
          </span>
          {voiceState === 'listening' && (
            <button
              className="staff-composer__voice-cancel"
              type="button"
              onClick={() => cancelVoiceInput()}
            >
              <X size={14} aria-hidden="true" />
              Cancel
            </button>
          )}
        </div>
      )}
    </>
  )
})

function voiceErrorMessage(error) {
  switch (error) {
    case 'not-allowed':
    case 'service-not-allowed':
      return 'Microphone permission was denied. Allow microphone access and try again.'
    case 'no-speech':
      return 'No speech was detected. Try again when you are ready.'
    case 'audio-capture':
      return 'No working microphone was found. Check your device and try again.'
    case 'network':
      return 'Voice recognition could not reach the browser speech service. Check your connection and try again.'
    default:
      return 'Voice input could not be completed. Try again.'
  }
}

export default VoiceInputControl
