import { useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'

import {
  getClaim,
  getClaimAutoFillSuggestions,
  listAccountAssets,
  listAccountPolicies,
  listClaimAssetSnapshots,
  requestId,
  selectClaimAsset,
  selectClaimPolicy,
} from '../api.js'
import { maskPolicyNumber } from '../profile/policyNumber.js'

function nextCursor(response) {
  return response?.page?.next_cursor || null
}

async function loadEveryPage(listPage, signal) {
  const items = []
  const seenCursors = new Set()
  let cursor = null
  do {
    const response = await listPage({ cursor, limit: 100, signal })
    items.push(...(response?.items || []))
    cursor = nextCursor(response)
    if (cursor && seenCursors.has(cursor)) break
    if (cursor) seenCursors.add(cursor)
  } while (cursor)
  return items
}

function sourceReference(field, kind) {
  const pattern = new RegExp(`^${kind}:([^:]+):revision:(\\d+)$`)
  for (const reference of field?.source_refs || []) {
    const match = pattern.exec(reference)
    if (match) return { id: match[1], revision: Number(match[2]) }
  }
  return null
}

function hasFieldValue(field) {
  return field?.value !== null
    && field?.value !== undefined
    && String(field.value).trim() !== ''
}

function claimAlreadyHasAssetData(claim, assets) {
  return assets.some((asset) => {
    if (asset.asset_type === 'vehicle') {
      return hasFieldValue(claim.form?.['vehicle.registration'])
    }
    if (asset.asset_type === 'property') {
      return hasFieldValue(claim.form?.['property.address'])
    }
    if (asset.asset_type === 'contents') {
      return Boolean(claim.contents_items?.length)
    }
    return false
  })
}

function assetMatchesClaimProductFamily(claim, asset) {
  const productFamily = claim.form?.['claim.product_family']
  if (!hasFieldValue(productFamily)) return true
  const assetProductFamily = {
    vehicle: 'motor',
    property: 'home',
    contents: 'contents',
  }[asset.asset_type]
  return productFamily.value === assetProductFamily
}

function policyLabel(policy) {
  return `Policy ${maskPolicyNumber(policy.policy_number)}`
}

function assetTypeLabel(assetType) {
  return ({ vehicle: 'Vehicle', property: 'Property', contents: 'Valuable item' })[assetType]
    || 'Saved asset'
}

function selectionFingerprint(kind, record) {
  const recordId = kind === 'policy' ? record.policy_id : record.asset_id
  return `${kind}:${recordId}:revision:${record.revision}`
}

function emptyResources() {
  return {
    status: 'idle',
    manifestError: '',
    policies: [],
    policyError: '',
    assets: [],
    assetError: '',
    snapshots: [],
  }
}

function unknownOutcomeMessage(error, kind) {
  const label = kind === 'policy' ? 'the saved policy' : 'the saved asset'
  const reason = error?.message || 'The Claim service did not return a final response.'
  return `We could not confirm whether ${label} was added. ${reason}`
}

export default function ClaimAutoFillPanel({
  account,
  claim,
  busy = false,
  onBusyChange = () => {},
  onClaimReadback,
  onPresenceChange = () => {},
}) {
  const choiceId = useId()
  const mountedRef = useRef(true)
  const claimRef = useRef(claim)
  const readbackRef = useRef(onClaimReadback)
  const busyChangeRef = useRef(onBusyChange)
  const attemptedAutomaticSelections = useRef(new Set())
  const presentationRef = useRef(null)
  const [resources, setResources] = useState(emptyResources)
  const [refreshCount, setRefreshCount] = useState(0)
  const [selectedIds, setSelectedIds] = useState({ policy: '', asset: '' })
  const [pendingKind, setPendingKind] = useState('')
  const [failure, setFailure] = useState(null)
  const [notices, setNotices] = useState([])

  claimRef.current = claim
  readbackRef.current = onClaimReadback
  busyChangeRef.current = onBusyChange

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      busyChangeRef.current(false)
    }
  }, [])

  useEffect(() => {
    if (busy) return undefined
    const controller = new AbortController()
    let active = true

    async function safelyLoad(loader) {
      try {
        return { items: await loader(), error: '' }
      } catch (error) {
        if (error?.name === 'AbortError') throw error
        return {
          items: [],
          error: error?.message || 'The saved records could not be loaded.',
        }
      }
    }

    async function loadSuggestions() {
      setResources((current) => ({
        ...current,
        status: 'loading',
        manifestError: '',
        policyError: '',
        assetError: '',
      }))
      try {
        const manifest = await getClaimAutoFillSuggestions(claim.claim_id, {
          signal: controller.signal,
        })
        if (!active || manifest.claim_id !== claim.claim_id) return

        if (Number(manifest.claim_revision) > Number(claim.revision || 0)) {
          const latestClaim = await getClaim(claim.claim_id)
          if (active) readbackRef.current(latestClaim, {
            minimumRevision: manifest.claim_revision,
          })
          return
        }

        const suggestions = new Map(
          (manifest.suggestions || []).map((suggestion) => [suggestion.category, suggestion]),
        )
        const policyEligible = suggestions.get('policy_number')?.eligible
          && suggestions.get('policy_number')?.action === 'select_policy'
        const assetEligible = suggestions.get('saved_assets')?.eligible
          && suggestions.get('saved_assets')?.action === 'select_asset'

        const [policyResult, assetResult, snapshotResult] = await Promise.all([
          policyEligible
            ? safelyLoad(() => loadEveryPage(listAccountPolicies, controller.signal))
            : { items: [], error: '' },
          assetEligible
            ? safelyLoad(() => loadEveryPage(listAccountAssets, controller.signal))
            : { items: [], error: '' },
          assetEligible
            ? safelyLoad(() => loadEveryPage(
              (options) => listClaimAssetSnapshots(claim.claim_id, options),
              controller.signal,
            ))
            : { items: [], error: '' },
        ])
        if (!active) return
        setResources({
          status: 'ready',
          manifestError: '',
          policies: policyResult.items,
          policyError: policyResult.error,
          assets: assetResult.items,
          assetError: assetResult.error || snapshotResult.error,
          snapshots: snapshotResult.items,
        })
      } catch (error) {
        if (!active || error?.name === 'AbortError') return
        setResources((current) => ({
          ...current,
          status: 'error',
          manifestError: error?.message || 'The Claim service did not respond.',
        }))
      }
    }

    loadSuggestions()
    return () => {
      active = false
      controller.abort()
    }
  }, [account.customer_id, account.revision, busy, claim.claim_id, claim.revision, refreshCount])

  useEffect(() => {
    setSelectedIds((current) => ({
      policy: resources.policies.some((policy) => policy.policy_id === current.policy)
        ? current.policy
        : resources.policies[0]?.policy_id || '',
      asset: resources.assets.some((asset) => asset.asset_id === current.asset)
        ? current.asset
        : resources.assets[0]?.asset_id || '',
    }))
  }, [resources.assets, resources.policies])

  const appliedPolicy = sourceReference(claim.form?.['policy.policy_number'], 'policy')
  const policyApplied = hasFieldValue(claim.form?.['policy.policy_number'])
    || resources.policies.some((policy) => (
      appliedPolicy?.id === policy.policy_id
      && appliedPolicy.revision === Number(policy.revision)
    ))
  const assetApplied = claimAlreadyHasAssetData(claim, resources.assets)
    || resources.assets.some((asset) => resources.snapshots.some((snapshot) => (
      snapshot.asset_id === asset.asset_id
      && Number(snapshot.asset_revision) === Number(asset.revision)
    )))

  const automaticSelection = useMemo(() => {
    if (resources.status !== 'ready') return null
    if (!resources.policyError && resources.policies.length === 1 && !policyApplied) {
      return { kind: 'policy', record: resources.policies[0] }
    }
    if (
      !resources.assetError
      && resources.assets.length === 1
      && !assetApplied
      && assetMatchesClaimProductFamily(claim, resources.assets[0])
    ) {
      return { kind: 'asset', record: resources.assets[0] }
    }
    return null
  }, [assetApplied, claim, policyApplied, resources])

  const choice = useMemo(() => {
    if (automaticSelection || resources.status !== 'ready') return null
    if (resources.policies.length > 1 && !policyApplied && !resources.policyError) {
      return { kind: 'policy', records: resources.policies }
    }
    if (resources.assets.length > 1 && !assetApplied && !resources.assetError) {
      return { kind: 'asset', records: resources.assets }
    }
    return null
  }, [assetApplied, automaticSelection, policyApplied, resources])

  const addNotice = useCallback((operation, alreadyAdded = false) => {
    const text = `${operation.displayName} was ${alreadyAdded ? 'already ' : ''}added to this Claim as information to review.`
    setNotices((current) => [
      ...current.filter((notice) => notice.kind !== operation.kind),
      { kind: operation.kind, text },
    ])
  }, [])

  const readLatestClaim = useCallback(async (operationRevision) => {
    const latestClaim = await getClaim(claimRef.current.claim_id)
    if (!mountedRef.current) return null
    if (latestClaim.claim_id !== claimRef.current.claim_id) {
      throw new Error('The latest Claim response did not match the active Claim.')
    }
    readbackRef.current(latestClaim, { minimumRevision: operationRevision })
    return latestClaim
  }, [])

  const operationWasApplied = useCallback(async (operation, latestClaim) => {
    if (operation.kind === 'policy') {
      const selected = sourceReference(latestClaim.form?.['policy.policy_number'], 'policy')
      return selected?.id === operation.recordId
        && selected.revision === operation.recordRevision
        && Number(latestClaim.revision) > operation.revision
    }
    try {
      const currentSnapshots = await loadEveryPage(
        (options) => listClaimAssetSnapshots(operation.claimId, options),
      )
      if (mountedRef.current) {
        setResources((current) => ({ ...current, snapshots: currentSnapshots }))
      }
      return currentSnapshots.some((snapshot) => (
        snapshot.asset_id === operation.recordId
        && Number(snapshot.asset_revision) === operation.recordRevision
        && Number(snapshot.resulting_claim_revision) > operation.revision
      ))
    } catch {
      return false
    }
  }, [])

  const runSelection = useCallback(async (operation) => {
    setPendingKind(operation.kind)
    setFailure(null)
    busyChangeRef.current(true)
    try {
      const response = operation.kind === 'policy'
        ? await selectClaimPolicy({
          claimId: operation.claimId,
          revision: operation.revision,
          policyId: operation.recordId,
          idempotencyKey: operation.idempotencyKey,
        })
        : await selectClaimAsset({
          claimId: operation.claimId,
          revision: operation.revision,
          assetId: operation.recordId,
          idempotencyKey: operation.idempotencyKey,
        })
      await readLatestClaim(response.revision)
      if (mountedRef.current) addNotice(operation)
    } catch (error) {
      if (!mountedRef.current) return
      let latestClaim = null
      try {
        latestClaim = await readLatestClaim(0)
      } catch { /* an ambiguous operation must retain its original request identity */ }
      if (!mountedRef.current) return

      if (latestClaim && await operationWasApplied(operation, latestClaim)) {
        addNotice(operation, true)
      } else if (!latestClaim || !error?.status || error?.code === 'NETWORK_ERROR') {
        setFailure({
          message: unknownOutcomeMessage(error, operation.kind),
          operation,
          retryLabel: 'Retry the same selection',
        })
      } else if (Number(latestClaim.revision) === operation.revision) {
        setFailure({
          message: `${operation.displayName} was not added. ${error?.message || 'The Claim service did not complete the request.'}`,
          operation,
          retryLabel: 'Retry the same selection',
        })
      } else {
        setFailure({
          message: `The Claim changed before ${operation.displayName} could be added. The latest Claim is now shown.`,
          operation: {
            ...operation,
            revision: Number(latestClaim.revision),
            idempotencyKey: requestId(`claim-${operation.kind}-selection`),
          },
          retryLabel: 'Try with the latest Claim',
        })
      }
    } finally {
      if (mountedRef.current) {
        setPendingKind('')
        busyChangeRef.current(false)
      }
    }
  }, [addNotice, operationWasApplied, readLatestClaim])

  const makeOperation = useCallback((kind, record) => ({
    kind,
    recordId: kind === 'policy' ? record.policy_id : record.asset_id,
    recordRevision: Number(record.revision),
    displayName: kind === 'policy' ? policyLabel(record) : record.display_name,
    claimId: claimRef.current.claim_id,
    revision: Number(claimRef.current.revision),
    idempotencyKey: requestId(`claim-${kind}-selection`),
  }), [])

  useEffect(() => {
    if (!automaticSelection || busy || pendingKind || failure) return
    const fingerprint = selectionFingerprint(
      automaticSelection.kind,
      automaticSelection.record,
    )
    if (attemptedAutomaticSelections.current.has(fingerprint)) return
    attemptedAutomaticSelections.current.add(fingerprint)
    runSelection(makeOperation(automaticSelection.kind, automaticSelection.record))
  }, [automaticSelection, busy, failure, makeOperation, pendingKind, runSelection])

  const error = resources.manifestError
    ? `Saved details could not be checked. ${resources.manifestError}`
    : resources.policyError
      ? `Saved policies could not be loaded. ${resources.policyError}`
      : resources.assetError
        ? `Saved assets could not be loaded safely. ${resources.assetError}`
        : ''
  const hasPresentation = Boolean(error || failure || notices.length || choice)

  useEffect(() => {
    if (hasPresentation) presentationRef.current?.scrollIntoView?.({ block: 'nearest' })
  }, [choice?.kind, error, failure, hasPresentation, notices.length])

  const needsClaimant = Boolean(error || failure || choice)
  useEffect(() => {
    // The workspace offers saved details as a chip only while the claimant has
    // something to choose or fix; a plain notice stays in the panel.
    onPresenceChange(needsClaimant)
  }, [needsClaimant, onPresenceChange])

  if (!hasPresentation) return null

  const selectedRecords = choice?.kind === 'policy' ? resources.policies : resources.assets
  const selectedId = choice ? selectedIds[choice.kind] : ''
  const selectedRecord = choice?.kind === 'policy'
    ? selectedRecords.find((record) => record.policy_id === selectedId)
    : selectedRecords.find((record) => record.asset_id === selectedId)

  function chooseRecord() {
    if (!choice || !selectedRecord || pendingKind || busy) return
    setFailure(null)
    runSelection(makeOperation(choice.kind, selectedRecord))
  }

  return (
    <div className="claim-autofill-inline" ref={presentationRef}>
      {notices.length > 0 && (
        <div className="claim-autofill-inline-notice" role="status">
          <span aria-hidden="true">✓</span>
          <span>{notices.map((notice) => notice.text).join(' ')}</span>
        </div>
      )}

      {choice && (
        <section className="claim-autofill-inline-choice" aria-labelledby={`${choiceId}-title`}>
          <div className="claim-autofill-inline-copy">
            <strong id={`${choiceId}-title`}>
              {choice.kind === 'policy'
                ? 'Which saved policy applies to this Claim?'
                : 'Which saved asset is involved in this Claim?'}
            </strong>
            <span>It will be added as information for you to review.</span>
          </div>
          <label className="claim-autofill-choice-label" htmlFor={choiceId}>
            {choice.kind === 'policy' ? 'Saved policy' : 'Saved asset'}
          </label>
          <select
            id={choiceId}
            value={selectedId}
            disabled={Boolean(pendingKind) || busy}
            onChange={(event) => {
              setSelectedIds((current) => ({
                ...current,
                [choice.kind]: event.target.value,
              }))
              setFailure(null)
            }}
          >
            {selectedRecords.map((record) => (
              <option
                key={choice.kind === 'policy' ? record.policy_id : record.asset_id}
                value={choice.kind === 'policy' ? record.policy_id : record.asset_id}
              >
                {choice.kind === 'policy'
                  ? policyLabel(record)
                  : `${record.display_name} — ${assetTypeLabel(record.asset_type)}`}
              </option>
            ))}
          </select>
          <button
            className="secondary-button"
            type="button"
            disabled={!selectedRecord || Boolean(pendingKind) || busy}
            onClick={chooseRecord}
          >
            {pendingKind === choice.kind ? 'Adding…' : 'Add for review'}
          </button>
        </section>
      )}

      {(error || failure) && (
        <div className="claim-autofill-inline-error" role="alert">
          <span>{failure?.message || error}</span>
          <button
            className="secondary-button"
            type="button"
            disabled={Boolean(pendingKind) || busy}
            onClick={() => {
              if (failure?.operation) runSelection(failure.operation)
              else setRefreshCount((count) => count + 1)
            }}
          >
            {failure?.retryLabel || 'Retry'}
          </button>
        </div>
      )}
    </div>
  )
}
