import { useEffect, useRef, useState } from 'react'

import { PROFILE_CATEGORIES } from '../profileRoutes.js'

const ASSET_CATEGORIES = [
  { key: 'vehicle', label: 'Vehicles', singular: 'vehicle', addLabel: 'Add vehicle' },
  { key: 'property', label: 'Properties', singular: 'property', addLabel: 'Add property' },
  { key: 'contents', label: 'Valuable items', singular: 'item', addLabel: 'Add item' },
]

function maskEmail(value = '') {
  const [local, domain] = value.split('@')
  if (!local || !domain) return value ? '••••' : 'Not provided'
  return `${local.slice(0, 1)}•••@${domain}`
}

function maskPhone(value = '') {
  const digits = value.replace(/\D/g, '')
  if (!digits) return 'Not provided'
  return `••• ••• ${digits.slice(-3).padStart(3, '•')}`
}

function initials(value = '') {
  const parts = value.trim().split(/\s+/).filter(Boolean)
  return (parts.slice(0, 2).map((part) => part[0]).join('') || 'NW').toUpperCase()
}

function contactPreference(preferences = {}) {
  const enabled = []
  if (preferences.email) enabled.push('Email')
  if (preferences.sms) enabled.push('SMS')
  return enabled.join(' and ') || 'Not provided'
}

function formatAssetDate(value) {
  const date = new Date(value)
  if (!value || Number.isNaN(date.getTime())) return 'Not recorded'
  return new Intl.DateTimeFormat('en-NZ', {
    day: 'numeric', month: 'short', year: 'numeric', timeZone: 'Pacific/Auckland',
  }).format(date)
}

function categoryFor(assetType) {
  return ASSET_CATEGORIES.find(({ key }) => key === assetType)
}

function assetTypeLabel(assetType) {
  const singular = categoryFor(assetType)?.singular || 'asset'
  return `${singular.slice(0, 1).toUpperCase()}${singular.slice(1)}`
}

function assetSecondaryText(asset) {
  const details = asset.details || {}
  if (asset.asset_type === 'vehicle') {
    return [details.year, details.make, details.model].filter(Boolean).join(' ') || 'Vehicle'
  }
  if (asset.asset_type === 'property') return details.address || 'Property'
  return [details.brand, details.model].filter(Boolean).join(' ') || details.description || 'Valuable item'
}

function optionalText(value) {
  const cleaned = String(value || '').trim()
  return cleaned || undefined
}

function vehicleDisplayName(draft) {
  const nickname = optionalText(draft.displayName)
  if (nickname) return nickname

  const makeAndModel = [optionalText(draft.make), optionalText(draft.model)].filter(Boolean).join(' ')
  return makeAndModel || draft.registration.trim()
}

function draftForAsset(assetType, asset = null) {
  const details = asset?.details || {}
  return {
    displayName: asset?.display_name || '',
    registration: details.registration || '',
    registeredOwner: details.registered_owner || '',
    make: details.make || '',
    model: details.model || '',
    year: details.year ? String(details.year) : '',
    address: details.address || '',
    ownerName: details.owner_name || '',
    propertyType: details.property_type || '',
    description: details.description || '',
    category: details.category || '',
    brand: details.brand || '',
  }
}

function payloadFromDraft(assetType, draft) {
  if (assetType === 'vehicle') {
    return {
      display_name: vehicleDisplayName(draft),
      details: {
        registration: draft.registration.trim(),
        ...(optionalText(draft.registeredOwner) ? { registered_owner: optionalText(draft.registeredOwner) } : {}),
        ...(optionalText(draft.make) ? { make: optionalText(draft.make) } : {}),
        ...(optionalText(draft.model) ? { model: optionalText(draft.model) } : {}),
        ...(draft.year ? { year: Number(draft.year) } : {}),
      },
    }
  }
  if (assetType === 'property') {
    return {
      display_name: draft.displayName.trim(),
      details: {
        address: draft.address.trim(),
        ...(optionalText(draft.ownerName) ? { owner_name: optionalText(draft.ownerName) } : {}),
        ...(optionalText(draft.propertyType) ? { property_type: optionalText(draft.propertyType) } : {}),
      },
    }
  }
  return {
    display_name: draft.displayName.trim(),
    details: {
      description: draft.description.trim(),
      ...(optionalText(draft.category) ? { category: optionalText(draft.category) } : {}),
      ...(optionalText(draft.brand) ? { brand: optionalText(draft.brand) } : {}),
      ...(optionalText(draft.model) ? { model: optionalText(draft.model) } : {}),
    },
  }
}

