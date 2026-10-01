// Moves the message composer from the centre of the start page to the bottom of
// the conversation (FLIP): the workspace composer is first drawn where the start
// page composer was, then transitions to its own place. Timing and easing come
// from the `.is-arriving` rule in the stylesheet (design tokens).

export function prefersReducedMotion() {
  return Boolean(globalThis.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches)
}

export function captureComposerRect(form) {
  if (!form?.getBoundingClientRect || prefersReducedMotion()) return null
  return form.getBoundingClientRect()
}

export function playComposerHandoff(target, fromRect) {
  if (!target || !fromRect || prefersReducedMotion()) return false
  const toRect = target.getBoundingClientRect()
  const dx = fromRect.left - toRect.left
  const dy = fromRect.top - toRect.top
  if (!dx && !dy) return false
  target.classList.remove('is-arriving')
  target.style.transform = `translate(${dx}px, ${dy}px)`
  target.getBoundingClientRect()
  target.classList.add('is-arriving')
  target.style.transform = ''
  target.addEventListener('transitionend', () => target.classList.remove('is-arriving'), { once: true })
  return true
}
