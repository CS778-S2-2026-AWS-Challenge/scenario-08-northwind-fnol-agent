import { useState } from 'react'

import {
  claimReviewRequirements,
  claimReviewSectionId,
  claimReviewSections,
} from '../claimReviewProjection.js'
import './ClaimReviewPanel.css'

const ATTENTION_QUESTIONS = {
  'incident.occurred_at': 'When did it happen?',
  'incident.discovered_at': 'When did you discover it?',
  'incident.location': 'Where did it happen?',
  'incident.description': 'What happened?',
  'incident.injury_or_danger': 'Was anyone injured or in immediate danger?',
  'loss.description': 'What was damaged or lost?',
  'parties.other_parties': 'Was anyone else involved?',
  'vehicle.damage_description': 'What should we record for vehicle damage?',
  'vehicle.drivable': 'Is the vehicle safe to drive?',
  'vehicle.registration': 'What is the vehicle registration?',
  'property.address': 'Which property was affected?',
  'property.habitable': 'Is the property safe to live in?',
  'property.ongoing_risk': 'Is there an ongoing risk at the property?',
  'policy.policy_number': 'What is your policy number?',
}

const SAFETY_FIELDS = new Set([
  'incident.injury_or_danger',
  'property.habitable',
  'property.ongoing_risk',
  'vehicle.drivable',
  'vehicle.towing_required',
])

function attentionQuestion(fieldCode, fieldLabel) {
  return ATTENTION_QUESTIONS[fieldCode] || `What should we record for ${fieldLabel(fieldCode).toLowerCase()}?`
}

function sentence(value) {
  const text = String(value || '').trim()
  if (!text) return ''
  return /[.!?]$/.test(text) ? text : `${text}.`
}

function readableValue(field, fieldValueText) {
  if (!field) return ''
  if (field.value && typeof field.value === 'object' && !Array.isArray(field.value)) {
    const preferred = field.value.claimant_wording
      || field.value.formatted
      || field.value.address
      || field.value.name
    if (preferred) return String(preferred)
    return Object.values(field.value).filter((value) => (
      typeof value === 'string' || typeof value === 'number'
    )).join(', ')
  }
  if (Array.isArray(field.value)) return field.value.join(', ')
  return fieldValueText(field)
}

function fieldHasValue(field) {
  if (!field || field.status === 'missing') return false
  if (field.value === false || field.value === 0) return true
  if (Array.isArray(field.value)) return field.value.length > 0
  if (field.value && typeof field.value === 'object') return Object.keys(field.value).length > 0
  return String(field.value ?? '').trim().length > 0
}

function fieldFor(section, fieldCode) {
  return section.fields.find(([code]) => code === fieldCode)?.[1]
}

function claimTypeName(value) {
  const normalized = String(value || '').trim().toLowerCase().replaceAll('_', ' ')
  if (['motor', 'vehicle', 'auto', 'car'].includes(normalized)) return 'motor vehicle claim'
  if (['home', 'property', 'house'].includes(normalized)) return 'home claim'
  if (['contents', 'personal property'].includes(normalized)) return 'contents claim'
  if (!normalized) return 'claim'
  return normalized.endsWith('claim') ? normalized : `${normalized} claim`
}

function naturalList(items) {
  if (items.length < 2) return items[0] || ''
  if (items.length === 2) return `${items[0]} and ${items[1]}`
  return `${items.slice(0, -1).join(', ')}, and ${items.at(-1)}`
}

