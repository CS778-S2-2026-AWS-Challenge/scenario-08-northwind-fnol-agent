import { useEffect, useRef, useState } from 'react'
import {
  ApiRequestError,
  completeEvidenceUpload, createClaim, createExternalClaim, getClaim,
  getClaimEvidence,
  requestEvidenceUpload, requestId, submitClaimMessage, updateClaimFields,
  registerPendingEvidence, uploadEvidenceContent,
} from './api.js'

const STORAGE_KEY = 'northwind-guided-motor-draft'
const DECLARATION_VERSION = 'guided-motor-prototype-v1'
const MONTH_NAMES = ['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December']
const WEEKDAYS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun']
const MATERIALS = [
  { key: 'incident_image', title: 'Photos of the incident or damage', help: 'Add clear photos showing the vehicle damage, the scene, or anything else that helps explain what happened.', accept: 'image/jpeg,image/png', formats: 'JPG or PNG' },
  { key: 'police_report', title: 'Police report', help: 'Add the report supplied by Police, if one was created. You can provide it later if it is not ready yet.', accept: 'application/pdf,image/jpeg,image/png', formats: 'PDF, JPG or PNG' },
  { key: 'repair_quote', title: 'Repair quote or receipt', help: 'Add an estimate, invoice, or receipt from a repairer. This is optional at the reporting stage.', accept: 'application/pdf,image/jpeg,image/png', formats: 'PDF, JPG or PNG' },
  { key: 'other_document', title: 'Other supporting document', help: 'Add another document that may help Northwind understand or progress your claim.', accept: 'application/pdf,image/jpeg,image/png', formats: 'PDF, JPG or PNG' },
]

const EMPTY = {
  policyNumber: '', role: 'policyholder', contactPreference: 'email',
  occurredAt: '', location: '', description: '', lossDescription: '',
  registration: '', damageDescription: '',
}

function EnglishDatePicker({ value, onChange }) {
  const initial = value ? new Date(`${value}T12:00:00`) : new Date()
  const [open, setOpen] = useState(false)
  const [view, setView] = useState(new Date(initial.getFullYear(), initial.getMonth(), 1))
  const pickerRef = useRef(null)
  const triggerRef = useRef(null)
  const year = view.getFullYear(); const month = view.getMonth()
  const leading = (new Date(year, month, 1).getDay() + 6) % 7
  const days = new Date(year, month + 1, 0).getDate()
  const cells = [...Array(leading).fill(null), ...Array.from({ length: days }, (_, index) => index + 1)]
  function select(day) {
    const selected = `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}`
    onChange(selected); setOpen(false)
  }
  useEffect(() => {
    if (!open) return undefined
    function closeOutside(event) {
      if (!pickerRef.current?.contains(event.target)) setOpen(false)
    }
    function closeWithEscape(event) {
      if (event.key === 'Escape') {
        setOpen(false)
        triggerRef.current?.focus()
      }
    }
    document.addEventListener('pointerdown', closeOutside)
    document.addEventListener('keydown', closeWithEscape)
    return () => {
      document.removeEventListener('pointerdown', closeOutside)
      document.removeEventListener('keydown', closeWithEscape)
    }
  }, [open])
  return <div className="english-date-picker" ref={pickerRef}>
    <button ref={triggerRef} className="date-trigger" type="button" aria-haspopup="dialog" aria-expanded={open} onClick={() => setOpen(!open)}>
      {value ? new Intl.DateTimeFormat('en-NZ', { day: 'numeric', month: 'long', year: 'numeric', timeZone: 'UTC' }).format(new Date(`${value}T00:00:00Z`)) : 'Choose a date'}
    </button>
    {open && <div className="calendar-popover" role="dialog" aria-label="Choose incident date">
      <div className="calendar-heading"><button type="button" aria-label="Previous month" onClick={() => setView(new Date(year, month - 1, 1))}>‹</button><strong>{MONTH_NAMES[month]} {year}</strong><button type="button" aria-label="Next month" onClick={() => setView(new Date(year, month + 1, 1))}>›</button></div>
      <div className="calendar-grid">{WEEKDAYS.map((day) => <span className="weekday" key={day}>{day}</span>)}{cells.map((day, index) => day ? <button type="button" key={day} className={value === `${year}-${String(month + 1).padStart(2, '0')}-${String(day).padStart(2, '0')}` ? 'selected' : ''} onClick={() => select(day)}>{day}</button> : <span key={`empty-${index}`} />)}</div>
    </div>}
  </div>
}

