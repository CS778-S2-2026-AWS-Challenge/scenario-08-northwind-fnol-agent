import { useEffect, useRef, useState } from 'react'

import { profileMutationMessage } from './profileMutation.js'
import { FeatureNotice, ResourceError, SectionHeading, SummaryRow } from './ProfilePrimitives.jsx'

const ASSET_CATEGORIES = [
  { key: 'vehicle', label: 'Vehicles', singular: 'vehicle', addLabel: 'Add vehicle' },
  { key: 'property', label: 'Properties', singular: 'property', addLabel: 'Add property' },
  { key: 'contents', label: 'Valuable items', singular: 'item', addLabel: 'Add item' },
]

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
      setError(profileMutationMessage(requestError, 'Northwind could not save this asset.'))
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
            <AssetField inputRef={firstInputRef} id={`${idPrefix}-registration`} label="Registration plate" required autoCapitalize="characters" {...fieldProps('registration')} />
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

function AssetDetail({ asset, busy, editing, headingAs: Heading, onBack, onEdit, onSave, onCancelEdit }) {
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
        <AssetEditor key={asset.asset_id} asset={asset} assetType={asset.asset_type} busy={busy} onCancel={onCancelEdit} onSave={onSave} />
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

export default function AssetsSection({
  resource,
  pending,
  headingAs: Heading = 'h1',
  onBeginCreate,
  onAbandonCreate,
  onCreate,
  onReload,
  onUpdate,
}) {
  const assets = resource.items
  const [notice, setNotice] = useState(null)
  const [selectedCategory, setSelectedCategory] = useState(null)
  const [selectedAssetId, setSelectedAssetId] = useState(null)
  const [editor, setEditor] = useState(null)
  const selectedAsset = assets?.find((asset) => asset.asset_id === selectedAssetId) || null

  function cancelCreate() {
    if (editor?.mode === 'create') onAbandonCreate('asset', editor.attemptId)
    setEditor(null)
  }

  async function createAsset(assetType, payload) {
    const created = await onCreate({ asset: { asset_type: assetType, ...payload }, attemptId: editor.attemptId })
    setEditor(null)
    setSelectedCategory(assetType)
    if (created?.asset_id) setSelectedAssetId(created.asset_id)
    setNotice({ kind: 'success', text: `${payload.display_name} was added to your saved assets.` })
  }

  async function updateAsset(asset, payload) {
    const updated = await onUpdate(asset.asset_id, asset.revision, payload)
    setEditor(null)
    if (updated?.asset_id) setSelectedAssetId(updated.asset_id)
    setNotice({ kind: 'success', text: `${payload.display_name} was updated in your saved assets.` })
  }

  if (selectedAsset) {
    return (
      <section className="profile-section" aria-label="Asset details">
        <FeatureNotice notice={notice} />
        <AssetDetail
          asset={selectedAsset}
          busy={Boolean(pending[`asset:${selectedAsset.asset_id}`])}
          editing={editor?.mode === 'edit'}
          headingAs={Heading}
          onBack={() => { setEditor(null); setSelectedAssetId(null) }}
          onCancelEdit={() => setEditor(null)}
          onEdit={() => { setNotice(null); setEditor({ mode: 'edit', type: selectedAsset.asset_type }) }}
          onSave={(payload) => updateAsset(selectedAsset, payload)}
        />
      </section>
    )
  }

  const category = categoryFor(selectedCategory)
  if (category) {
    const categoryAssets = (assets || []).filter((asset) => asset.asset_type === category.key)
    const ready = assets !== null && !resource.error
    const creating = editor?.mode === 'create' && editor.type === category.key
    return (
      <section className="profile-section" aria-labelledby={`profile-assets-${category.key}-title`}>
        <FeatureNotice notice={notice} />
        <button className="profile-asset-back" type="button" onClick={() => { cancelCreate(); setNotice(null); setSelectedCategory(null) }}>
          <span aria-hidden="true">←</span> Back to Insured assets
        </button>
        <header className="profile-asset-category-page-header">
          <div>
            <Heading id={`profile-assets-${category.key}-title`}>{category.label}</Heading>
            <p>{resource.error ? 'Saved assets unavailable' : assets === null ? 'Loading saved assets' : `${categoryAssets.length} saved`}</p>
          </div>
          <button
            className="profile-asset-add-action"
            type="button"
            disabled={!ready}
            aria-expanded={creating}
            onClick={() => {
              cancelCreate()
              setNotice(null)
              setEditor({ mode: 'create', type: category.key, attemptId: onBeginCreate('asset') })
            }}
          >
            <span aria-hidden="true">+</span> {category.addLabel}
          </button>
        </header>
        <ResourceError message={resource.error} onRetry={onReload} />
        {assets === null && !resource.error && <p className="profile-assets-loading" role="status">Loading saved assets…</p>}
        {creating && (
          <AssetEditor
            key={editor.attemptId}
            assetType={category.key}
            busy={Boolean(pending['asset-create'])}
            onCancel={cancelCreate}
            onSave={(payload) => createAsset(category.key, payload)}
          />
        )}
        {ready && categoryAssets.length === 0 && !creating && <p className="profile-assets-empty">No saved {category.label.toLowerCase()} yet.</p>}
        {categoryAssets.length > 0 && (
          <div className="profile-asset-list" aria-label={`Saved ${category.label.toLowerCase()}`}>
            {categoryAssets.map((asset) => (
              <button
                className="profile-asset-list-row"
                type="button"
                key={asset.asset_id}
                aria-label={`Open ${asset.display_name}`}
                onClick={() => { setNotice(null); cancelCreate(); setSelectedAssetId(asset.asset_id) }}
              >
                <span className="profile-asset-list-copy"><strong>{asset.display_name}</strong><span>{assetSecondaryText(asset)}</span></span>
                <span className="profile-asset-list-updated">Updated {formatAssetDate(asset.updated_at)}</span>
                <span className="profile-asset-list-chevron" aria-hidden="true">›</span>
              </button>
            ))}
          </div>
        )}
      </section>
    )
  }

  return (
    <section className="profile-section" aria-labelledby="profile-insured-assets">
      <FeatureNotice notice={notice} />
      <SectionHeading as={Heading} id="profile-insured-assets" title="Insured assets" description="Review the vehicles, properties, and valuable items saved to your Profile." />
      <ResourceError message={resource.error} onRetry={onReload} />
      {assets === null && !resource.error && <p className="profile-assets-loading" role="status">Loading saved assets…</p>}
      <div className="profile-category-list" aria-label="Insured asset categories">
        {ASSET_CATEGORIES.map((assetCategory) => {
          const count = (assets || []).filter((asset) => asset.asset_type === assetCategory.key).length
          const countLabel = resource.error ? 'Needs attention' : assets === null ? 'Loading' : `${count} saved`
          return (
            <button
              className="profile-asset-category-row"
              type="button"
              key={assetCategory.key}
              onClick={() => { setEditor(null); setNotice(null); setSelectedCategory(assetCategory.key) }}
            >
              <span className="profile-asset-category-label">{assetCategory.label}</span>
              <span className="profile-asset-category-count">{countLabel}</span>
              <span className="profile-asset-chevron" aria-hidden="true">›</span>
            </button>
          )
        })}
      </div>
    </section>
  )
}
