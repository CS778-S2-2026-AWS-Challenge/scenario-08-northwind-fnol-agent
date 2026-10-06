// The claimant view carries only claimant-visible fields, and no oracle or setup value reaches
// the claimant prompt (#1222). Run with: node --test tests/corpus/runner/
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { test } = require('node:test')

const { buildClaimantView, hiddenValues, assertNoLeak } = require('./claimant_view.cjs')
const { buildClaimantPrompt, promptScaffold } = require('./claimant_simulator.cjs')

function writeJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, JSON.stringify(value, null, 1))
}

function syntheticPack() {
  const dir = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'corpus-view-')), 'CTL-M-900')
  fs.mkdirSync(path.join(dir, 'input', 'materials'), { recursive: true })
  fs.writeFileSync(path.join(dir, 'input', 'initial_message.txt'), 'Hi, i backed into a pole at the supermarkt carpark.\n')
  writeJson(path.join(dir, 'input', 'facts.json'), {
    case_id: 'CTL-M-900',
    persona: 'Brief and a bit embarrassed.',
    answer_policy: 'Answer only what is asked, from these facts.',
    facts: { 'claim.product_family': 'motor', 'policy.policy_number': 'NW-SYN-MTR-100900' },
  })
  writeJson(path.join(dir, 'input', 'materials.json'), {
    case_id: 'CTL-M-900',
    materials: [
      { file: 'photo-rear.jpg', evidence_kind: 'incident_photo', available_from: 'start' },
      { file: 'source-render.png', evidence_kind: 'incident_photo', available_from: 'start' },
    ],
  })
  writeJson(path.join(dir, 'provenance.json'), {
    materials: [
      { id: 'photo-rear', file: 'photo-rear.jpg', purpose: 'Shows the dented bumper planted for review', inputs: { prompt: 'a dented bumper, overcast car park' } },
      { id: 'source-render', file: 'source-render.png', include: false, purpose: 'Source image for the photo', inputs: {} },
    ],
  })
  writeJson(path.join(dir, 'setup.json'), {
    case_id: 'CTL-M-900',
    claimant_session: 'anonymous_then_sign_in',
    policies_in_system: [{ policy_number: 'NW-SYN-MTR-100900', family: 'motor', uncertainty: ['COVERAGE_SECTION_INCOMPLETE'] }],
  })
  writeJson(path.join(dir, 'oracle', 'labels.json'), {
    family: 'motor',
    triage: { expected_class: 'complex', required_reasons: ['coverage_unclear'], rationale: 'The lookup carries an uncertainty marker.' },
    design: { planted_indicators: ['receipt dated after the incident'], message_style: 'typos' },
  })
  return dir
}

const LABELS = { 'CTL-M-900': { 'photo-rear': 'Photo of the back of my car', 'source-render': 'never shown' } }

test('the view carries claimant-visible fields only', () => {
  const view = buildClaimantView(syntheticPack(), LABELS)
  assert.deepEqual(Object.keys(view).sort(), ['answer_policy', 'case_id', 'facts', 'initial_message', 'materials', 'persona'])
  assert.equal(view.initial_message, 'Hi, i backed into a pole at the supermarkt carpark.')
  assert.deepEqual(view.materials, [{ id: 'photo-rear', file: 'photo-rear.jpg', label: 'Photo of the back of my car', available_from: 'start' }])
  const text = JSON.stringify(view)
  for (const forbidden of ['evidence_kind', 'incident_photo', 'planted for review', 'overcast car park', 'source-render']) {
    assert.ok(!text.includes(forbidden), `view must not contain ${forbidden}`)
  }
})

test('no oracle or setup value reaches the claimant prompt', () => {
  const dir = syntheticPack()
  const view = buildClaimantView(dir, LABELS)
  const hidden = hiddenValues(dir, view, promptScaffold())
  // The policy number is in the facts as well as the setup, so it is not a hidden value.
  assert.ok(!hidden.includes('NW-SYN-MTR-100900'))
  assert.ok(hidden.includes('complex') && hidden.includes('coverage_unclear') && hidden.includes('anonymous_then_sign_in'))
  const prompt = buildClaimantPrompt(view, [], 'Northwind: Is anyone hurt?')
  assert.doesNotThrow(() => assertNoLeak(prompt.system + prompt.brief, hidden))
})

test('a material label that repeats an oracle or setup value fails the guard', () => {
  const dir = syntheticPack()
  for (const label of ['Receipt dated after the incident', 'Photo for anonymous_then_sign_in']) {
    // The runner builds the view with the labels and derives the hidden values from that view.
    const view = buildClaimantView(dir, { 'CTL-M-900': { 'photo-rear': label } })
    const hidden = hiddenValues(dir, view, promptScaffold())
    const prompt = buildClaimantPrompt(view, [], '')
    assert.throws(() => assertNoLeak(prompt.system + prompt.brief, hidden), /oracle or setup value/, label)
  }
})

test('a prompt that carries an oracle value fails the guard', () => {
  const dir = syntheticPack()
  const view = buildClaimantView(dir, LABELS)
  const hidden = hiddenValues(dir, view, promptScaffold())
  const oracle = JSON.parse(fs.readFileSync(path.join(dir, 'oracle', 'labels.json'), 'utf8'))
  const leaky = buildClaimantPrompt({ ...view, persona: `${view.persona} Expected triage: ${oracle.triage.expected_class}.` }, [], '')
  assert.throws(() => assertNoLeak(leaky.system + leaky.brief, hidden), /oracle or setup value/)
  const setupLeak = buildClaimantPrompt({ ...view, facts: { ...view.facts, session: 'anonymous_then_sign_in' } }, [], '')
  assert.throws(() => assertNoLeak(setupLeak.system + setupLeak.brief, hidden), /oracle or setup value/)
})
