// The scorer reads the end state the way the system writes it (#1222).
// Run with: node --test tests/corpus/runner/score.test.cjs
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { test } = require('node:test')

const { scorePack, summarise, sameValue } = require('./score.cjs')

function writeJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, JSON.stringify(value, null, 1))
}

// One synthetic pack and one run of it. `lodged` switches between a lodged and a stuck run.
function syntheticRun({ lodged = true, urgency = 'normal', agentText = 'When did it happen?', agentTurns = [agentText], severity = 'fast_track', fraudSignal = 'none', innocentControls = [], staffOpenItems = [], expectedFraud = 'none', signals = [], condition = undefined, additionalConditions = undefined, provenance = [], processingFailed = undefined } = {}) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'corpus-score-'))
  const casesDir = path.join(root, 'tests', 'corpus', 'controlled', 'v1', 'cases')
  writeJson(path.join(root, 'tests', 'corpus', 'tools', 'global_assertions.json'), {
    assertions: [
      { id: 'G1', kind: 'forbidden', judge: 'text', scope: 'claimant_visible', must_not_match: ['(?i)\\bfraud', '\\bfast_track\\b'] },
      { id: 'G3', kind: 'forbidden', judge: 'state', path: 'claimant:claim.form["claim.product_family"].value', op: 'not_equals', value: '{pack.family}' },
    ],
  })
  writeJson(path.join(casesDir, 'CTL-M-900', 'oracle', 'labels.json'), {
    case_id: 'CTL-M-900',
    family: 'motor',
    scenario_category: 'M1',
    ...(condition ? { condition } : {}),
    ...(additionalConditions ? { additional_conditions: additionalConditions } : {}),
    design: { innocent_controls: innocentControls },
    triage: { expected_class: 'fast_track', required_reasons: [], allowed_reasons: [] },
    review_indicators: { expected_fraud_signal: expectedFraud },
    expected_facts: { 'claim.product_family': 'motor', 'vehicle.drivable': true },
    assertions: [
      { id: 'F2', kind: 'forbidden', judge: 'state', path: 'staff:claim.claim_state.urgency', op: 'in', value: ['urgent', 'immediate_safety_risk'] },
    ],
  })
  if (provenance.length) writeJson(path.join(casesDir, 'CTL-M-900', 'provenance.json'), { case_id: 'CTL-M-900', materials: provenance })
  const runDir = path.join(root, 'run', 'CTL-M-900')
  const started = '2026-10-06T01:00:00.000Z'
  writeJson(path.join(runDir, 'run.json'), {
    case_id: 'CTL-M-900', claim_id: 'clm_900', outcome: lodged ? 'lodged_first_time' : 'stuck', claim_number: lodged ? 'NWF-2026-000001' : null,
    claimant_messages: 2, retries: 0, repeated_questions: 0, nothing_to_answer: 0, turn_ms: [5000], uploads: [], stuck: null,
    started_at: started, finished_at: '2026-10-06T01:01:00.000Z',
    ...(processingFailed ? { processing_failed: processingFailed } : {}),
  })
  writeJson(path.join(runDir, 'claimant.json'), {
    'claimant:claim': { status: 200, body: { workflow_state: 'created', form: { 'claim.product_family': { value: 'motor', status: 'confirmed' } }, open_items: [] } },
    'claimant:evidence': { status: 200, body: { items: [] } },
    'claimant:messages': { status: 200, body: { items: agentTurns.map((text) => ({ actor: 'agent', content: { type: 'text', text } })) } },
  })
  writeJson(path.join(runDir, 'staff.json'), {
    'staff:claim': { status: 200, body: { claim_state: { severity, urgency, fraud_signal: fraudSignal }, triage: { severity, reasons: [] }, open_items: staffOpenItems } },
    'staff:claim.fields': { status: 200, body: { items: [
      { code: 'claim.product_family', field: { value: 'motor', status: 'confirmed' } },
      { code: 'vehicle.drivable', field: { value: true, status: 'confirmed' } },
    ] } },
    'staff:claim.handoffs': { status: 200, body: { items: [] } },
    'staff:claim.signals': { status: 200, body: { items: signals.map((code) => ({ code })) } },
    'staff:claim.evidence': { status: 200, body: { items: [] } },
  })
  writeJson(path.join(runDir, 'transcript.json'), [])
  return { runDir, casesDir }
}

