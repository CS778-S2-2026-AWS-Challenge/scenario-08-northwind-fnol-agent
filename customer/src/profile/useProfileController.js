import { useCallback, useEffect, useRef, useState } from 'react'

import {
  ApiRequestError,
  createAccountAsset,
  createAccountIdentityDocument,
  createAccountPolicy,
  createPaymentDestination,
  getAuthenticatedAccount,
  listAccountAssets,
  listAccountIdentityDocuments,
  listAccountPaymentDestinations,
  listAccountPolicies,
  requestId,
  updateAccountAsset,
  updateAccountIdentityDocument,
  updateAccountPaymentDestination,
  updateAccountPolicy,
  updateAccountPreferences,
  updateAccountProfile,
} from '../api.js'
import { ProfileMutationError } from './profileMutation.js'

export { ProfileMutationError, profileMutationMessage } from './profileMutation.js'

const RESOURCE_CONFIG = {
  assets: {
    id: 'asset_id',
    label: 'saved assets',
    list: listAccountAssets,
  },
  policies: {
    id: 'policy_id',
    label: 'saved policy numbers',
    list: listAccountPolicies,
  },
  payments: {
    id: 'payment_destination_id',
    label: 'saved payment details',
    list: listAccountPaymentDestinations,
  },
  identities: {
    id: 'identity_id',
    label: 'saved identity documents',
    list: listAccountIdentityDocuments,
  },
}

function emptyResource() {
  return { items: null, error: '', loading: false, stale: false }
}

function initialResources() {
  return Object.fromEntries(Object.keys(RESOURCE_CONFIG).map((name) => [name, emptyResource()]))
}

async function readAllRecords(config, signal) {
  const records = new Map()
  const seenCursors = new Set()
  let cursor = null

  do {
    const response = await config.list({ cursor, signal })
    for (const item of response.items) records.set(item[config.id], item)
    const nextCursor = response.page?.next_cursor || null
    if (nextCursor && seenCursors.has(nextCursor)) {
      throw new ApiRequestError(
        `Northwind returned an invalid page while loading ${config.label}. Reload the Profile and try again.`,
        { code: 'INVALID_PAGINATION' },
      )
    }
    if (nextCursor) seenCursors.add(nextCursor)
    cursor = nextCursor
  } while (cursor)

  return [...records.values()]
}

function loadFailureMessage(error, label) {
  if (error?.status === 401) {
    return `Your session expired while Northwind was loading ${label}. Sign in again, then reopen Profile.`
  }
  if (error?.code === 'NETWORK_ERROR') {
    return `Northwind could not load ${label} because the connection was lost. Check your connection and try again.`
  }
  return `${error?.message || `Northwind could not load ${label}.`} Reload this section and try again.`
}

function normalizedProfileValue(key, value) {
  if (value == null) return null
  if (key === 'email') return String(value).trim().toLowerCase()
  if (typeof value === 'string') return value.trim()
  return value
}

function accountMatchesProfile(account, patch) {
  return Object.entries(patch).every(([key, value]) => (
    normalizedProfileValue(key, account.profile?.[key]) === normalizedProfileValue(key, value)
  ))
}

function accountMatchesPreferences(account, preferences) {
  return Boolean(account.preferences?.email) === Boolean(preferences.email)
    && Boolean(account.preferences?.sms) === Boolean(preferences.sms)
}

function objectContains(actual, expected) {
  if (expected === null || typeof expected !== 'object') return actual === expected
  return Object.entries(expected).every(([key, value]) => objectContains(actual?.[key], value))
}

