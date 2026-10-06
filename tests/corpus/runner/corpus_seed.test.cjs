// Packs become one #1221 business-seed manifest with fixed identities (#1222).
// Run with: node --test tests/corpus/runner/corpus_seed.test.cjs
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { test } = require('node:test')

const { buildBusinessSeed } = require('./corpus_seed.cjs')

function writeJson(file, value) {
  fs.mkdirSync(path.dirname(file), { recursive: true })
  fs.writeFileSync(file, JSON.stringify(value, null, 1))
}

function casesWith(packs) {
  const casesDir = fs.mkdtempSync(path.join(os.tmpdir(), 'corpus-seed-'))
  for (const [caseId, setup, facts] of packs) {
    writeJson(path.join(casesDir, caseId, 'setup.json'), { case_id: caseId, claimant_session: 'signed_in', history_lookup: 'available', policies_in_system: [], prior_submitted_claims: [], ...setup })
    writeJson(path.join(casesDir, caseId, 'input', 'facts.json'), { case_id: caseId, facts: { 'policyholder.name': 'Aroha Test', 'claimant.email': `${caseId.toLowerCase()}@example.invalid`, ...facts } })
  }
  return casesDir
}

const POLICY = { policy_number: 'NW-SYN-MTR-100900', family: 'motor', effective_from: '2026-02-01', effective_to: '2027-01-31', excess_nzd: 400, uncertainty: [] }

test('each pack becomes a fixed customer with its own policy and earlier claims', () => {
  const casesDir = casesWith([
    ['CTL-M-900', { policies_in_system: [POLICY], prior_submitted_claims: [{ family: 'motor', incident_date: '2025-11-08', submitted_date: '2025-11-10' }] }, {}],
  ])
  const seed = buildBusinessSeed(casesDir, ['CTL-M-900'])
  assert.equal(seed.version, '1')
  assert.equal(seed.primary_customer_id, null)
  assert.deepEqual(seed.demo_cases, [])
  assert.deepEqual(seed.customers.map((c) => [c.customer_id, c.email, c.display_name]), [['cus_corpus_ctl_m_900', 'ctl-m-900@example.invalid', 'Aroha Test']])
  assert.deepEqual(seed.policies_in_system[0], { ...POLICY, customer_id: 'cus_corpus_ctl_m_900', status: 'active', coverage_sections: [] })
  assert.deepEqual(seed.prior_submitted_claims, [{
    claim_id: 'clm_corpus_ctl_m_900_p1',
    session_id: 'ses_corpus_ctl_m_900_p1',
    customer_id: 'cus_corpus_ctl_m_900',
    family: 'motor',
    incident_date: '2025-11-08',
    submitted_date: '2025-11-10',
    claim_number: 'NW-SYN-CTL-M-900-P1',
    incident_description: 'Earlier motor claim.',
  }])
})

test('the same packs always give the same manifest', () => {
  const casesDir = casesWith([['CTL-M-900', { policies_in_system: [POLICY] }, {}], ['CTL-H-900', {}, {}]])
  assert.deepEqual(buildBusinessSeed(casesDir, ['CTL-M-900', 'CTL-H-900']), buildBusinessSeed(casesDir, ['CTL-M-900', 'CTL-H-900']))
})

test('a reserved policy number, a shared policy number or a repeated pack is refused', () => {
  const reserved = casesWith([['CTL-M-901', { policies_in_system: [{ ...POLICY, policy_number: 'NW-MTR-204518' }] }, {}]])
  assert.throws(() => buildBusinessSeed(reserved, ['CTL-M-901']), /reserved by #1206/)
  const shared = casesWith([['CTL-M-902', { policies_in_system: [POLICY] }, {}], ['CTL-M-903', { policies_in_system: [POLICY] }, {}]])
  assert.throws(() => buildBusinessSeed(shared, ['CTL-M-902', 'CTL-M-903']), /appears in CTL-M-902 and CTL-M-903/)
  const single = casesWith([['CTL-M-904', {}, {}]])
  assert.throws(() => buildBusinessSeed(single, ['CTL-M-904', 'CTL-M-904']), /appears twice/)
})