test('facts are read from the staff field list', () => {
  const { runDir, casesDir } = syntheticRun()
  const score = scorePack(runDir, casesDir)
  assert.deepEqual(score.facts.map((fact) => [fact.code, fact.result]), [['claim.product_family', 'pass'], ['vehicle.drivable', 'pass']])
})

test('a forbidden assertion passes when its condition does not hold and fails when it does', () => {
  const calm = syntheticRun({ urgency: 'normal' })
  assert.equal(scorePack(calm.runDir, calm.casesDir).assertions.find((a) => a.id === 'F2').result, 'pass')
  const urgent = syntheticRun({ urgency: 'urgent' })
  assert.equal(scorePack(urgent.runDir, urgent.casesDir).assertions.find((a) => a.id === 'F2').result, 'fail')
})

test('global assertions apply, with the pack family and Python-style case-insensitive patterns', () => {
  const clean = syntheticRun()
  const cleanScore = scorePack(clean.runDir, clean.casesDir)
  assert.equal(cleanScore.assertions.find((a) => a.id === 'G3').result, 'pass')
  assert.equal(cleanScore.assertions.find((a) => a.id === 'G1').result, 'pass')
  const leaked = syntheticRun({ agentText: 'Our FRAUD team will look at this.' })
  assert.equal(scorePack(leaked.runDir, leaked.casesDir).assertions.find((a) => a.id === 'G1').result, 'fail')
})

test('only a lodged journey can meet the effort target', () => {
  const lodged = syntheticRun({ lodged: true })
  assert.equal(scorePack(lodged.runDir, lodged.casesDir).journey.effort_within_target, true)
  const stuck = syntheticRun({ lodged: false })
  assert.equal(scorePack(stuck.runDir, stuck.casesDir).journey.effort_within_target, false)
})

test('every question sentence counts towards effort, a repeated question included', () => {
  const { runDir, casesDir } = syntheticRun({
    agentTurns: ['What is the registration?', 'What is the registration? What colour is it?', 'What is the registration? Is it drivable?', 'Thanks, that is everything.'],
  })
  assert.equal(scorePack(runDir, casesDir).journey.agent_questions, 5)
  const many = syntheticRun({ agentTurns: ['When? Where? Who was driving? Anyone hurt? Drivable?', 'Photos? Quote? Police report? Witnesses? Other driver?'] })
  const score = scorePack(many.runDir, many.casesDir)
  assert.equal(score.journey.agent_questions, 10)
  assert.equal(score.journey.effort_within_target, false)
})

test('a lodged claim that triage says is missing information is not completed without follow-up', () => {
  const { runDir, casesDir } = syntheticRun()
  assert.equal(scorePack(runDir, casesDir).journey.completed_without_follow_up, true)
  const staffFile = path.join(runDir, 'staff.json')
  const staff = JSON.parse(fs.readFileSync(staffFile, 'utf8'))
  staff['staff:claim'].body.triage.reasons = ['document_outstanding', 'amount_over_threshold']
  fs.writeFileSync(staffFile, JSON.stringify(staff))
  const journey = scorePack(runDir, casesDir).journey
  assert.equal(journey.completed_without_follow_up, false)
  assert.deepEqual(journey.missing_information_reasons, ['document_outstanding'])
})

test('a pack that expects no Claim has no triage to score', () => {
  const { runDir, casesDir } = syntheticRun()
  const oracleFile = path.join(casesDir, 'CTL-M-900', 'oracle', 'labels.json')
  const oracle = JSON.parse(fs.readFileSync(oracleFile, 'utf8'))
  oracle.triage = { applies: false, expected_class: null, required_reasons: [], allowed_reasons: [] }
  fs.writeFileSync(oracleFile, JSON.stringify(oracle))
  assert.equal(scorePack(runDir, casesDir).triage.result, 'not_applicable')
})

