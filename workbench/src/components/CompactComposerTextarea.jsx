import { forwardRef, useImperativeHandle, useLayoutEffect, useRef } from 'react'

const CompactComposerTextarea = forwardRef(function CompactComposerTextarea({
  describedBy,
  disabled = false,
  id,
  label,
  onValueChange,
  placeholder,
  submitDisabled = false,
  value,
}, forwardedRef) {
  const textareaRef = useRef(null)

  useImperativeHandle(forwardedRef, () => textareaRef.current)

  useLayoutEffect(() => {
    resizeTextarea(textareaRef.current)
  }, [value])

  function changeValue(event) {
    resizeTextarea(event.currentTarget)
    onValueChange(event.target.value)
  }

  function handleKeyDown(event) {
    const isComposing = event.isComposing || event.nativeEvent?.isComposing
    if (event.key !== 'Enter' || event.shiftKey || isComposing) return
    event.preventDefault()
    if (!submitDisabled) event.currentTarget.form?.requestSubmit()
  }

  return (
    <>
      <label className="sr-only" htmlFor={id}>{label}</label>
      <textarea
        ref={textareaRef}
        className="compact-composer__textarea"
        id={id}
        rows="1"
        value={value}
        onChange={changeValue}
        onKeyDown={handleKeyDown}
        disabled={disabled}
        placeholder={placeholder}
        aria-describedby={describedBy}
      />
    </>
  )
})

function resizeTextarea(textarea) {
  if (!textarea) return
  textarea.style.height = 'auto'
  const maxHeight = Number.parseFloat(globalThis.getComputedStyle?.(textarea).maxHeight)
  const contentHeight = textarea.scrollHeight
  if (contentHeight > 0) {
    textarea.style.height = `${Number.isFinite(maxHeight) ? Math.min(contentHeight, maxHeight) : contentHeight}px`
  }
  textarea.style.overflowY = Number.isFinite(maxHeight) && contentHeight > maxHeight ? 'auto' : 'hidden'
}

export default CompactComposerTextarea
