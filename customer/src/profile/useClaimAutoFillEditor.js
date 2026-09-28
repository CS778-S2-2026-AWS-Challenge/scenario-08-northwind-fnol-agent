import { useState } from 'react'

import { profileMutationMessage } from './profileMutation.js'

export const CLAIM_AUTO_FILL_CATEGORIES = [
  { key: 'personal_details', label: 'Personal details' },
  { key: 'policy_number', label: 'Policy number' },
  { key: 'saved_assets', label: 'Saved assets' },
  { key: 'payment_details', label: 'Payment details' },
  { key: 'identity_information', label: 'Identity information' },
]

export function claimAutoFillDraftFromAccount(account) {
  return Object.fromEntries(CLAIM_AUTO_FILL_CATEGORIES.map(({ key }) => [
    key,
    Boolean(account?.claim_auto_fill_preferences?.[key]),
  ]))
}

export default function useClaimAutoFillEditor({ account, onSave }) {
  const available = CLAIM_AUTO_FILL_CATEGORIES.every(({ key }) => (
    Object.hasOwn(account?.claim_auto_fill_preferences || {}, key)
  ))
  const accountKey = account?.customer_id || null
  const authoritativeDraft = claimAutoFillDraftFromAccount(account)
  const [editor, setEditor] = useState(() => ({
    accountKey,
    changes: {},
    saving: false,
    error: '',
    notice: '',
  }))
  const activeEditor = editor.accountKey === accountKey
    ? editor
    : { accountKey, changes: {}, saving: false, error: '', notice: '' }
  const draft = { ...authoritativeDraft, ...activeEditor.changes }
  const dirty = Object.keys(activeEditor.changes).length > 0

  const choices = CLAIM_AUTO_FILL_CATEGORIES.map(({ key, label }) => ({
    key,
    label,
    visible: draft[key],
  }))

  function changeChoice(key, visible) {
    if (!available) return
    setEditor((current) => {
      const changes = current.accountKey === accountKey ? { ...current.changes } : {}
      if (visible === authoritativeDraft[key]) delete changes[key]
      else changes[key] = visible
      return { accountKey, changes, saving: false, error: '', notice: '' }
    })
  }

  async function saveChoices() {
    if (!available || !dirty || activeEditor.saving) return
    setEditor((current) => ({
      ...(current.accountKey === accountKey ? current : activeEditor),
      saving: true,
      error: '',
      notice: '',
    }))
    try {
      const updated = await onSave(draft)
      setEditor({
        accountKey: updated?.customer_id || accountKey,
        changes: {},
        saving: false,
        error: '',
        notice: 'Claim auto-fill choices were updated in your saved Northwind account.',
      })
    } catch (requestError) {
      setEditor((current) => ({
        ...(current.accountKey === accountKey ? current : activeEditor),
        saving: false,
        error: profileMutationMessage(
          requestError,
          'Northwind could not update your Claim auto-fill choices. Your draft is still here; review it and try again.',
        ),
        notice: '',
      }))
    }
  }

  function reset() {
    setEditor({ accountKey: null, changes: {}, saving: false, error: '', notice: '' })
  }

  return {
    available,
    choices: available ? choices : null,
    dirty,
    error: activeEditor.error,
    notice: activeEditor.notice,
    saving: activeEditor.saving,
    changeChoice,
    reset,
    saveChoices,
  }
}