function SummaryRow({ label, value }) {
  return <div className="profile-summary-row"><dt>{label}</dt><dd>{value}</dd></div>
}

function ProfileHeader({ account, editing, onEdit }) {
  return (
    <header className="profile-header">
      <div className="profile-avatar" aria-hidden="true">{initials(account.profile.display_name)}</div>
      <div className="profile-header-copy">
        <span className="profile-account-name-label">Preferred name</span>
        <strong>{account.profile.display_name}</strong>
        <p className="profile-header-meta">
          <span>Policy number</span><span aria-hidden="true">·</span><span>Unavailable</span>
        </p>
      </div>
      <button
        className="profile-quiet-action"
        type="button"
        aria-expanded={editing}
        aria-controls="profile-header-editor"
        onClick={onEdit}
      >
        {editing ? 'Done' : 'Edit profile'}
      </button>
    </header>
  )
}

function ProfileNavigation({ activeSection, onOpenClaims, onSelectSection, mobile = false }) {
  return (
    <nav className={`profile-category-nav ${mobile ? 'is-mobile-index' : ''}`} aria-label="Profile navigation">
      <ul>
        {PROFILE_CATEGORIES.map(({ key, label }) => {
          const selected = !mobile && activeSection === key
          return (
            <li key={key}>
              <button
                className={selected ? 'is-active' : ''}
                type="button"
                aria-current={selected ? 'page' : undefined}
                onClick={() => onSelectSection(key)}
              >
                <span>{label}</span><span aria-hidden="true">›</span>
              </button>
            </li>
          )
        })}
        {onOpenClaims && (
          <li className="profile-claim-history-link">
            <button type="button" onClick={onOpenClaims}>
              <span>Claim history</span><span aria-hidden="true">›</span>
            </button>
          </li>
        )}
      </ul>
    </nav>
  )
}

function SectionHeading({ as: Heading = 'h2', id, title, description }) {
  return (
    <header className="profile-section-heading">
      <div><Heading id={id}>{title}</Heading>{description && <p>{description}</p>}</div>
    </header>
  )
}

function UnavailableSection({ headingAs, id, title, description, children }) {
  return (
    <section className="profile-section" aria-labelledby={id}>
      <SectionHeading as={headingAs} id={id} title={title} description={description} />
      <div className="profile-availability-note">
        <strong>Unavailable</strong>
        <p>This information is not supported by the current account service.</p>
      </div>
      {children}
    </section>
  )
}

function AssetField({ id, inputRef, label, optional = false, ...inputProps }) {
  return (
    <div className="profile-asset-field">
      <label htmlFor={id}>{label} {optional && <span>(optional)</span>}</label>
      <input ref={inputRef} id={id} maxLength="200" {...inputProps} />
    </div>
  )
}