test('triage reasons pass only with every required reason and nothing outside the allowed list', () => {
  const { runDir, casesDir } = syntheticRun()
  const staffFile = path.join(runDir, 'staff.json')
  const staff = JSON.parse(fs.readFileSync(staffFile, 'utf8'))
  assert.equal(scorePack(runDir, casesDir).triage.reasons.result, 'pass')
  staff['staff:claim'].body.triage.reasons = ['document_outstanding']
  fs.writeFileSync(staffFile, JSON.stringify(staff))
  const score = scorePack(runDir, casesDir)
  assert.equal(score.triage.reasons.result, 'fail')
  assert.deepEqual(score.triage.reasons.unexpected, ['document_outstanding'])
})

test('a pack that never lodged has its triage and review marked not lodged, not unimplemented', () => {
  const stuck = syntheticRun({ lodged: false, severity: 'unassessed' })
  const score = scorePack(stuck.runDir, stuck.casesDir)
  assert.equal(score.triage.result, 'not_lodged')
  assert.equal(score.review.result, 'not_lodged')
  const summary = summarise([score])
  assert.match(summary, /Triage scored: 0 .*not implemented: 0; .*not lodged: 1\./)
  assert.match(summary, /Fraud review scored: 0 .*not implemented: 0; not lodged: 1\./)
})

