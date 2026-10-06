// Controlled-corpus packs as one business-seed manifest in the shared #1221 contract
// (`config/business-seed.json`, `backend/services/business_seed.py`) (#1222). The manifest is
// written outside the repository and provisioned by provision_seed.py through the #1221
// functions, which insert absent records only.
//
// Every identity is fixed by the pack: the same packs always give the same manifest, so a
// repeated seed changes nothing. Each pack's claimant is its own customer, signed in with
// the name and email the pack gives them.
const fs = require('node:fs')
const path = require('node:path')

// #1206 uses these as fixture policies; a pack that names one is a corpus error.
const RESERVED_POLICIES = new Set(['NW-MTR-204518', 'NW-MTR-204519', 'NW-HOM-204518', 'NW-CON-204518'])

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8'))
}

// CTL-M-002 -> ctl_m_002
function packKey(caseId) {
  return caseId.toLowerCase().replace(/[^a-z0-9]+/g, '_')
}

// The account a pack signs in with. The password is synthetic, the same for every run of the
// pack, and exists only in the local manifest and the local identity store.
function seedAccount(caseId, facts) {
  const key = packKey(caseId)
  return {
    customer_id: `cus_corpus_${key}`,
    email: String(facts['claimant.email'] || `${key.replace(/_/g, '-')}@corpus.example.invalid`).toLowerCase(),
    display_name: String(facts['policyholder.name'] || 'Corpus Claimant'),
    synthetic_password: `corpus-synthetic-${key.replace(/_/g, '-')}`,
  }
}

function buildBusinessSeed(casesDir, caseIds) {
  if (new Set(caseIds).size !== caseIds.length) throw new Error('a pack appears twice; each pack is seeded once per run')
  const customers = []
  const policies = []
  const priorClaims = []
  const policyOwner = new Map()
  for (const caseId of caseIds) {
    const setup = readJson(path.join(casesDir, caseId, 'setup.json'))
    const facts = readJson(path.join(casesDir, caseId, 'input', 'facts.json')).facts
    const account = seedAccount(caseId, facts)
    customers.push(account)
    for (const policy of setup.policies_in_system || []) {
      if (RESERVED_POLICIES.has(policy.policy_number)) throw new Error(`${caseId} uses ${policy.policy_number}, reserved by #1206`)
      // A policy belongs to one customer, and absent-only provisioning would silently keep the
      // first owner, so two packs may not share a policy number.
      if (policyOwner.has(policy.policy_number)) throw new Error(`${policy.policy_number} appears in ${policyOwner.get(policy.policy_number)} and ${caseId}`)
      policyOwner.set(policy.policy_number, caseId)
      policies.push({
        policy_number: policy.policy_number,
        customer_id: account.customer_id,
        family: policy.family,
        effective_from: policy.effective_from ?? null,
        effective_to: policy.effective_to ?? null,
        excess_nzd: policy.excess_nzd ?? null,
        status: 'active',
        // The corpus has no coverage sections; the lookup reports none rather than invented ones.
        coverage_sections: [],
        uncertainty: policy.uncertainty || [],
      })
    }
    ;(setup.prior_submitted_claims || []).forEach((prior, index) => {
      const n = index + 1
      priorClaims.push({
        claim_id: `clm_corpus_${packKey(caseId)}_p${n}`,
        session_id: `ses_corpus_${packKey(caseId)}_p${n}`,
        customer_id: account.customer_id,
        family: prior.family,
        incident_date: prior.incident_date,
        submitted_date: prior.submitted_date,
        claim_number: `NW-SYN-${caseId}-P${n}`,
        incident_description: `Earlier ${prior.family} claim.`,
      })
    })
  }
  // Corpus packs have no primary demo customer and no demo cases (docs/controlled-test-corpus.md).
  return { version: '1', primary_customer_id: null, customers, policies_in_system: policies, prior_submitted_claims: priorClaims, demo_cases: [] }
}

module.exports = { RESERVED_POLICIES, packKey, seedAccount, buildBusinessSeed }