function overviewDescription(form, requirements, conversationEmpty) {
  if (conversationEmpty || Object.keys(form || {}).length === 0) {
    return 'Tell us what happened and the Agent will build this overview as you chat.'
  }
  const outstanding = [...requirements.missingRequiredNow, ...requirements.pendingLater]
  if (outstanding.length === 0) {
    return 'The information needed to progress this claim has been captured.'
  }
  const categoryLabels = {
    overview: 'claim',
    incident: 'incident',
    loss: 'damage',
    safety: 'safety',
  }
  const categories = [...new Set(outstanding.map((fieldCode) => (
    categoryLabels[claimReviewSectionId(fieldCode)]
  )).filter(Boolean))]
    .sort((left, right) => ['claim', 'incident', 'damage', 'safety'].indexOf(left)
      - ['claim', 'incident', 'damage', 'safety'].indexOf(right))
  const needed = categories.length > 0 ? `${naturalList(categories)} details` : 'a few more details'
  return `We still need ${needed} before the claim can progress.`
}

function sectionSummary(section, fieldValueText) {
  if (section.id === 'overview') {
    const family = readableValue(fieldFor(section, 'claim.product_family'), fieldValueText)
    const policy = readableValue(fieldFor(section, 'policy.policy_number'), fieldValueText)
    if (family && policy) return `${claimTypeName(family)[0].toUpperCase()}${claimTypeName(family).slice(1)} linked to policy ${policy}.`
    if (family) return `${claimTypeName(family)[0].toUpperCase()}${claimTypeName(family).slice(1)}.`
  }

  if (section.id === 'incident') {
    const description = readableValue(fieldFor(section, 'incident.description'), fieldValueText)
    const occurredAt = readableValue(fieldFor(section, 'incident.occurred_at'), fieldValueText)
    const location = readableValue(fieldFor(section, 'incident.location'), fieldValueText)
    const details = [sentence(description)]
    if (occurredAt) details.push(`It happened ${occurredAt}.`)
    if (location) details.push(`The reported location is ${location}.`)
    if (details.some(Boolean)) return details.filter(Boolean).join(' ')
  }

  if (section.id === 'loss') {
    const loss = readableValue(fieldFor(section, 'loss.description'), fieldValueText)
      || readableValue(fieldFor(section, 'vehicle.damage_description'), fieldValueText)
    const propertyAddress = readableValue(fieldFor(section, 'property.address'), fieldValueText)
    const affectedAreas = readableValue(fieldFor(section, 'property.affected_areas'), fieldValueText)
    const itemNames = section.contentsItems.map((item) => item.description).filter(Boolean)
    const details = [sentence(loss)]
    if (propertyAddress) details.push(`The affected property is ${propertyAddress}.`)
    if (affectedAreas) details.push(`Affected area: ${affectedAreas}.`)
    if (itemNames.length) details.push(`${itemNames.slice(0, 2).join(' and ')} ${itemNames.length === 1 ? 'is' : 'are'} included in the loss.`)
    if (details.some(Boolean)) return details.filter(Boolean).join(' ')
  }

  if (section.id === 'safety') {
    const danger = fieldFor(section, 'incident.injury_or_danger')
    const habitable = fieldFor(section, 'property.habitable')
    const drivable = fieldFor(section, 'vehicle.drivable')
    const ongoingRisk = readableValue(fieldFor(section, 'property.ongoing_risk'), fieldValueText)
    const details = []
    if (danger?.value === false) details.push('No injuries or immediate danger were reported.')
    if (danger?.value === true) details.push('An injury or immediate danger was reported.')
    if (habitable?.value === true) details.push('The property was reported safe to live in.')
    if (habitable?.value === false) details.push('The property may not be safe to live in.')
    if (drivable?.value === true) details.push('The vehicle was reported safe to drive.')
    if (drivable?.value === false) details.push('The vehicle was reported unsafe to drive.')
    if (ongoingRisk && String(ongoingRisk).toLowerCase() !== 'none') {
      details.push(`Ongoing risk: ${String(ongoingRisk).replaceAll('_', ' ')}.`)
    }
    if (details.length) return details.join(' ')
  }

  const firstValue = section.fields
    .map(([, field]) => readableValue(field, fieldValueText))
    .find(Boolean)
  return firstValue ? sentence(firstValue) : ''
}