function AssetEditor({ asset = null, assetType, busy, onCancel, onSave }) {
  const [draft, setDraft] = useState(() => draftForAsset(assetType, asset))
  const [error, setError] = useState('')
  const firstInputRef = useRef(null)
  const editing = Boolean(asset)
  const category = categoryFor(assetType)
  const idPrefix = `asset-${editing ? asset.asset_id : assetType}`

  useEffect(() => { firstInputRef.current?.focus() }, [])

  function fieldProps(field) {
    return {
      value: draft[field],
      onChange: (event) => setDraft((current) => ({ ...current, [field]: event.target.value })),
    }
  }

  async function submitAsset(event) {
    event.preventDefault()
    setError('')
    try {
      await onSave(payloadFromDraft(assetType, draft))
    } catch (requestError) {
      setError(`${requestError.message || 'Northwind could not save this asset.'} Your changes were not saved. Review the details and try again.`)
    }
  }

  return (
    <form className="profile-edit-form profile-asset-editor" onSubmit={submitAsset}>
      <header className="profile-asset-editor-heading">
        <div>
          <h3>{editing ? `Edit ${category.singular}` : category.addLabel}</h3>
          <p>Only information supported by your Northwind Profile is stored here.</p>
        </div>
      </header>

      <div className="profile-asset-form-group">
        <h4>{assetType === 'vehicle' ? 'Vehicle details' : 'Overview'}</h4>
        {assetType === 'vehicle' ? (
          <>
            <AssetField
              inputRef={firstInputRef}
              id={`${idPrefix}-registration`}
              label="Registration plate"
              required
              autoCapitalize="characters"
              {...fieldProps('registration')}
            />
            <div className="profile-asset-field-grid">
              <AssetField id={`${idPrefix}-make`} label="Make" optional {...fieldProps('make')} />
              <AssetField id={`${idPrefix}-model`} label="Model" optional {...fieldProps('model')} />
              <AssetField id={`${idPrefix}-year`} label="Year" optional type="number" min="1886" max="2200" maxLength={undefined} {...fieldProps('year')} />
            </div>
            <AssetField id={`${idPrefix}-name`} label="Vehicle type/name" optional {...fieldProps('displayName')} />
          </>
        ) : (
          <>
            <AssetField inputRef={firstInputRef} id={`${idPrefix}-name`} label="Asset name" required {...fieldProps('displayName')} />
            {assetType === 'property' && (
              <>
                <AssetField id={`${idPrefix}-address`} label="Property address" required {...fieldProps('address')} />
                <AssetField id={`${idPrefix}-type`} label="Property type" optional {...fieldProps('propertyType')} />
              </>
            )}
            {assetType === 'contents' && (
              <>
                <AssetField id={`${idPrefix}-description`} label="Description" required {...fieldProps('description')} />
                <div className="profile-asset-field-grid">
                  <AssetField id={`${idPrefix}-category`} label="Category" optional {...fieldProps('category')} />
                  <AssetField id={`${idPrefix}-brand`} label="Brand" optional {...fieldProps('brand')} />
                  <AssetField id={`${idPrefix}-model`} label="Model" optional {...fieldProps('model')} />
                </div>
              </>
            )}
          </>
        )}
      </div>

      {(assetType === 'vehicle' || assetType === 'property') && (
        <div className="profile-asset-form-group">
          <h4>Ownership</h4>
          {assetType === 'vehicle'
            ? <AssetField id={`${idPrefix}-owner`} label="Registered owner name" optional {...fieldProps('registeredOwner')} />
            : <AssetField id={`${idPrefix}-owner`} label="Owner name" optional {...fieldProps('ownerName')} />}
        </div>
      )}

      {error && <p className="profile-form-error" role="alert">{error}</p>}
      <div className="profile-asset-form-actions">
        <button className="primary-button" type="submit" disabled={busy}>{busy ? 'Saving…' : 'Save asset'}</button>
        <button className="profile-quiet-action" type="button" disabled={busy} onClick={onCancel}>Cancel</button>
      </div>
    </form>
  )
}