test('an innocent control is judged only once the fraud signal is written', () => {
  const quiet = syntheticRun({ innocentControls: ['non_date_inconsistency'] })
  const quietScore = scorePack(quiet.runDir, quiet.casesDir)
  assert.deepEqual(quietScore.innocent_controls, [{ control: 'non_date_inconsistency', result: 'not_implemented' }])
  assert.match(summarise([quietScore]), /Innocent controls: 1 \(flagged 0, not implemented 1, not lodged 0\)/)
  const flagged = syntheticRun({ innocentControls: ['non_date_inconsistency'], fraudSignal: 'review_required' })
  const flaggedScore = scorePack(flagged.runDir, flagged.casesDir)
  assert.deepEqual(flaggedScore.innocent_controls, [{ control: 'non_date_inconsistency', result: 'flagged' }])
  assert.equal(flaggedScore.review.false_positive, true)
  assert.match(summarise([flaggedScore]), /Fraud review scored: 1 \(false positives 1;/)
})

test('a staff signal outside the fraud contract never scores fraud review or innocent controls', () => {
  for (const expectedFraud of ['none', 'review_required']) {
    const { runDir, casesDir } = syntheticRun({ expectedFraud, signals: ['POLICY_JUDGMENT_PROPOSAL'], innocentControls: ['same_day_purchase'] })
    const score = scorePack(runDir, casesDir)
    assert.equal(score.review.result, 'not_implemented', `expected fraud signal ${expectedFraud}`)
    assert.deepEqual(score.review.signal_codes, ['POLICY_JUDGMENT_PROPOSAL'])
    assert.deepEqual(score.innocent_controls, [{ control: 'same_day_purchase', result: 'not_implemented' }])
    assert.match(summarise([score]), /Fraud review scored: 0 .*not implemented: 1;/)
  }
})

test('the staff to-answer list keeps each item kind, the proposed answer and the contact preference', () => {
  const { runDir, casesDir } = syntheticRun({ staffOpenItems: [
    { item_id: 'nwq_1', kind: 'question', owner: 'northwind', state: 'open', subject: 'Can I book the glazier?', claimant_wording: 'Can I book the glazier?', proposed_answer: 'The team will confirm.', basis: 'Asked in chat.', contact_preference: null },
    { item_id: 'nwq_2', kind: 'contact_request', owner: 'northwind', state: 'open', subject: 'Call me back', claimant_wording: 'Call me back', proposed_answer: null, basis: null, contact_preference: 'phone' },
  ] })
  const items = scorePack(runDir, casesDir).staff_open_items
  assert.deepEqual(items.map((item) => [item.kind, item.proposed_answer, item.basis, item.contact_preference]), [
    ['question', 'The team will confirm.', 'Asked in chat.', null],
    ['contact_request', null, null, 'phone'],
  ])
})

test('a pack whose staff or claimant reads failed is incomplete and kept out of every count', () => {
  const complete = syntheticRun()
  assert.equal(scorePack(complete.runDir, complete.casesDir).evidence.complete, true)
  const missing = syntheticRun()
  const staffFile = path.join(missing.runDir, 'staff.json')
  const staff = JSON.parse(fs.readFileSync(staffFile, 'utf8'))
  delete staff['staff:claim.handoffs']
  staff['staff:claim.signals'].status = 500
  fs.writeFileSync(staffFile, JSON.stringify(staff))
  const score = scorePack(missing.runDir, missing.casesDir)
  assert.equal(score.evidence.complete, false)
  assert.deepEqual(score.evidence.missing_reads, ['staff:claim.handoffs', 'staff:claim.signals'])
  const summary = summarise([scorePack(complete.runDir, complete.casesDir), score])
  assert.match(summary, /Evidence incomplete \(kept out of every count\): 1 \(CTL-M-900\)/)
  assert.match(summary, /Packs: 1\. Lodged first time: 1\./)
})

test('the incident day is read from every stored temporal form', () => {
  assert.equal(sameValue('incident.occurred_at', '2026-09-11 night', '2026-09-11'), true)
  assert.equal(sameValue('incident.occurred_at', '2026-09-11 morning', '2026-09-11'), true)
  assert.equal(sameValue('incident.occurred_at', '2026-09-05T16:00+12:00', '2026-09-05'), true)
  assert.equal(sameValue('incident.occurred_at', { date: '2026-09-05', precision: 'partial' }, '2026-09-05'), true)
  assert.equal(sameValue('incident.occurred_at', '2026-09-12 night', '2026-09-11'), false)
  assert.equal(sameValue('incident.occurred_at', 'last Friday night', '2026-09-11'), false)
})

test('files the product could not process are reported, and a valid one among them is flagged', () => {
  const provenance = [
    { id: 'quote-corrupt', file: 'quote.pdf', inputs: { source: 'quote-source', transform: 'truncate' } },
    { id: 'photo-front', file: 'photo-front.jpg', inputs: {} },
  ]
  // The pack's planted broken quote failed twice (tried once more), and that is expected.
  const planted = syntheticRun({ condition: 'corrupt_file', provenance, processingFailed: ['quote-corrupt', 'quote-corrupt'] })
  const plantedScore = scorePack(planted.runDir, planted.casesDir)
  assert.deepEqual(plantedScore.journey.processing_failed, ['quote-corrupt', 'quote-corrupt'])
  assert.deepEqual(plantedScore.journey.unexpected_processing_failed, [])
  // A valid photo failing is a product or extraction failure, flagged even though the pack lodged.
  const valid = syntheticRun({ condition: 'corrupt_file', provenance, processingFailed: ['photo-front'] })
  const validScore = scorePack(valid.runDir, valid.casesDir)
  assert.equal(validScore.journey.outcome, 'lodged_first_time')
  assert.deepEqual(validScore.journey.unexpected_processing_failed, ['photo-front'])
  const summary = summarise([plantedScore, validScore])
  assert.match(summary, /Files the product could not process: 3 in 2 packs; not made broken by the corpus: 1 \(CTL-M-900: photo-front\)\./)
  // A condition listed among the pack's additional conditions counts the same.
  const additional = syntheticRun({ additionalConditions: ['corrupt_file'], provenance, processingFailed: ['quote-corrupt'] })
  assert.deepEqual(scorePack(additional.runDir, additional.casesDir).journey.unexpected_processing_failed, [])
  // No failed file, and no provenance on disk: nothing reported.
  const clean = syntheticRun()
  assert.deepEqual(scorePack(clean.runDir, clean.casesDir).journey.unexpected_processing_failed, [])
})