function statusMeta(status) {
  if (status === 'confirmed') return { icon: '✓', label: 'Confirmed', tone: 'confirmed' }
  if (status === 'proposed') return { icon: '◇', label: 'Needs review', tone: 'review' }
  if (status === 'disputed') return { icon: '!', label: 'Conflict', tone: 'risk' }
  return { icon: '○', label: 'Recorded', tone: 'neutral' }
}

function sectionStatus(section) {
  const records = [...section.fields.map(([, field]) => field), ...section.contentsItems]
  if (records.some((item) => item.status === 'disputed')) return { icon: '!', label: 'Conflict', tone: 'risk' }
  if (records.some((item) => item.status === 'proposed')) return { icon: '◇', label: 'Needs review', tone: 'review' }
  if (records.length > 0 && records.every((item) => item.status === 'confirmed')) {
    return { icon: '✓', label: 'Confirmed', tone: 'confirmed' }
  }
  return { icon: '○', label: 'Recorded', tone: 'neutral' }
}

function reviewSnapshot(form, contentsItems) {
  const fields = Object.fromEntries(
    Object.entries(form || {}).map(([fieldCode, field]) => [fieldCode, JSON.stringify(field)]),
  )
  const contents = JSON.stringify(contentsItems || [])
  return { fields, contents, key: JSON.stringify([fields, contents]) }
}

function changedReviewSections(previous, next) {
  const changedSections = new Set()
  const fieldCodes = new Set([...Object.keys(previous.fields), ...Object.keys(next.fields)])
  for (const fieldCode of fieldCodes) {
    if (previous.fields[fieldCode] !== next.fields[fieldCode]) {
      changedSections.add(claimReviewSectionId(fieldCode))
    }
  }
  if (previous.contents !== next.contents) changedSections.add('loss')
  return changedSections
}

function sectionRenderKey(section) {
  return `${section.id}:${JSON.stringify([section.fields, section.contentsItems])}`
}

function FieldEditor({ fieldCode, field, fieldLabel, editValue, setEditValue, cancelEdit, saveFieldCorrection, busy, status }) {
  return (
    <div className="summary-field-editor">
      <label htmlFor={`summary-field-${fieldCode}`}>{fieldLabel(fieldCode)}</label>
      <textarea
        id={`summary-field-${fieldCode}`}
        aria-label={`Correct ${fieldLabel(fieldCode)}`}
        value={editValue}
        onChange={(event) => setEditValue(event.target.value)}
        rows="3"
        autoFocus
      />
      <div className="summary-field-actions">
        <button className="summary-quiet-action" type="button" onClick={cancelEdit} disabled={busy}>Cancel</button>
        <button
          className="summary-save-action"
          type="button"
          onClick={() => saveFieldCorrection(fieldCode, field || { value: null, status: 'missing' })}
          disabled={!editValue.trim() || busy}
        >
          {status === 'saving' ? 'Saving…' : 'Save correction'}
        </button>
      </div>
    </div>
  )
}

function claimProgressStats(form, contentsItems, dynamicForm) {
  const requirements = claimReviewRequirements(dynamicForm)
  const fallbackComplete = [...Object.values(form || {}), ...(contentsItems || [])]
    .filter((item) => item.status === 'confirmed').length
  const fallbackTotal = new Set([
    ...Object.keys(form || {}),
    ...requirements.missingRequiredNow,
  ]).size + (contentsItems || []).length
  const complete = requirements.currentActionSatisfied ?? fallbackComplete
  const total = requirements.currentActionTotal ?? fallbackTotal
  return {
    complete: Math.min(complete, total),
    maximum: Math.max(total, 1),
    requirements,
    total,
  }
}

