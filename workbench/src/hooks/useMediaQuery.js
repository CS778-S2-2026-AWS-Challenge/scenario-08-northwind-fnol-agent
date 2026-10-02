import { useSyncExternalStore } from 'react'

// Matches the compact Workbench layout breakpoint in styles.css.
export const COMPACT_WORKBENCH_QUERY = '(max-width: 800px)'

function mediaQueryList(query) {
  return typeof window.matchMedia === 'function' ? window.matchMedia(query) : null
}

export function useMediaQuery(query) {
  return useSyncExternalStore(
    (onChange) => {
      const list = mediaQueryList(query)
      list?.addEventListener('change', onChange)
      return () => list?.removeEventListener('change', onChange)
    },
    () => mediaQueryList(query)?.matches ?? false,
    () => false,
  )
}
