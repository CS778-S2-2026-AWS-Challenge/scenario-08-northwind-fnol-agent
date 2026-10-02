const FOCUSABLE_SELECTOR = 'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'

export function focusableElements(container) {
  return container ? [...container.querySelectorAll(FOCUSABLE_SELECTOR)] : []
}

// Keeps Tab and Shift+Tab inside a dialog container. Returns true when it moved focus.
export function containTabFocus(event, container) {
  if (event.key !== 'Tab' || !container) return false
  const elements = focusableElements(container)
  if (!elements.length) {
    event.preventDefault()
    container.focus()
    return true
  }
  const first = elements[0]
  const last = elements.at(-1)
  if (event.shiftKey && document.activeElement === first) {
    event.preventDefault()
    last.focus()
    return true
  }
  if (!event.shiftKey && document.activeElement === last) {
    event.preventDefault()
    first.focus()
    return true
  }
  return false
}