function AssetDetail({ asset, busy, editing, headingAs: Heading = 'h2', onBack, onEdit, onSave, onCancelEdit }) {
  const details = asset.details || {}
  const owner = asset.asset_type === 'vehicle'
    ? details.registered_owner
    : asset.asset_type === 'property' ? details.owner_name : null

  return (
    <div className="profile-asset-detail">
      <button className="profile-asset-back" type="button" onClick={onBack}>
        <span aria-hidden="true">←</span> Back to {categoryFor(asset.asset_type)?.label}
      </button>
      <header className="profile-asset-detail-header">
        <div>
          <p>{assetTypeLabel(asset.asset_type)}</p>
          <Heading>{asset.display_name}</Heading>
          <span>Last updated {formatAssetDate(asset.updated_at)}</span>
        </div>
        {!editing && <button className="profile-quiet-action" type="button" onClick={onEdit}>Edit asset</button>}
      </header>

      {editing ? (
        <AssetEditor
          key={`${asset.asset_id}-${asset.revision}`}
          asset={asset}
          assetType={asset.asset_type}
          busy={busy}
          onCancel={onCancelEdit}
          onSave={onSave}
        />
      ) : (
        <div className="profile-asset-detail-sections">
          <section aria-labelledby="asset-overview-heading">
            <h3 id="asset-overview-heading">Overview</h3>
            <dl className="profile-summary-list">
              <SummaryRow label="Asset type" value={assetTypeLabel(asset.asset_type)} />
              {asset.asset_type === 'vehicle' && <SummaryRow label="Registration" value={details.registration} />}
              {asset.asset_type === 'vehicle' && <SummaryRow label="Make and model" value={[details.make, details.model].filter(Boolean).join(' ') || 'Not provided'} />}
              {asset.asset_type === 'vehicle' && <SummaryRow label="Year" value={details.year || 'Not provided'} />}
              {asset.asset_type === 'property' && <SummaryRow label="Address" value={details.address} />}
              {asset.asset_type === 'property' && <SummaryRow label="Property type" value={details.property_type || 'Not provided'} />}
              {asset.asset_type === 'contents' && <SummaryRow label="Description" value={details.description} />}
              {asset.asset_type === 'contents' && <SummaryRow label="Category" value={details.category || 'Not provided'} />}
              {asset.asset_type === 'contents' && <SummaryRow label="Brand and model" value={[details.brand, details.model].filter(Boolean).join(' ') || 'Not provided'} />}
            </dl>
          </section>
          <section aria-labelledby="asset-ownership-heading">
            <h3 id="asset-ownership-heading">Ownership &amp; insurance</h3>
            <dl className="profile-summary-list">
              <SummaryRow label="Recorded owner" value={owner || 'Not provided'} />
              <SummaryRow label="Policy association" value="Not linked in Profile" />
            </dl>
          </section>
          <section aria-labelledby="asset-documents-heading">
            <h3 id="asset-documents-heading">Photos &amp; documents</h3>
            <p>Asset-level files are not stored in Profile. Add supporting files to a claim when they are needed.</p>
          </section>
          <section aria-labelledby="asset-notes-heading">
            <h3 id="asset-notes-heading">Notes</h3>
            <p>Notes are not stored for saved Profile assets.</p>
          </section>
        </div>
      )}
    </div>
  )
}

