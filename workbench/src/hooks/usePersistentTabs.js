import { useCallback, useEffect, useMemo, useState } from 'react'

const STORAGE_KEY = 'northwind.workbench.tabs.v1'

function initialState() {
  try {
    const value = JSON.parse(localStorage.getItem(STORAGE_KEY) || 'null')
    if (Array.isArray(value?.tabs)) {
      return { tabs: value.tabs, activeId: value.activeId || value.tabs[0]?.claimId || null }
    }
  } catch {
    // A malformed local preference must not prevent staff from opening the Workbench.
  }
  return { tabs: [], activeId: null }
}

export function usePersistentTabs() {
  const [state, setState] = useState(initialState)

  useEffect(() => {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(state))
  }, [state])

  const open = useCallback((claim) => {
    setState((current) => {
      const existing = current.tabs.find((tab) => tab.claimId === claim.claim_id)
      if (existing) return { ...current, activeId: existing.claimId }
      const tab = {
        claimId: claim.claim_id,
        label: claim.display_reference || claim.claim_id,
        section: 'summary',
        draft: '',
        expandedRecords: [],
        pendingAction: null,
      }
      return { tabs: [...current.tabs, tab], activeId: tab.claimId }
    })
  }, [])

  const activate = useCallback((claimId) => {
    setState((current) => ({ ...current, activeId: claimId }))
  }, [])

  const close = useCallback((claimId) => {
    setState((current) => {
      const index = current.tabs.findIndex((tab) => tab.claimId === claimId)
      if (index < 0) return current
      const tabs = current.tabs.filter((tab) => tab.claimId !== claimId)
      if (current.activeId !== claimId) return { ...current, tabs }
      const neighbour = tabs[Math.min(index, tabs.length - 1)]
      return { tabs, activeId: neighbour?.claimId || null }
    })
  }, [])

  const update = useCallback((claimId, changes) => {
    setState((current) => ({
      ...current,
      tabs: current.tabs.map((tab) =>
        tab.claimId === claimId ? { ...tab, ...changes } : tab,
      ),
    }))
  }, [])

  const activeTab = useMemo(
    () => state.tabs.find((tab) => tab.claimId === state.activeId) || null,
    [state],
  )

  return { ...state, activeTab, open, activate, close, update }
}
