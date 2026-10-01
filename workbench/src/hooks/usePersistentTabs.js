import { useCallback, useEffect, useMemo, useState } from 'react'
import { claimIdentity } from '../claim-identity.js'

const STORAGE_KEY = 'northwind.workbench.tabs.v1'

// Open tabs carry Claim summaries, so each staff identity keeps its own record.
function storageKeyFor(staffId) {
  return staffId ? `${STORAGE_KEY}:${staffId}` : null
}

function initialState(storageKey) {
  try {
    // Remove the former browser-wide record, which any later account could read.
    localStorage.removeItem(STORAGE_KEY)
    const value = storageKey ? JSON.parse(localStorage.getItem(storageKey) || 'null') : null
    if (Array.isArray(value?.tabs)) {
      const tabs = value.tabs.map(normalizePersistedTab)
      return { tabs, activeId: value.activeId || tabs[0]?.claimId || null }
    }
  } catch {
    // A malformed local preference must not prevent staff from opening the Workbench.
  }
  return { tabs: [], activeId: null }
}

export function usePersistentTabs(staffId) {
  const storageKey = storageKeyFor(staffId)
  const [loadedKey, setLoadedKey] = useState(storageKey)
  const [state, setState] = useState(() => initialState(storageKey))
  if (loadedKey !== storageKey) {
    setLoadedKey(storageKey)
    setState(initialState(storageKey))
  }

  useEffect(() => {
    if (storageKey) localStorage.setItem(storageKey, JSON.stringify(state))
  }, [state, storageKey])

  const open = useCallback((claim) => {
    setState((current) => {
      const existing = current.tabs.find((tab) => tab.claimId === claim.claim_id)
      const identityFields = tabIdentityFields(claim)
      if (existing) {
        return {
          tabs: current.tabs.map((tab) => (
            tab.claimId === existing.claimId ? { ...tab, ...identityFields } : tab
          )),
          activeId: existing.claimId,
        }
      }
      const tab = {
        claimId: claim.claim_id,
        ...identityFields,
        section: 'summary',
        draft: '',
        expandedRecords: [],
        pendingAction: null,
      }
      return { tabs: [...current.tabs, tab], activeId: tab.claimId }
    })
  }, [])

  const syncIdentities = useCallback((claims = []) => {
    const claimById = new Map(claims.map((claim) => [claim.claim_id, claim]))
    setState((current) => {
      let changed = false
      const tabs = current.tabs.map((tab) => {
        const claim = claimById.get(tab.claimId)
        if (!claim) return tab
        const identityFields = tabIdentityFields(claim)
        if (
          tab.label === identityFields.label
          && tab.reference === identityFields.reference
          && tab.referenceLabel === identityFields.referenceLabel
        ) return tab
        changed = true
        return { ...tab, ...identityFields }
      })
      return changed ? { ...current, tabs } : current
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

  return { ...state, activeTab, open, syncIdentities, activate, close, update }
}

function tabIdentityFields(claim) {
  const identity = claimIdentity(claim)
  return {
    label: identity.tabLabel,
    reference: identity.reference,
    referenceLabel: identity.referenceLabel,
  }
}

function normalizePersistedTab(tab) {
  if (tab.reference && tab.referenceLabel) return tab
  const legacyReference = tab.label || tab.claimId
  const identity = claimIdentity({
    claim_id: tab.claimId,
    display_reference: legacyReference,
  })
  return {
    ...tab,
    label: 'Claim in progress',
    reference: legacyReference,
    referenceLabel: identity.referenceLabel,
  }
}