export default function UserProfile({
  account,
  assets = null,
  assetsError = '',
  activeSection = null,
  embedded = false,
  busy = false,
  onCreateAsset = async () => null,
  onOpenClaims,
  onReloadAssets = async () => [],
  onSaveProfile,
  onSavePreferences,
  onSelectSection = () => {},
  onSignOut,
  onUpdateAsset = async () => null,
}) {
  const [activeEditor, setActiveEditor] = useState(null)
  const [detailsDirty, setDetailsDirty] = useState(false)
  const [preferencesDirty, setPreferencesDirty] = useState(false)
  const [detailDraft, setDetailDraft] = useState({
    displayName: account.profile.display_name,
    phone: account.profile.phone || '',
  })
  const [preferenceDraft, setPreferenceDraft] = useState({
    email: Boolean(account.preferences.email),
    sms: Boolean(account.preferences.sms),
  })
  const [notice, setNotice] = useState(null)
  const [selectedAssetCategory, setSelectedAssetCategory] = useState(null)
  const [selectedAssetId, setSelectedAssetId] = useState(null)
  const [assetEditor, setAssetEditor] = useState(null)
  const detailInputRef = useRef(null)
  const phoneInputRef = useRef(null)
  const SectionTitle = embedded ? 'h2' : 'h1'
  const currentSection = activeSection || 'personal-details'
  const selectedAsset = assets?.find((asset) => asset.asset_id === selectedAssetId) || null

  useEffect(() => {
    if (currentSection !== 'personal-details') return
    if (activeEditor === 'profile') detailInputRef.current?.focus()
    if (activeEditor === 'personal') phoneInputRef.current?.focus()
  }, [activeEditor, currentSection])

  function resetPersonalDrafts() {
    setDetailDraft({ displayName: account.profile.display_name, phone: account.profile.phone || '' })
    setPreferenceDraft({ email: Boolean(account.preferences.email), sms: Boolean(account.preferences.sms) })
    setDetailsDirty(false)
    setPreferencesDirty(false)
  }

  function closeEditor() {
    resetPersonalDrafts()
    setActiveEditor(null)
    setNotice(null)
  }

  function openEditor(editor) {
    onSelectSection('personal-details')
    if (activeEditor && activeEditor !== editor) resetPersonalDrafts()
    setActiveEditor(editor)
    setNotice(null)
  }

  function selectProfileSection(section) {
    setNotice(null)
    setSelectedAssetId(null)
    setSelectedAssetCategory(null)
    setAssetEditor(null)
    onSelectSection(section)
  }

  async function saveDetails(event) {
    event.preventDefault()
    setNotice(null)
    try {
      const updated = await onSaveProfile({
        display_name: detailDraft.displayName.trim(), phone: detailDraft.phone.trim(),
      })
      setDetailDraft({ displayName: updated.profile.display_name, phone: updated.profile.phone || '' })
      setDetailsDirty(false)
      setNotice({ kind: 'success', text: 'Profile information was updated in your saved Northwind account.' })
    } catch (error) {
      setNotice({
        kind: 'error',
        text: `${error.message || 'Northwind could not update these details.'} Your changes were not saved. Check the fields and try again.`,
      })
    }
  }

  async function savePreferences(event) {
    event.preventDefault()
    setNotice(null)
    try {
      const updated = await onSavePreferences(preferenceDraft)
      setPreferenceDraft({ email: Boolean(updated.preferences.email), sms: Boolean(updated.preferences.sms) })
      setPreferencesDirty(false)
      setNotice({ kind: 'success', text: 'Contact preferences were updated in your saved Northwind account.' })
    } catch (error) {
      setNotice({
        kind: 'error',
        text: `${error.message || 'Northwind could not update these preferences.'} Your changes were not saved. Review the choices and try again.`,
      })
    }
  }

  async function createAsset(assetType, payload) {
    const created = await onCreateAsset({ asset_type: assetType, ...payload })
    setAssetEditor(null)
    setSelectedAssetCategory(assetType)
    if (created?.asset_id) setSelectedAssetId(created.asset_id)
    setNotice({ kind: 'success', text: `${payload.display_name} was added to your saved assets.` })
  }

  async function updateAsset(asset, payload) {
    const updated = await onUpdateAsset(asset.asset_id, asset.revision, payload)
    setAssetEditor(null)
    if (updated?.asset_id) setSelectedAssetId(updated.asset_id)
    setNotice({ kind: 'success', text: `${payload.display_name} was updated in your saved assets.` })
  }

  function renderPersonalDetails() {
    return (
      <section className="profile-section" aria-label="Personal details">
        <section className="profile-header-region" aria-label="Profile header">
          <ProfileHeader
            account={account}
            editing={activeEditor === 'profile'}
            onEdit={activeEditor === 'profile' ? closeEditor : () => openEditor('profile')}
          />
          {activeEditor === 'profile' && (
            <form id="profile-header-editor" className="profile-edit-form profile-header-editor" onSubmit={saveDetails}>
              <h3>Profile details</h3>
              <label htmlFor="profile-display-name">Preferred name</label>
              <input
                ref={detailInputRef}
                id="profile-display-name"
                name="display_name"
                value={detailDraft.displayName}
                maxLength="120"
                autoComplete="name"
                required
                onChange={(event) => {
                  setDetailDraft((current) => ({ ...current, displayName: event.target.value }))
                  setDetailsDirty(true)
                }}
              />
              <p className="profile-field-limit">Avatar changes are unavailable in the current account service.</p>
              <button className="primary-button" type="submit" disabled={busy || !detailsDirty}>Save profile</button>
            </form>
          )}
        </section>

        <section className="profile-personal-information" aria-labelledby="profile-personal-information-title">
          <header className="profile-personal-information-heading">
            <SectionTitle id="profile-personal-information-title">Personal information</SectionTitle>
            <button
              className="profile-quiet-action"
              type="button"
              aria-label={activeEditor === 'personal' ? 'Done editing personal information' : 'Edit personal information'}
              aria-expanded={activeEditor === 'personal'}
              aria-controls="profile-personal-editor"
              onClick={activeEditor === 'personal' ? closeEditor : () => openEditor('personal')}
            >
              {activeEditor === 'personal' ? 'Done' : 'Edit'}
            </button>
          </header>
          <dl className="profile-summary-list">
            <SummaryRow label="Legal name" value="Unavailable" />
            <SummaryRow label="Date of birth" value="Unavailable" />
            <SummaryRow label="Phone" value={maskPhone(account.profile.phone)} />
            <SummaryRow label="Email" value={maskEmail(account.profile.email)} />
            <SummaryRow label="Preferred contact" value={contactPreference(account.preferences)} />
            <SummaryRow label="Residential address" value="Unavailable" />
          </dl>
          {activeEditor === 'personal' && (
            <div id="profile-personal-editor" className="profile-personal-editor">
              <form className="profile-edit-form" onSubmit={saveDetails}>
                <h3>Contact details</h3>
                <label htmlFor="profile-phone">Phone number <span>(optional)</span></label>
                <input
                  ref={phoneInputRef}
                  id="profile-phone"
                  name="phone"
                  type="tel"
                  value={detailDraft.phone}
                  maxLength="40"
                  autoComplete="tel"
                  onChange={(event) => {
                    setDetailDraft((current) => ({ ...current, phone: event.target.value }))
                    setDetailsDirty(true)
                  }}
                />
                <p className="profile-field-limit">Legal name, date of birth, email, and address changes are unavailable in the current account service.</p>
                <button className="primary-button" type="submit" disabled={busy || !detailsDirty}>Save phone</button>
              </form>
              <form className="profile-edit-form profile-preferences-form" onSubmit={savePreferences}>
                <h3>Contact preferences</h3>
                <label className="profile-check-row">
                  <input
                    name="email"
                    type="checkbox"
                    checked={preferenceDraft.email}
                    onChange={(event) => {
                      setPreferenceDraft((current) => ({ ...current, email: event.target.checked }))
                      setPreferencesDirty(true)
                    }}
                  />
                  <span><strong>Email</strong><small>Use the saved email address for claim updates.</small></span>
                </label>
                <label className="profile-check-row">
                  <input
                    name="sms"
                    type="checkbox"
                    checked={preferenceDraft.sms}
                    onChange={(event) => {
                      setPreferenceDraft((current) => ({ ...current, sms: event.target.checked }))
                      setPreferencesDirty(true)
                    }}
                  />
                  <span><strong>SMS</strong><small>Use the saved phone number for claim updates.</small></span>
                </label>
                <button className="secondary-button" type="submit" disabled={busy || !preferencesDirty}>Save contact preferences</button>
              </form>
            </div>
          )}
        </section>
      </section>
    )
  }

  function renderAssetCategory(category) {
    const categoryAssets = (assets || []).filter((asset) => asset.asset_type === category.key)
    const countLabel = assetsError ? 'Needs attention' : assets === null ? 'Loading' : `${categoryAssets.length} saved`

    return (
      <button
        className="profile-asset-category-row"
        type="button"
        key={category.key}
        onClick={() => {
          setAssetEditor(null)
          setNotice(null)
          setSelectedAssetCategory(category.key)
        }}
      >
        <span className="profile-asset-category-label">{category.label}</span>
        <span className="profile-asset-category-count">{countLabel}</span>
        <span className="profile-asset-chevron" aria-hidden="true">›</span>
      </button>
    )
  }

  function renderAssetCategoryPage(category) {
    const categoryAssets = (assets || []).filter((asset) => asset.asset_type === category.key)
    const assetsReady = assets !== null && !assetsError
    const countLabel = assetsError ? 'Saved assets unavailable' : assets === null ? 'Loading saved assets' : `${categoryAssets.length} saved`
    const creating = assetEditor?.mode === 'create' && assetEditor.type === category.key

    return (
      <section className="profile-section" aria-labelledby={`profile-assets-${category.key}-title`}>
        <button
          className="profile-asset-back"
          type="button"
          onClick={() => {
            setNotice(null)
            setAssetEditor(null)
            setSelectedAssetCategory(null)
          }}
        >
          <span aria-hidden="true">←</span> Back to Insured assets
        </button>
        <header className="profile-asset-category-page-header">
          <div>
            <SectionTitle id={`profile-assets-${category.key}-title`}>{category.label}</SectionTitle>
            <p>{countLabel}</p>
          </div>
          <button
            className="profile-asset-add-action"
            type="button"
            disabled={!assetsReady}
            aria-expanded={creating}
            onClick={() => {
              setNotice(null)
              setAssetEditor({ mode: 'create', type: category.key })
            }}
          >
            <span aria-hidden="true">+</span> {category.addLabel}
          </button>
        </header>
        {assetsError && (
          <div className="profile-assets-error" role="alert">
            <p>{assetsError}</p>
            <button className="profile-quiet-action" type="button" onClick={() => onReloadAssets().catch(() => {})}>Try again</button>
          </div>
        )}
        {assets === null && !assetsError && <p className="profile-assets-loading" role="status">Loading saved assets…</p>}
        {creating && (
          <AssetEditor
            key={`create-${category.key}`}
            assetType={category.key}
            busy={busy}
            onCancel={() => setAssetEditor(null)}
            onSave={(payload) => createAsset(category.key, payload)}
          />
        )}
        {assetsReady && categoryAssets.length === 0 && !creating && (
          <p className="profile-assets-empty">No saved {category.label.toLowerCase()} yet.</p>
        )}
        {categoryAssets.length > 0 && (
          <div className="profile-asset-list" aria-label={`Saved ${category.label.toLowerCase()}`}>
            {categoryAssets.map((asset) => (
              <button
                className="profile-asset-list-row"
                type="button"
                key={asset.asset_id}
                aria-label={`Open ${asset.display_name}`}
                onClick={() => {
                  setNotice(null)
                  setAssetEditor(null)
                  setSelectedAssetId(asset.asset_id)
                }}
              >
                <span className="profile-asset-list-copy">
                  <strong>{asset.display_name}</strong>
                  <span>{assetSecondaryText(asset)}</span>
                </span>
                <span className="profile-asset-list-updated">Updated {formatAssetDate(asset.updated_at)}</span>
                <span className="profile-asset-list-chevron" aria-hidden="true">›</span>
              </button>
            ))}
          </div>
        )}
      </section>
    )
  }

  function renderInsuredAssets() {
    if (selectedAsset) {
      return (
        <section className="profile-section" aria-label="Asset details">
          <AssetDetail
            asset={selectedAsset}
            busy={busy}
            editing={assetEditor?.mode === 'edit'}
            headingAs={SectionTitle}
            onBack={() => { setAssetEditor(null); setSelectedAssetId(null) }}
            onCancelEdit={() => setAssetEditor(null)}
            onEdit={() => { setNotice(null); setAssetEditor({ mode: 'edit', type: selectedAsset.asset_type }) }}
            onSave={(payload) => updateAsset(selectedAsset, payload)}
          />
        </section>
      )
    }
    const category = categoryFor(selectedAssetCategory)
    if (category) return renderAssetCategoryPage(category)

    return (
      <section className="profile-section" aria-labelledby="profile-insured-assets">
        <SectionHeading
          as={SectionTitle}
          id="profile-insured-assets"
          title="Insured assets"
          description="Review the vehicles, properties, and valuable items saved to your Profile."
        />
        {assetsError && (
          <div className="profile-assets-error" role="alert">
            <p>{assetsError}</p>
            <button className="profile-quiet-action" type="button" onClick={() => onReloadAssets().catch(() => {})}>Try again</button>
          </div>
        )}
        {assets === null && !assetsError && <p className="profile-assets-loading" role="status">Loading saved assets…</p>}
        <div className="profile-category-list" aria-label="Insured asset categories">
          {ASSET_CATEGORIES.map(renderAssetCategory)}
        </div>
      </section>
    )
  }

  function renderSection() {
    if (currentSection === 'personal-details') return renderPersonalDetails()
    if (currentSection === 'insured-assets') return renderInsuredAssets()
    if (currentSection === 'payment-details') {
      return (
        <section className="profile-section" aria-labelledby="profile-payment-details">
          <SectionHeading
            as={SectionTitle}
            id="profile-payment-details"
            title="Payment details"
            description="Bank account to receive claim payments"
          />
          <dl className="profile-summary-list profile-compact-summary-list">
            <SummaryRow label="Bank" value="Unavailable" />
            <SummaryRow label="Account holder" value="Unavailable" />
            <SummaryRow label="Account number" value="Unavailable" />
          </dl>
        </section>
      )
    }
    if (currentSection === 'identity-verification') {
      return (
        <UnavailableSection
          headingAs={SectionTitle}
          id="profile-identity-verification"
          title="Identity & verification"
          description="Only add an identity document when Northwind needs it for a supported purpose."
        >
          <dl className="profile-summary-list profile-compact-summary-list">
            <SummaryRow label="Driver licence" value="Unavailable" />
            <SummaryRow label="Passport" value="Unavailable" />
          </dl>
        </UnavailableSection>
      )
    }
    return (
      <UnavailableSection
        headingAs={SectionTitle}
        id="profile-claim-auto-fill"
        title="Claim auto-fill"
        description="Choose which saved information may be suggested when you start a future claim."
      >
        <p className="profile-helper-copy">Saved Profile information may only be suggested or prefilled. You must review and confirm it before it becomes claim information.</p>
        <dl className="profile-summary-list profile-compact-summary-list">
          {['Personal details', 'Policy number', 'Saved assets', 'Payment details', 'Identity information'].map((category) => (
            <SummaryRow key={category} label={category} value="Not configured" />
          ))}
        </dl>
      </UnavailableSection>
    )
  }

  return (
    <article
      className={`user-profile ${embedded ? 'is-embedded' : ''} ${activeSection ? 'has-selected-section' : 'is-category-index'}`}
      aria-label="Profile"
    >
      {notice && (
        <p className={`profile-notice is-${notice.kind}`} role={notice.kind === 'error' ? 'alert' : 'status'} aria-live="polite">
          {notice.text}
        </p>
      )}
      <div className="profile-workspace">
        <aside className="profile-sidebar">
          <ProfileNavigation activeSection={currentSection} onOpenClaims={onOpenClaims} onSelectSection={selectProfileSection} />
        </aside>
        <section className="profile-mobile-index" aria-label="Profile overview">
          <ProfileNavigation activeSection={null} onOpenClaims={onOpenClaims} onSelectSection={selectProfileSection} mobile />
        </section>
        <div className="profile-content">
          <button className="profile-mobile-back" type="button" onClick={() => selectProfileSection(null)}>
            <span aria-hidden="true">←</span> Back to profile
          </button>
          {renderSection()}
        </div>
      </div>
      {onSignOut && (
        <footer className="profile-footer">
          <button type="button" onClick={onSignOut} disabled={busy}>Log out</button>
        </footer>
      )}
    </article>
  )
}
