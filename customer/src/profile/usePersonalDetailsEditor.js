import { useEffect, useState } from 'react'

import { profileMutationMessage } from './profileMutation.js'

export function profileDraftFromAccount(account) {
  const profile = account.profile || {}
  return {
    preferredName: profile.preferred_name || '',
    legalName: profile.legal_name || '',
    dateOfBirth: profile.date_of_birth || '',
    email: profile.email || '',
    phone: profile.phone || '',
    residentialAddress: profile.residential_address || '',
  }
}

export default function usePersonalDetailsEditor({ account, onSaveProfile, onSavePreferences }) {
  const [activeEditor, setActiveEditor] = useState(null)
  const [detailsDirty, setDetailsDirty] = useState(false)
  const [preferencesDirty, setPreferencesDirty] = useState(false)
  const [detailDraft, setDetailDraft] = useState(() => profileDraftFromAccount(account))
  const [preferenceDraft, setPreferenceDraft] = useState({
    email: Boolean(account.preferences?.email),
    sms: Boolean(account.preferences?.sms),
  })
  const [notice, setNotice] = useState(null)
  const [saving, setSaving] = useState(false)
  const [returnFocus, setReturnFocus] = useState(null)

  useEffect(() => {
    if (activeEditor || !returnFocus) return
    globalThis.document?.getElementById(
      returnFocus === 'profile' ? 'profile-edit-button' : 'profile-personal-edit-button',
    )?.focus()
  }, [activeEditor, returnFocus])

  function resetDrafts() {
    setDetailDraft(profileDraftFromAccount(account))
    setPreferenceDraft({
      email: Boolean(account.preferences?.email),
      sms: Boolean(account.preferences?.sms),
    })
    setDetailsDirty(false)
    setPreferencesDirty(false)
  }

  function closeEditor() {
    resetDrafts()
    setActiveEditor(null)
    setNotice(null)
  }

  function openEditor(editor) {
    if (activeEditor !== editor) resetDrafts()
    setReturnFocus(null)
    setActiveEditor(editor)
    setNotice(null)
  }

  function changeDetail(field, value) {
    setDetailDraft((current) => ({ ...current, [field]: value }))
    setDetailsDirty(true)
  }

  function choosePreference(preference) {
    setPreferenceDraft({ email: preference === 'email', sms: preference === 'sms' })
    setPreferencesDirty(true)
  }

  async function saveDetails(event) {
    event.preventDefault()
    if (saving) return
    const savedEditor = activeEditor
    const payload = activeEditor === 'personal'
      ? {
        legal_name: detailDraft.legalName.trim(),
        date_of_birth: detailDraft.dateOfBirth || null,
        email: detailDraft.email.trim(),
        phone: detailDraft.phone.trim(),
        residential_address: detailDraft.residentialAddress.trim() || null,
      }
      : {
        preferred_name: detailDraft.preferredName.trim() || null,
      }
    setSaving(true)
    setNotice(null)
    try {
      const updated = await onSaveProfile(payload)
      setDetailDraft(profileDraftFromAccount(updated))
      setDetailsDirty(false)
      setActiveEditor(null)
      setReturnFocus(savedEditor)
      setNotice({ kind: 'success', text: 'Profile information was updated in your saved Northwind account.' })
    } catch (error) {
      setNotice({
        kind: 'error',
        text: profileMutationMessage(error, 'Northwind could not update these details.'),
      })
    } finally {
      setSaving(false)
    }
  }

  async function savePreferences(event) {
    event.preventDefault()
    if (saving) return
    setSaving(true)
    setNotice(null)
    try {
      const updated = await onSavePreferences(preferenceDraft)
      setPreferenceDraft({
        email: Boolean(updated.preferences.email),
        sms: Boolean(updated.preferences.sms),
      })
      setPreferencesDirty(false)
      setActiveEditor(null)
      setReturnFocus('personal')
      setNotice({ kind: 'success', text: 'Contact preferences were updated in your saved Northwind account.' })
    } catch (error) {
      setNotice({
        kind: 'error',
        text: profileMutationMessage(error, 'Northwind could not update these preferences.'),
      })
    } finally {
      setSaving(false)
    }
  }

  return {
    activeEditor,
    changeDetail,
    choosePreference,
    closeEditor,
    detailDraft,
    detailsDirty,
    notice,
    openEditor,
    preferenceDraft,
    preferencesDirty,
    saveDetails,
    savePreferences,
    saving,
  }
}