export function ClaimSummaryProgress({ form, contentsItems, dynamicForm }) {
  const { complete, maximum, total } = claimProgressStats(form, contentsItems, dynamicForm)

  return (
    <section className="claim-summary-progress" aria-label="Claim information progress">
      <div className="claim-summary-progress-copy">
        <strong>{total > 0 ? `${complete} of ${total} completed` : 'Ready to capture details'}</strong>
        <span className="claim-summary-save-state">
          <span className="claim-summary-save-dot" aria-hidden="true" />
          <span>Saved automatically</span>
        </span>
      </div>
      <div
        className="claim-summary-progress-track"
        role="progressbar"
        aria-label="Claim details captured"
        aria-valuemin="0"
        aria-valuemax={maximum}
        aria-valuenow={Math.min(complete, maximum)}
      >
        <span style={{ width: `${Math.min((complete / maximum) * 100, 100)}%` }} />
      </div>
    </section>
  )
}

export function ClaimNextStepsPanel({
  form,
  dynamicForm,
  fieldLabel,
  editingField,
  editValue,
  setEditValue,
  beginEdit,
  cancelEdit,
  saveFieldCorrection,
  busy,
  status,
}) {
  const requirements = claimReviewRequirements(dynamicForm)
  const [taskEditor, setTaskEditor] = useState(null)
  const currentCodes = new Set(requirements.missingRequiredNow)
  const tasks = [
    ...requirements.missingRequiredNow.map((fieldCode) => ({ fieldCode, current: true })),
    ...requirements.pendingLater
      .filter((fieldCode) => !currentCodes.has(fieldCode))
      .map((fieldCode) => ({ fieldCode, current: false })),
  ]
  const safetyChecks = tasks.filter(({ fieldCode }) => SAFETY_FIELDS.has(fieldCode))
  const incidentDetails = tasks.filter(({ fieldCode }) => !SAFETY_FIELDS.has(fieldCode))
  const completed = Object.entries(form || {}).filter(([, field]) => field.status === 'confirmed' && fieldHasValue(field))

  function renderTask({ fieldCode }) {
    return (
      <li key={fieldCode}>
        {editingField === fieldCode && taskEditor === fieldCode ? (
          <FieldEditor
            fieldCode={fieldCode}
            field={form[fieldCode]}
            fieldLabel={fieldLabel}
            editValue={editValue}
            setEditValue={setEditValue}
            cancelEdit={() => {
              setTaskEditor(null)
              cancelEdit()
            }}
            saveFieldCorrection={(nextFieldCode, field) => {
              setTaskEditor(null)
              saveFieldCorrection(nextFieldCode, field)
            }}
            busy={busy}
            status={status}
          />
        ) : (
          <>
            <strong className="next-step-question">{attentionQuestion(fieldCode, fieldLabel)}</strong>
            <button
              type="button"
              onClick={() => {
                setTaskEditor(fieldCode)
                beginEdit(fieldCode, form[fieldCode]?.value)
              }}
              disabled={busy}
              aria-label={`Add ${attentionQuestion(fieldCode, fieldLabel)}`}
            >
              <span aria-hidden="true">+</span> Add
            </button>
          </>
        )}
      </li>
    )
  }

  function renderGroup(title, items, tone = 'standard') {
    if (items.length === 0) return null
    const headingId = `next-steps-${title.toLowerCase().replaceAll(' ', '-')}`
    return (
      <section className={`next-steps-group is-${tone}`} aria-labelledby={headingId}>
        <div className="next-steps-group-heading">
          <h3 id={headingId}>{title}</h3>
          <span>{items.length}</span>
        </div>
        <ul className="next-steps-list">{items.map(renderTask)}</ul>
      </section>
    )
  }

  return (
    <div className="next-steps-panel">
      {!requirements.available ? (
        <p className="next-steps-empty">Your next steps will appear here as the Agent understands your claim.</p>
      ) : tasks.length === 0 ? (
        <div className="next-steps-complete" role="status">
          <span aria-hidden="true">✓</span>
          <div>
            <strong>All required details are complete.</strong>
            <p>There is nothing else to add right now.</p>
          </div>
        </div>
      ) : (
        <>
          {renderGroup('Safety checks', safetyChecks, 'safety')}
          {renderGroup('Incident details', incidentDetails)}
        </>
      )}

      {completed.length > 0 && (
        <details className="next-steps-completed">
          <summary>
            <span>Completed</span>
            <span>{completed.length}</span>
          </summary>
          <ul>
            {completed.map(([fieldCode]) => (
              <li key={fieldCode}>
                <span>{fieldLabel(fieldCode)}</span>
                <span><span aria-hidden="true">✓</span> Done</span>
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  )
}

export default function ClaimReviewPanel({
  form,
  contentsItems,
  dynamicForm,
  proposedFields = [],
  proposedContentsItems = [],
  editingField,
  editValue,
  setEditValue,
  beginEdit,
  cancelEdit,
  saveFieldCorrection,
  confirmProposedFields,
  fieldLabel,
  fieldStatusLabel,
  fieldSourceLabel,
  fieldValueText,
  busy,
  status,
  conversationEmpty = false,
  onViewNextSteps,
}) {
  const requirements = claimReviewRequirements(dynamicForm)
  const capturedForm = Object.fromEntries(
    Object.entries(form || {}).filter(([, field]) => fieldHasValue(field)),
  )
  const sections = claimReviewSections(capturedForm, contentsItems)
    .filter((section) => section.fields.length > 0 || section.contentsItems.length > 0)
  const [openSections, setOpenSections] = useState(
    editingField && capturedForm[editingField] ? [claimReviewSectionId(editingField)] : [],
  )
  const nextSnapshot = reviewSnapshot(capturedForm, contentsItems)
  const [projectionUpdate, setProjectionUpdate] = useState(() => ({ snapshot: nextSnapshot, sections: new Set() }))
  if (projectionUpdate.snapshot.key !== nextSnapshot.key) {
    setProjectionUpdate({
      snapshot: nextSnapshot,
      sections: changedReviewSections(projectionUpdate.snapshot, nextSnapshot),
    })
  }
  const updatedSections = projectionUpdate.snapshot.key === nextSnapshot.key
    ? projectionUpdate.sections
    : changedReviewSections(projectionUpdate.snapshot, nextSnapshot)
  const outstandingCount = new Set([
    ...requirements.missingRequiredNow,
    ...requirements.pendingLater,
  ]).size
  const progress = claimProgressStats(capturedForm, contentsItems, dynamicForm)
  const claimType = claimTypeName(readableValue(capturedForm['claim.product_family'], fieldValueText))
  const claimTitle = `${claimType[0].toUpperCase()}${claimType.slice(1)}`
  const overviewCopy = overviewDescription(capturedForm, requirements, conversationEmpty)
  const missingSafety = [...requirements.missingRequiredNow, ...requirements.pendingLater]
    .some((fieldCode) => SAFETY_FIELDS.has(fieldCode))
  const riskFields = Object.entries(capturedForm).filter(([fieldCode, field]) => (
    (fieldCode === 'incident.injury_or_danger' && field.value === true)
    || (fieldCode === 'property.habitable' && field.value === false)
    || (fieldCode === 'vehicle.drivable' && field.value === false)
    || (fieldCode === 'property.ongoing_risk'
      && !['', 'none', 'false'].includes(String(field.value ?? '').toLowerCase()))
  ))
  const conflictFields = Object.entries(capturedForm).filter(([, field]) => field.status === 'disputed')
  const reviewCount = proposedFields.length + proposedContentsItems.length
  const firstProposedSection = proposedFields[0]
    ? claimReviewSectionId(proposedFields[0][0])
    : 'loss'
  const hasAlerts = missingSafety || riskFields.length > 0 || conflictFields.length > 0 || reviewCount > 0

  function setSectionOpen(sectionId, open) {
    setOpenSections((current) => (
      open ? [...new Set([...current, sectionId])] : current.filter((id) => id !== sectionId)
    ))
  }

  function openAlertSection(sectionId) {
    setSectionOpen(sectionId, true)
    globalThis.requestAnimationFrame?.(() => {
      document.getElementById(`claim-review-${sectionId}-panel`)?.scrollIntoView?.({ block: 'nearest' })
    })
  }

  return (
    <div className="claim-summary-content">
      <section className="claim-overview-card" aria-labelledby="claim-overview-title">
        <p className="overview-eyebrow">Claim overview</p>
        <h2 id="claim-overview-title">{claimTitle}</h2>
        <p className="claim-overview-copy">{overviewCopy}</p>
        {requirements.available && (
          <div className="claim-overview-progress">
            <strong>{progress.total > 0 ? `${progress.complete} of ${progress.total} details captured` : 'Ready to build'}</strong>
            <div
              className="claim-overview-progress-track"
              role="progressbar"
              aria-label="Overview details captured"
              aria-valuemin="0"
              aria-valuemax={progress.maximum}
              aria-valuenow={Math.min(progress.complete, progress.maximum)}
            >
              <span style={{ width: `${Math.min((progress.complete / progress.maximum) * 100, 100)}%` }} />
            </div>
            <div className="claim-overview-next">
              <span>
                {outstandingCount === 0
                  ? 'All required details captured'
                  : `${outstandingCount} ${outstandingCount === 1 ? 'detail' : 'details'} remaining`}
              </span>
              {outstandingCount > 0 && (
                <button type="button" onClick={onViewNextSteps}>
                  View <span aria-hidden="true">→</span>
                </button>
              )}
            </div>
          </div>
        )}
      </section>

      {sections.length > 0 && (
        <section className="overview-known" aria-labelledby="what-we-know-title">
          <h2 id="what-we-know-title">What we know</h2>
          <div className="claim-known-list">
            {sections.map((section) => {
              const isOpen = openSections.includes(section.id)
              const sectionState = sectionStatus(section)
              const sectionHasReview = section.fields.some(([, field]) => field.status === 'proposed')
                || section.contentsItems.some((item) => item.status === 'proposed')
              return (
                <section
                  className={`claim-known-row state-${sectionState.tone} ${updatedSections.has(section.id) ? 'is-updated' : ''}`}
                  key={sectionRenderKey(section)}
                >
                  <div className="claim-known-row-heading">
                    <h3>
                      <button
                        className="claim-known-toggle"
                        type="button"
                        aria-expanded={isOpen}
                        aria-controls={`claim-review-${section.id}-panel`}
                        onClick={() => setSectionOpen(section.id, !isOpen)}
                      >
                        <span className="claim-known-copy">
                          <span className="claim-known-label">{section.title}</span>
                          <span className="claim-summary-sentence">{sectionSummary(section, fieldValueText)}</span>
                        </span>
                        <span className={`summary-status state-${sectionState.tone}`} aria-label={sectionState.label}>
                          <span aria-hidden="true">{sectionState.icon}</span>
                          {sectionState.tone !== 'confirmed' && <span>{sectionState.label}</span>}
                        </span>
                        <svg className="claim-known-chevron" viewBox="0 0 20 20" aria-hidden="true">
                          <path d="m7 8 3 3 3-3" />
                        </svg>
                      </button>
                    </h3>
                    <button
                      className="claim-summary-edit"
                      type="button"
                      aria-label={`Edit ${section.title}`}
                      title={`Edit ${section.title}`}
                      onClick={() => setSectionOpen(section.id, true)}
                    >
                      <svg viewBox="0 0 20 20" aria-hidden="true">
                        <path d="M4 14.5V16h1.5L15 6.5 13.5 5 4 14.5Z" />
                        <path d="m12.5 6 1.5 1.5" />
                      </svg>
                    </button>
                  </div>
                  <div id={`claim-review-${section.id}-panel`} hidden={!isOpen} className="claim-summary-card-details">
                    <p className="claim-summary-edit-hint">Select a detail to update it. Sources and review status are shown below.</p>
                    {section.fields.map(([fieldCode, field]) => {
                      const fieldState = statusMeta(field.status)
                      return editingField === fieldCode ? (
                        <FieldEditor
                          key={fieldCode}
                          fieldCode={fieldCode}
                          field={field}
                          fieldLabel={fieldLabel}
                          editValue={editValue}
                          setEditValue={setEditValue}
                          cancelEdit={cancelEdit}
                          saveFieldCorrection={saveFieldCorrection}
                          busy={busy}
                          status={status}
                        />
                      ) : (
                        <button
                          className="claim-summary-detail"
                          type="button"
                          key={fieldCode}
                          onClick={() => beginEdit(fieldCode, field.value)}
                          disabled={busy}
                          aria-label={`Edit ${fieldLabel(fieldCode)}`}
                        >
                          <span className="claim-summary-detail-heading">
                            <span>{fieldLabel(fieldCode)}</span>
                            <span className={`summary-status state-${fieldState.tone}`}>
                              <span aria-hidden="true">{fieldState.icon}</span>
                              {fieldStatusLabel(field.status)}
                            </span>
                          </span>
                          <strong>{readableValue(field, fieldValueText)}</strong>
                          <small>{fieldSourceLabel(field.source)}</small>
                        </button>
                      )
                    })}
                    {section.contentsItems.map((item) => {
                      const itemState = statusMeta(item.status)
                      return (
                        <div className="claim-summary-detail is-read-only" key={item.item_id}>
                          <span className="claim-summary-detail-heading">
                            <span>Insured item</span>
                            <span className={`summary-status state-${itemState.tone}`}>
                              <span aria-hidden="true">{itemState.icon}</span>
                              {fieldStatusLabel(item.status)}
                            </span>
                          </span>
                          <strong>{item.description}</strong>
                          <small>{item.category ? `${item.category} · ` : ''}{fieldSourceLabel(item.source)}</small>
                        </div>
                      )
                    })}
                    {sectionHasReview && (
                      <button
                        className="summary-confirm-action"
                        type="button"
                        onClick={confirmProposedFields}
                        disabled={busy}
                      >
                        {status === 'confirming' ? 'Confirming…' : 'Confirm suggested details'}
                      </button>
                    )}
                  </div>
                </section>
              )
            })}
          </div>
        </section>
      )}

      {hasAlerts && (
        <section className="overview-alerts" aria-labelledby="needs-review-title">
          <h2 id="needs-review-title">Needs review</h2>
          <div className="overview-alert-list">
            {missingSafety && (
              <div className="overview-alert is-attention">
                <span aria-hidden="true">!</span>
                <strong>Safety information has not been confirmed.</strong>
                <button type="button" onClick={onViewNextSteps}>Review</button>
              </div>
            )}
            {riskFields.length > 0 && (
              <div className="overview-alert is-risk">
                <span aria-hidden="true">!</span>
                <strong>{riskFields.length === 1 ? 'A safety risk was reported.' : `${riskFields.length} safety risks were reported.`}</strong>
                <button type="button" onClick={() => openAlertSection('safety')}>Review</button>
              </div>
            )}
            {conflictFields.length > 0 && (
              <div className="overview-alert is-risk">
                <span aria-hidden="true">!</span>
                <strong>{conflictFields.length === 1 ? 'One detail has conflicting information.' : `${conflictFields.length} details have conflicting information.`}</strong>
                <button type="button" onClick={() => openAlertSection(claimReviewSectionId(conflictFields[0][0]))}>Review</button>
              </div>
            )}
            {reviewCount > 0 && editingField === null && (
              <div className="overview-alert is-review">
                <span aria-hidden="true">◇</span>
                <strong>{reviewCount} Agent-suggested {reviewCount === 1 ? 'detail needs' : 'details need'} your review.</strong>
                <button type="button" onClick={() => openAlertSection(firstProposedSection)}>Review</button>
              </div>
            )}
          </div>
        </section>
      )}
    </div>
  )
}
