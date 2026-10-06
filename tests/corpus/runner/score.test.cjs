// The scorer reads the end state the way the system writes it (#1222).
// Run with: node --test tests/corpus/runner/score.test.cjs
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { test } = require('node:test')

const { scorePack } = require('./score.cjs')

function writeJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, JSON.stringify(value, null, 1))
}

// One synthetic pack and one run of it. `lodged` switches between a lodged and a stuck run.
function syntheticRun({ lodged = true, urgency = 'normal', agentText = 'When did it happen?' } = {}) {
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
    design: { innocent_controls: [] },
    triage: { expected_class: 'fast_track', required_reasons: [], allowed_reasons: [] },
    review_indicators: { expected_fraud_signal: 'none' },
    expected_facts: { 'claim.product_family': 'motor', 'vehicle.drivable': true },
    assertions: [
      { id: 'F2', kind: 'forbidden', judge: 'state', path: 'staff:claim.claim_state.urgency', op: 'in', value: ['urgent', 'immediate_safety_risk'] },
    ],
  })
  const runDir = path.join(root, 'run', 'CTL-M-900')
  const started = '2026-10-06T01:00:00.000Z'
  writeJson(path.join(runDir, 'run.json'), {
    case_id: 'CTL-M-900', outcome: lodged ? 'lodged_first_time' : 'stuck', claim_number: lodged ? 'NWF-2026-000001' : null,
    claimant_messages: 2, retries: 0, repeated_questions: 0, nothing_to_answer: 0, turn_ms: [5000], uploads: [], stuck: null,
    started_at: started, finished_at: '2026-10-06T01:01:00.000Z',
  })
  writeJson(path.join(runDir, 'claimant.json'), {
    'claimant:claim': { status: 200, body: { workflow_state: 'created', form: { 'claim.product_family': { value: 'motor', status: 'confirmed' } }, open_items: [] } },
    'claimant:messages': { status: 200, body: { items: [{ actor: 'agent', content: { type: 'text', text: agentText } }] } },
  })
  writeJson(path.join(runDir, 'staff.json'), {
    'staff:claim': { status: 200, body: { claim_state: { severity: 'fast_track', urgency, fraud_signal: 'none' }, triage: { severity: 'fast_track', reasons: [] }, open_items: [] } },
    'staff:claim.fields': { status: 200, body: { items: [
      { code: 'claim.product_family', field: { value: 'motor', status: 'confirmed' } },
      { code: 'vehicle.drivable', field: { value: true, status: 'confirmed' } },
    ] } },
    'staff:claim.signals': { status: 200, body: { items: [] } },
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