export default function GuidedMotorClaim({ initialDescription = '', onExit }) {
  const saved = (() => { try { return JSON.parse(localStorage.getItem(STORAGE_KEY)) } catch { return null } })()
  const [step, setStep] = useState(saved?.step || 1)
  const [draft, setDraft] = useState(saved?.draft || { ...EMPTY, description: initialDescription })
  const [claimRef, setClaimRef] = useState(saved?.claimRef || null)
  const [files, setFiles] = useState({})
  const [uploaded, setUploaded] = useState(saved?.uploaded || [])
  const [accepted, setAccepted] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [result, setResult] = useState(null)

  useEffect(() => {
    if (!result) localStorage.setItem(STORAGE_KEY, JSON.stringify({ step, draft, claimRef, uploaded }))
  }, [step, draft, claimRef, uploaded, result])

  function field(name) {
    return { value: draft[name], onChange: (event) => setDraft({ ...draft, [name]: event.target.value }) }
  }

  async function ensureClaim() {
    if (claimRef) {
      try {
        const current = await getClaim(claimRef.claimId)
        return { ...claimRef, current }
      } catch (requestError) {
        if (!(requestError instanceof ApiRequestError) || requestError.code !== 'RESOURCE_NOT_FOUND') throw requestError
        localStorage.removeItem(STORAGE_KEY)
        setClaimRef(null); setUploaded([])
      }
    }
    const created = await createClaim({ incidentType: 'motor', idempotencyKey: requestId('guided-claim') })
    const ref = { claimId: created.claim.claim_id, sessionId: created.session.session_id, revision: created.claim.revision }
    setClaimRef(ref)
    return ref
  }

  async function saveDetails(event) {
    event.preventDefault()
    if (!draft.occurredAt) { setError('Choose the date when the incident happened.'); return }
    setBusy(true); setError('')
    try {
      let ref = await ensureClaim()
      let current = ref.current || await getClaim(ref.claimId)
      ref = { claimId: ref.claimId, sessionId: ref.sessionId, revision: ref.revision }
      let revision = current.revision
      if (Object.keys(current.form).length === 0) {
        const turn = await submitClaimMessage({
          claimId: ref.claimId, sessionId: ref.sessionId, revision,
          text: draft.description, idempotencyKey: requestId('guided-intake'), clientMessageId: requestId('guided-message'),
        })
        revision = turn.claim_revision
        current = await getClaim(ref.claimId)
        revision = current.revision
      }
      const values = [
        ['claimant.client_number', draft.policyNumber], ['claimant.role', draft.role],
        ['claimant.contact_preference', draft.contactPreference], ['incident.type', 'motor'],
        ['incident.occurred_at', draft.occurredAt], ['incident.location', draft.location],
        ['incident.description', draft.description], ['loss.description', draft.lossDescription],
        ['vehicle.registration', draft.registration], ['vehicle.damage_description', draft.damageDescription],
      ]
      const updates = values.filter(([, value]) => value).flatMap(([field_code, value]) => {
        const existing = current.form[field_code]
        if (existing?.status === 'confirmed' && existing.value === value) return []
        return [{ field_code, value, status: 'confirmed', ...(existing?.status === 'confirmed' ? { correction_reason: 'The claimant updated this detail in the guided form.' } : {}) }]
      })
      if (updates.length) {
        const patched = await updateClaimFields({ claimId: ref.claimId, revision, updates })
        revision = patched.revision
      }
      ref = { ...ref, revision }; setClaimRef(ref); setStep(2)
    } catch (requestError) { setError(requestError.message) } finally { setBusy(false) }
  }

  async function uploadFiles() {
    setBusy(true); setError('')
    try {
      let ref = claimRef || await ensureClaim()
      const selectedFiles = Object.entries(files).filter(([, selected]) => Boolean(selected))
      const evidenceState = await getClaimEvidence(ref.claimId)
      ref = { ...ref, revision: evidenceState.revision }
      const existingKinds = new Set(evidenceState.items.map(item => item.kind))
      const selectedKinds = new Set(selectedFiles.map(([kind]) => kind))
      const expectedMaterials = MATERIALS.filter(material => material.key !== 'other_document')
      for (const material of expectedMaterials) {
        if (existingKinds.has(material.key) || selectedKinds.has(material.key)) continue
        const pending = await registerPendingEvidence({
          claimId: ref.claimId, revision: ref.revision, kind: material.key,
          note: `${material.title} was not supplied with the guided claim. The claimant can add it later.`,
        })
        ref = { ...ref, revision: pending.revision }
      }
      for (const [kind, file] of selectedFiles) {
        const requested = await requestEvidenceUpload({ claimId: ref.claimId, revision: ref.revision, file, kind })
        await uploadEvidenceContent({ upload: requested.upload, file })
        const digest = await crypto.subtle.digest('SHA-256', await file.arrayBuffer())
        const checksum = `sha256:${[...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, '0')).join('')}`
        const completed = await completeEvidenceUpload({ claimId: ref.claimId, evidenceId: requested.evidence_id, revision: requested.revision, checksum })
        ref = { ...ref, revision: completed.revision }
        setUploaded((current) => [...current, { name: file.name, status: completed.evidence.file_status }])
      }
      setClaimRef(ref); setFiles({}); setStep(3)
    } catch (requestError) { setError(requestError.message) } finally { setBusy(false) }
  }

  async function submit(event) {
    event.preventDefault(); setBusy(true); setError('')
    try {
      const current = await getClaim(claimRef.claimId)
      const declaration = await submitClaimMessage({
        claimId: claimRef.claimId, sessionId: claimRef.sessionId, revision: current.revision,
        text: `I accept declaration ${DECLARATION_VERSION} and confirm the information is true and complete to the best of my knowledge.`,
        idempotencyKey: requestId('guided-declaration'), clientMessageId: requestId('guided-declaration-message'),
      })
      const created = await createExternalClaim({ claimId: claimRef.claimId, revision: declaration.claim_revision, idempotencyKey: requestId('guided-submit') })
      localStorage.removeItem(STORAGE_KEY); setResult(created.external_claim)
    } catch (requestError) { setError(requestError.message) } finally { setBusy(false) }
  }

  if (result) return <main className="guided-page"><section className="guided-card success-card"><p className="eyebrow">Claim submitted</p><h1>{result.claim_number}</h1><p>Your completed Motor claim is now available to Northwind staff.</p><button className="primary-button" onClick={onExit}>Return home</button></section></main>

  return <main className="guided-page"><section className="guided-card">
    <button className="back-link" type="button" onClick={onExit}>← Back to claim options</button>
    <div className="step-track" aria-label={`Step ${step} of 3`}><span className={step >= 1 ? 'active' : ''}>1 Details</span><span className={step >= 2 ? 'active' : ''}>2 Materials</span><span className={step >= 3 ? 'active' : ''}>3 Declaration</span></div>
    {step === 1 && <form onSubmit={saveDetails}><p className="eyebrow">Motor claim · Step 1</p><h1>Your details and incident</h1><div className="guided-grid">
      <label>Client Number<input required autoComplete="off" placeholder="For example, NW-123456" {...field('policyNumber')} /></label>
      <label>Your role<select {...field('role')}><option value="policyholder">Policyholder</option><option value="authorised_representative">Authorised representative</option></select></label>
      <label>Contact preference<select {...field('contactPreference')}><option value="email">Email</option><option value="phone">Phone</option><option value="sms">SMS</option><option value="in_app">In app</option></select></label>
      <label>Incident date<EnglishDatePicker value={draft.occurredAt} onChange={(occurredAt) => setDraft({ ...draft, occurredAt })} /></label>
      <label className="wide">Where it happened<input required {...field('location')} /></label>
      <label className="wide">What happened<textarea required {...field('description')} /></label>
      <label className="wide">What was damaged or lost<textarea required {...field('lossDescription')} /></label>
      <label>Vehicle registration plate number<input aria-label="Vehicle registration plate number" placeholder="For example, ABC123" {...field('registration')} /><small>The letters and numbers shown on your vehicle's licence plate.</small></label><label>Damage summary<input {...field('damageDescription')} /></label>
    </div><p className="save-note">Your draft is saved on this device and to shared Claim State when you continue.</p><button className="primary-button" disabled={busy}>{busy ? 'Saving…' : 'Save and continue'}</button></form>}
    {step === 2 && <section><p className="eyebrow">Motor claim · Step 2</p><h1>Add supporting materials</h1><p className="materials-intro">Add anything you already have. These materials are recommended, not required to save your report, and you can provide missing documents later.</p><div className="material-list">{MATERIALS.map((material) => <label className="material-card" key={material.key}><span className="material-copy"><strong>{material.title}</strong><span>{material.help}</span><small>{material.formats} · Maximum 10 MB</small></span><span className="file-control"><span>{files[material.key]?.name || 'Choose file'}</span><input type="file" accept={material.accept} onChange={(event) => { const selected = event.target.files[0]; setFiles((current) => selected ? { ...current, [material.key]: selected } : current) }} /></span></label>)}</div>{uploaded.map((file) => <p className="uploaded-file" key={file.name}>✓ {file.name} · {file.status}</p>)}<div className="guided-actions"><button className="secondary-button" onClick={() => setStep(1)}>Back</button><button className="primary-button" disabled={busy} onClick={uploadFiles}>{busy ? 'Saving…' : Object.values(files).some(Boolean) ? 'Upload and continue' : 'Continue without files'}</button></div></section>}
    {step === 3 && <form onSubmit={submit}><p className="eyebrow">Motor claim · Step 3</p><h1>Review and declare</h1><div className="declaration"><strong>Controlled prototype declaration</strong><p>I confirm the information supplied is true and complete to the best of my knowledge. I understand Northwind may request more information.</p><small>Version: {DECLARATION_VERSION}</small></div><label className="accept-row"><input type="checkbox" checked={accepted} onChange={(event) => setAccepted(event.target.checked)} /> I have read and accept this declaration.</label><div className="guided-actions"><button className="secondary-button" type="button" onClick={() => setStep(2)}>Back</button><button className="primary-button" disabled={!accepted || busy}>{busy ? 'Submitting…' : 'Submit claim'}</button></div></form>}
    {error && <p className="backend-status is-error" role="alert">{error}</p>}
  </section></main>
}