export default function useProfileController({ account, setAccount, enabled = true }) {
  const accountKey = account?.customer_id || (account ? 'authenticated-account' : null)
  const [resources, setResources] = useState(initialResources)
  const [pending, setPending] = useState({})
  const resourcesRef = useRef(resources)
  const accountRef = useRef(account)
  const loadControllersRef = useRef(new Map())
  const createKeysRef = useRef(new Map())
  resourcesRef.current = resources
  accountRef.current = account

  const setPendingScope = useCallback((scope, active) => {
    setPending((current) => {
      if (active) return { ...current, [scope]: true }
      const next = { ...current }
      delete next[scope]
      return next
    })
  }, [])

  const loadResource = useCallback(async (name, { preserveItems = false } = {}) => {
    const config = RESOURCE_CONFIG[name]
    loadControllersRef.current.get(name)?.abort()
    const controller = new AbortController()
    loadControllersRef.current.set(name, controller)
    const previousItems = resourcesRef.current[name]?.items
    setResources((current) => ({
      ...current,
      [name]: {
        ...current[name],
        items: preserveItems ? current[name].items : null,
        error: '',
        loading: true,
        stale: preserveItems ? current[name].stale : false,
      },
    }))
    try {
      const items = await readAllRecords(config, controller.signal)
      if (controller.signal.aborted) return previousItems || []
      setResources((current) => ({
        ...current,
        [name]: { items, error: '', loading: false, stale: false },
      }))
      return items
    } catch (error) {
      if (controller.signal.aborted) throw error
      setResources((current) => ({
        ...current,
        [name]: {
          items: preserveItems ? current[name].items : null,
          error: loadFailureMessage(error, config.label),
          loading: false,
          stale: preserveItems && current[name].items !== null,
        },
      }))
      throw error
    } finally {
      if (loadControllersRef.current.get(name) === controller) {
        loadControllersRef.current.delete(name)
      }
    }
  }, [])

  useEffect(() => {
    const loadControllers = loadControllersRef.current
    for (const controller of loadControllers.values()) controller.abort()
    loadControllers.clear()
    if (!accountKey) {
      setResources(initialResources())
      createKeysRef.current.clear()
      return undefined
    }
    if (!enabled) return undefined
    for (const name of Object.keys(RESOURCE_CONFIG)) {
      void loadResource(name).catch(() => {})
    }
    return () => {
      for (const controller of loadControllers.values()) controller.abort()
      loadControllers.clear()
    }
  }, [accountKey, enabled, loadResource])

  const reloadAccount = useCallback(async () => {
    const latest = await getAuthenticatedAccount()
    accountRef.current = latest
    setAccount(latest)
    return latest
  }, [setAccount])

  const runAccountMutation = useCallback(async ({ scope, action, execute, matches }) => {
    setPendingScope(scope, true)
    try {
      const updated = await execute()
      accountRef.current = updated
      setAccount(updated)
      return updated
    } catch (error) {
      const revisionConflict = error?.code === 'REVISION_CONFLICT'
      const unknownOutcome = error?.code === 'NETWORK_ERROR'
      if (!revisionConflict && !unknownOutcome) throw error

      let latest
      try {
        latest = await reloadAccount()
      } catch (reloadError) {
        throw new ProfileMutationError(
          `Northwind could not confirm whether ${action} was saved because the connection was interrupted and the latest account could not be reloaded. Your draft is still here; reconnect and reload Profile before trying again.`,
          { code: error?.code, kind: 'unknown', cause: reloadError },
        )
      }
      if (unknownOutcome && matches(latest)) return latest
      if (revisionConflict) {
        throw new ProfileMutationError(
          `Your saved account changed after this editor opened. Northwind reloaded the latest values and kept your draft. Review what changed before saving again.`,
          { code: error.code, kind: 'conflict', cause: error },
        )
      }
      throw new ProfileMutationError(
        `Northwind reloaded your account after the connection was lost but could not confirm that ${action} was saved. Your draft is still here; review the latest saved values and retry when ready.`,
        { code: error.code, kind: 'unknown', cause: error },
      )
    } finally {
      setPendingScope(scope, false)
    }
  }, [reloadAccount, setAccount, setPendingScope])

  const upsertResource = useCallback((name, record) => {
    const idField = RESOURCE_CONFIG[name].id
    setResources((current) => {
      const items = current[name].items || []
      const nextItems = items.some((item) => item[idField] === record[idField])
        ? items.map((item) => item[idField] === record[idField] ? record : item)
        : [record, ...items]
      return { ...current, [name]: { items: nextItems, error: '', loading: false, stale: false } }
    })
  }, [])

  const runResourceMutation = useCallback(async ({
    scope,
    resource,
    action,
    execute,
    reconcile,
    recoverUnknown,
  }) => {
    const before = resourcesRef.current[resource].items || []
    setPendingScope(scope, true)
    try {
      const saved = await execute()
      upsertResource(resource, saved)
      return saved
    } catch (error) {
      const revisionConflict = error?.code === 'REVISION_CONFLICT'
      const changedResource = error?.status === 404
      const unknownOutcome = error?.code === 'NETWORK_ERROR'
      if (!revisionConflict && !changedResource && !unknownOutcome) throw error

      let outcomeError = error
      if (unknownOutcome && recoverUnknown) {
        try {
          const recovered = await recoverUnknown()
          upsertResource(resource, recovered)
          return recovered
        } catch (recoveryError) {
          if (recoveryError?.code !== 'NETWORK_ERROR') throw recoveryError
          outcomeError = recoveryError
        }
      }

      let latest
      try {
        latest = await loadResource(resource, { preserveItems: true })
      } catch (reloadError) {
        throw new ProfileMutationError(
          `Northwind could not confirm whether ${action} completed because the connection was interrupted and the latest ${RESOURCE_CONFIG[resource].label} could not be loaded. Your draft is still here; reconnect and refresh before trying again.`,
          { code: error?.code, kind: 'unknown', cause: reloadError },
        )
      }
      if (unknownOutcome) {
        const reconciled = reconcile?.(latest, before)
        if (reconciled) return reconciled
        throw new ProfileMutationError(
          `Northwind reloaded ${RESOURCE_CONFIG[resource].label} after the connection was lost but could not confirm that ${action} completed. Your draft is still here; review the latest saved list and retry when ready.`,
          { code: outcomeError.code, kind: 'unknown', cause: outcomeError },
        )
      }
      throw new ProfileMutationError(
        `This saved record changed or is no longer available. Northwind reloaded the latest list and kept your draft. Review the current record before saving again.`,
        { code: error?.code || 'RESOURCE_CHANGED', kind: 'conflict', cause: error },
      )
    } finally {
      setPendingScope(scope, false)
    }
  }, [loadResource, setPendingScope, upsertResource])

  const beginCreate = useCallback((resource) => {
    const attemptId = requestId(`${resource}-attempt`)
    createKeysRef.current.set(`${resource}:${attemptId}`, requestId(resource))
    return attemptId
  }, [])

  const abandonCreate = useCallback((resource, attemptId) => {
    createKeysRef.current.delete(`${resource}:${attemptId}`)
  }, [])

  const createKey = useCallback((resource, attemptId) => {
    const key = `${resource}:${attemptId}`
    if (!createKeysRef.current.has(key)) createKeysRef.current.set(key, requestId(resource))
    return createKeysRef.current.get(key)
  }, [])

  const saveProfile = useCallback((patch) => runAccountMutation({
    scope: 'profile',
    action: 'your Profile change',
    execute: () => accountRef.current?.revision == null
      ? updateAccountProfile(patch)
      : updateAccountProfile(patch, accountRef.current.revision),
    matches: (latest) => accountMatchesProfile(latest, patch),
  }), [runAccountMutation])

  const savePreferences = useCallback((preferences) => runAccountMutation({
    scope: 'preferences',
    action: 'your contact preference',
    execute: () => updateAccountPreferences(preferences, accountRef.current?.revision),
    matches: (latest) => accountMatchesPreferences(latest, preferences),
  }), [runAccountMutation])

  const createAsset = useCallback(async ({ asset, attemptId }) => {
    const saved = await runResourceMutation({
      scope: 'asset-create',
      resource: 'assets',
      action: 'the new asset',
      execute: () => createAccountAsset({ asset, idempotencyKey: createKey('asset', attemptId) }),
      reconcile: (latest, before) => {
        const previousIds = new Set(before.map((item) => item.asset_id))
        return latest.find((item) => !previousIds.has(item.asset_id) && objectContains(item, asset))
      },
    })
    abandonCreate('asset', attemptId)
    return saved
  }, [abandonCreate, createKey, runResourceMutation])

  const saveAsset = useCallback((assetId, revision, updates) => runResourceMutation({
    scope: `asset:${assetId}`,
    resource: 'assets',
    action: 'the asset update',
    execute: () => updateAccountAsset({ assetId, revision, updates }),
    reconcile: (latest) => latest.find((item) => item.asset_id === assetId && objectContains(item, updates)),
  }), [runResourceMutation])

  const createPolicy = useCallback(async ({ policyNumber, attemptId }) => {
    const normalized = policyNumber.trim()
    const create = () => createAccountPolicy({
      policyNumber: normalized,
      idempotencyKey: createKey('policy', attemptId),
    })
    const saved = await runResourceMutation({
      scope: 'policy-create',
      resource: 'policies',
      action: 'the new policy number',
      execute: create,
      recoverUnknown: create,
    })
    abandonCreate('policy', attemptId)
    return saved
  }, [abandonCreate, createKey, runResourceMutation])

  const savePolicy = useCallback((policyId, revision, policyNumber) => {
    const normalized = policyNumber.trim()
    return runResourceMutation({
      scope: `policy:${policyId}`,
      resource: 'policies',
      action: 'the policy-number update',
      execute: () => updateAccountPolicy({ policyId, revision, policyNumber: normalized }),
      reconcile: (latest) => latest.find((item) => (
        item.policy_id === policyId && item.policy_number === normalized
      )),
    })
  }, [runResourceMutation])

  const createPayment = useCallback(async ({
    accountType,
    accountNumber,
    bankName,
    accountHolderName,
    attemptId,
  }) => {
    const idempotencyKey = createKey('payment', attemptId)
    const create = () => createPaymentDestination({
      accountType,
      accountNumber,
      bankName,
      accountHolderName,
      idempotencyKey,
    })
    const saved = await runResourceMutation({
      scope: 'payment-create',
      resource: 'payments',
      action: 'the Claim payment destination save',
      execute: create,
      recoverUnknown: create,
    })
    abandonCreate('payment', attemptId)
    return saved
  }, [abandonCreate, createKey, runResourceMutation])

  const savePayment = useCallback((paymentDestinationId, revision, updates) => {
    const projectedUpdates = {
      ...(updates.accountType !== undefined ? { account_type: updates.accountType } : {}),
      ...(updates.bankName !== undefined ? { bank_name: updates.bankName } : {}),
      ...(updates.accountHolderName !== undefined
        ? { account_holder_name: updates.accountHolderName }
        : {}),
      ...(updates.isCommon !== undefined ? { is_common: updates.isCommon } : {}),
    }
    return runResourceMutation({
      scope: `payment:${paymentDestinationId}`,
      resource: 'payments',
      action: 'the Claim payment destination update',
      execute: () => updateAccountPaymentDestination({
        paymentDestinationId,
        revision,
        ...updates,
      }),
      reconcile: updates.accountNumber === undefined
        ? (latest) => latest.find((item) => (
          item.payment_destination_id === paymentDestinationId
          && objectContains(item, projectedUpdates)
        ))
        : undefined,
    })
  }, [runResourceMutation])

  const createIdentity = useCallback(async ({ documentType, documentNumber, attemptId }) => {
    const idempotencyKey = createKey('identity', attemptId)
    const create = () => createAccountIdentityDocument({
      documentType,
      documentNumber,
      idempotencyKey,
    })
    const saved = await runResourceMutation({
      scope: 'identity-create',
      resource: 'identities',
      action: 'the identity-document save',
      execute: create,
      recoverUnknown: create,
    })
    abandonCreate('identity', attemptId)
    return saved
  }, [abandonCreate, createKey, runResourceMutation])

  const saveIdentity = useCallback((identityId, revision, documentNumber) => runResourceMutation({
    scope: `identity:${identityId}`,
    resource: 'identities',
    action: 'the identity-document update',
    execute: () => updateAccountIdentityDocument({ identityId, revision, documentNumber }),
  }), [runResourceMutation])

  return {
    resources,
    pending,
    beginCreate,
    abandonCreate,
    saveProfile,
    savePreferences,
    createAsset,
    saveAsset,
    createPolicy,
    savePolicy,
    createPayment,
    savePayment,
    createIdentity,
    saveIdentity,
    reloadAssets: () => loadResource('assets', { preserveItems: true }),
    reloadPolicies: () => loadResource('policies', { preserveItems: true }),
    reloadPayments: () => loadResource('payments', { preserveItems: true }),
    reloadIdentities: () => loadResource('identities', { preserveItems: true }),
  }
}
