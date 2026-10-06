// Scorer for controlled-corpus runs (#1222). Runs after the journeys and is the only reader of
// `oracle/`. Every comparison is mechanical; nothing here asks a model for a score.
//
//   node tests/corpus/runner/score.cjs <run folder>    (CORPUS_CASES_DIR must be set)
//
// Capabilities main does not implement yet are reported as `not_implemented`, kept out of the
// pass and fail counts, and listed in the summary, never skipped silently.
const fs = require('node:fs')
const path = require('node:path')

const { questionSentences } = require('./runner.cjs')

const RETRIEVAL_ONLY_SIGNALS = new Set(['POLICY_RETRIEVAL_UNCERTAINTY', 'CLAIM_HISTORY_RETRIEVAL_UNCERTAINTY'])
// Triage reasons (backend/domain/triage.py) that say something is still missing from the report:
// the insurer has to come back to the claimant, so the claim was not completed without follow-up.
const MISSING_INFORMATION_REASONS = new Set(['document_outstanding', 'fact_unresolved', 'policy_not_verified', 'amount_unknown'])
// The end-state reads a pack with a Claim needs: the claimant's own view and the staff view
// through the normal staff sign-in (#1222).
const REQUIRED_READS = ['claimant:claim', 'claimant:evidence', 'claimant:messages', 'staff:claim', 'staff:claim.fields', 'staff:claim.handoffs', 'staff:claim.signals', 'staff:claim.evidence']

function readJson(file, fallbackMissing = undefined) {
  if (!fs.existsSync(file)) {
    if (fallbackMissing !== undefined) return fallbackMissing
    throw new Error(`${file} is missing`)
  }
  return JSON.parse(fs.readFileSync(file, 'utf8'))
}

function median(values) {
  if (!values.length) return null
  const sorted = [...values].sort((a, b) => a - b)
  const middle = Math.floor(sorted.length / 2)
  return sorted.length % 2 ? sorted[middle] : Math.round((sorted[middle - 1] + sorted[middle]) / 2)
}

// The calendar day a temporal value names. The runtime stores one of the forms in
// `backend/domain/temporal_resolution.py`: `2026-10-01T17:20+13:00`, `2026-10-01`, or a date
// with a part of day (`2026-10-01 evening`); a seeded earlier claim stores `{ date, precision }`.
// A clock time is read in New Zealand time. Anything else is returned as it is, so it only
// matches itself.
const PARTS_OF_DAY = ['morning', 'afternoon', 'evening', 'night']

function calendarDay(value) {
  if (value && typeof value === 'object' && typeof value.date === 'string') return calendarDay(value.date)
  const text = String(value).trim()
  const dated = text.match(/^(\d{4}-\d{2}-\d{2})(?:\s+([a-z]+))?$/)
  if (dated && (!dated[2] || PARTS_OF_DAY.includes(dated[2]))) return dated[1]
  if (/^\d{4}-\d{2}-\d{2}T/.test(text)) {
    const date = new Date(text)
    if (!Number.isNaN(date.getTime())) return new Intl.DateTimeFormat('en-CA', { timeZone: 'Pacific/Auckland', year: 'numeric', month: '2-digit', day: '2-digit' }).format(date)
  }
  return text
}

function sameValue(code, actual, expected) {
  if (Array.isArray(expected)) return expected.some((item) => sameValue(code, actual, item))
  if (code === 'incident.occurred_at' || /_date$|\.date$/.test(code)) return calendarDay(actual) === calendarDay(expected)
  if (typeof expected === 'string' && typeof actual === 'string') return actual.trim().toLowerCase() === expected.trim().toLowerCase()
  return JSON.stringify(actual) === JSON.stringify(expected)
}

// Paths from `docs/controlled-test-corpus.md`: a source such as `claimant:claim`, then fields,
// quoted field codes (`form["claim.product_family"]`) and list filters (`[field=value]`).
function resolvePath(sources, pathText) {
  const match = pathText.match(/^([a-z]+:[a-z]+)(.*)$/)
  if (!match) return { found: false, reason: `unrecognised path ${pathText}` }
  const source = sources[match[1]]
  if (source === undefined) return { found: false, reason: `source ${match[1]} not recorded` }
  let current = source
  const tokens = match[2].match(/\.[A-Za-z0-9_]+|\["[^"]+"\]|\[[A-Za-z0-9_]+=[^\]]+\]/g) || []
  for (const token of tokens) {
    if (current === undefined || current === null) return { found: false }
    if (token.startsWith('.')) current = current[token.slice(1)]
    else if (token.startsWith('["')) current = current[token.slice(2, -2)]
    else {
      const [field, value] = token.slice(1, -1).split('=')
      const list = Array.isArray(current) ? current : current.items || []
      current = list.find((item) => String(item[field]) === value)
    }
  }
  return { found: current !== undefined && current !== null, value: current }
}

// A `state` assertion describes a condition. `required` passes when it holds; `forbidden` ("must
// not happen", corpus standard) passes when it does not.
function judgeState(sources, assertion) {
  const { found, value, reason } = resolvePath(sources, assertion.path)
  if (reason) return { result: 'not_scored', detail: reason }
  let holds
  switch (assertion.op) {
    case 'exists': holds = found; break
    case 'absent': holds = !found; break
    case 'equals': holds = found && sameValue(assertion.path, value, assertion.value); break
    case 'not_equals': holds = !found || !sameValue(assertion.path, value, assertion.value); break
    case 'in': holds = found && assertion.value.some((item) => sameValue(assertion.path, value, item)); break
    case 'contains': holds = found && JSON.stringify(value).includes(String(assertion.value)); break
    default: return { result: 'not_scored', detail: `operator ${assertion.op}` }
  }
  const passes = assertion.kind === 'forbidden' ? !holds : holds
  return { result: passes ? 'pass' : 'fail', detail: found ? JSON.stringify(value).slice(0, 120) : 'not present' }
}

// The corpus writes patterns in Python syntax; a leading `(?i)` means case-insensitive.
function corpusRegExp(pattern) {
  return pattern.startsWith('(?i)') ? new RegExp(pattern.slice(4), 'i') : new RegExp(pattern)
}

function judgeText(agentText, assertion) {
  if (assertion.scope !== 'claimant_visible') return { result: 'not_scored', detail: `scope ${assertion.scope}` }
  if (assertion.must_not_match) {
    const hits = assertion.must_not_match.filter((pattern) => corpusRegExp(pattern).test(agentText))
    if (hits.length) return { result: 'fail', detail: `matched ${hits.join(', ')}` }
    // No pattern matched; a rubric still needs a reader for what patterns cannot catch.
    return assertion.rubric ? { result: 'needs_human', detail: 'no pattern matched; rubric' } : { result: 'pass', detail: '' }
  }
  return { result: 'needs_human', detail: 'rubric' }
}

// Corpus-wide assertions (`tests/corpus/tools/global_assertions.json`) apply to every pack.
function globalAssertions(casesDir, family) {
  const file = process.env.CORPUS_GLOBAL_ASSERTIONS || path.resolve(casesDir, '..', '..', '..', 'tools', 'global_assertions.json')
  return readJson(file).assertions.map((assertion) => (assertion.value === '{pack.family}' ? { ...assertion, value: family } : assertion))
}

function scorePack(packDir, casesDir) {
  const run = readJson(path.join(packDir, 'run.json'))
  const oracle = readJson(path.join(casesDir, run.case_id, 'oracle', 'labels.json'))
  const claimant = readJson(path.join(packDir, 'claimant.json'), {})
  const staff = readJson(path.join(packDir, 'staff.json'), {})
  const transcript = readJson(path.join(packDir, 'transcript.json'), [])
  const body = (entry) => (entry && entry.status === 200 ? entry.body : undefined)
  const sources = {
    'claimant:claim': body(claimant['claimant:claim']),
    'claimant:evidence': body(claimant['claimant:evidence']),
    'claimant:messages': body(claimant['claimant:messages']),
    'staff:claim': body(staff['staff:claim']),
    'staff:fields': body(staff['staff:claim.fields']),
    'staff:handoffs': body(staff['staff:claim.handoffs']),
    'staff:signals': body(staff['staff:claim.signals']),
    'staff:evidence': body(staff['staff:claim.evidence']),
  }
  // Every end-state read the scores rely on must have succeeded. A pack that has a Claim but a
  // missing or failed read is reported as incomplete and kept out of every count, rather than
  // scored on the gap.
  const reads = { ...claimant, ...staff }
  const missingReads = run.claim_id ? REQUIRED_READS.filter((key) => !reads[key] || reads[key].status !== 200) : []
  const evidence = { complete: missingReads.length === 0, missing_reads: missingReads, staff_read_error: run.staff_read_error || null }
  if (!evidence.complete) {
    return { case_id: run.case_id, scenario_category: oracle.scenario_category, evidence, journey: { outcome: run.outcome, claim_number: run.claim_number } }
  }
  const claim = sources['claimant:claim'] || {}
  const staffClaim = sources['staff:claim'] || {}
  const claimState = staffClaim.claim_state || {}

  // What the claimant was shown: the agent messages the claimant's own message list returns, or
  // the runner's transcript when that read failed.
  const messageItems = (sources['claimant:messages'] || {}).items
  const agentTurns = messageItems
    ? messageItems.filter((item) => item.actor === 'agent').map((item) => String((item.content || {}).text || ''))
    : transcript.filter((turn) => turn.who === 'northwind').map((turn) => turn.text)
  const agentText = agentTurns.join('\n')

  // Journey. Every question sentence of every agent turn counts, a question asked again included,
  // by the rule the runner uses to recognise a repeated question.
  const questions = agentTurns.reduce((total, text) => total + questionSentences(text).length, 0)
  const durationMs = Date.parse(run.finished_at) - Date.parse(run.started_at)
  const owedByClaimant = (claim.open_items || []).filter((item) => item.owner === 'claimant' && item.state === 'open')
  const lodged = Boolean(run.claim_number)
  const triageReasons = (staffClaim.triage && staffClaim.triage.reasons) || null
  const missingInformation = (triageReasons || []).filter((code) => MISSING_INFORMATION_REASONS.has(code))
  const journey = {
    outcome: run.outcome,
    claim_number: run.claim_number,
    // Lodged, nothing owed by the claimant, and triage does not say anything is still missing.
    completed_without_follow_up: lodged && owedByClaimant.length === 0 && missingInformation.length === 0,
    follow_up_basis: triageReasons ? 'open_items_and_triage' : 'open_items_only',
    missing_information_reasons: missingInformation,
    open_items_owed_by_claimant: owedByClaimant.map((item) => item.subject),
    claimant_messages: run.claimant_messages,
    agent_questions: questions,
    repeated_questions: run.repeated_questions,
    nothing_to_answer: run.nothing_to_answer,
    retries: run.retries,
    stuck: run.stuck,
    duration_s: Math.round(durationMs / 1000),
    turn_ms_median: median(run.turn_ms || []),
    turn_ms_max: run.turn_ms && run.turn_ms.length ? Math.max(...run.turn_ms) : null,
    effort_within_target: lodged && durationMs < 5 * 60 * 1000 && questions < 10,
    uploads: run.uploads,
  }

  // Triage and review signals: main does not write them yet (corpus standard, "What the labels map to").
  // Reasons pass when every required reason is there and nothing outside required and allowed is.
  const severity = claimState.severity
  const actualReasons = (staffClaim.triage && staffClaim.triage.reasons) || null
  const required = oracle.triage.required_reasons || []
  const allowed = new Set([...required, ...(oracle.triage.allowed_reasons || [])])
  const reasons = actualReasons
    ? {
        result: required.every((code) => actualReasons.includes(code)) && actualReasons.every((code) => allowed.has(code)) ? 'pass' : 'fail',
        expected_required: required,
        missing: required.filter((code) => !actualReasons.includes(code)),
        unexpected: actualReasons.filter((code) => !allowed.has(code)),
        actual: actualReasons,
      }
    : { result: 'not_implemented' }
  // A pack that expects no Claim (`triage.applies: false`) has no triage to score; a Claim that
  // formed anyway fails the pack's own assertions instead.
  const triage = oracle.triage.applies === false
    ? { result: 'not_applicable', expected: null, actual: severity || null }
    : !severity || severity === 'unassessed'
      ? { result: 'not_implemented', expected: oracle.triage.expected_class, actual: severity || null }
      : { result: severity === oracle.triage.expected_class ? 'pass' : 'fail', expected: oracle.triage.expected_class, actual: severity, reasons }
  const signalCodes = ((sources['staff:signals'] || {}).items || sources['staff:signals'] || []).map?.((item) => item.code) || []
  const reviewWritten = claimState.fraud_signal === 'review_required' || signalCodes.some((code) => !RETRIEVAL_ONLY_SIGNALS.has(code))
  const review = reviewWritten
    ? {
        result: claimState.fraud_signal === oracle.review_indicators.expected_fraud_signal ? 'pass' : 'fail',
        expected: oracle.review_indicators.expected_fraud_signal,
        actual: claimState.fraud_signal,
        false_positive: oracle.review_indicators.expected_fraud_signal === 'none' && claimState.fraud_signal === 'review_required',
        false_negative: oracle.review_indicators.expected_fraud_signal === 'review_required' && claimState.fraud_signal !== 'review_required',
      }
    : { result: 'not_implemented', expected: oracle.review_indicators.expected_fraud_signal, signal_codes: signalCodes }
  const innocentControls = (oracle.design.innocent_controls || []).map((control) => ({ control, flagged: reviewWritten && claimState.fraud_signal === 'review_required' }))

  // Facts: the confirmed value of every expected fact; optional facts must match when present.
  // The staff field list (`items: [{code, field}]`) holds the full form; the claimant's form is the
  // fallback when the staff read failed.
  const staffItems = (sources['staff:fields'] || {}).items
  const form = staffItems ? Object.fromEntries(staffItems.map((item) => [item.code, item.field])) : claim.form || {}
  const factResults = Object.entries(oracle.expected_facts).map(([code, expected]) => {
    const record = form[code]
    const actual = record && typeof record === 'object' && 'value' in record ? record.value : record
    const status = record && record.status
    return { code, expected, actual: actual ?? null, status: status || null, result: actual !== undefined && sameValue(code, actual, expected) && (!status || status === 'confirmed') ? 'pass' : 'fail' }
  })
  const optionalResults = Object.entries(oracle.optional_facts || {}).filter(([code]) => form[code] !== undefined).map(([code, expected]) => {
    const actual = form[code] && typeof form[code] === 'object' ? form[code].value : form[code]
    return { code, expected, actual, result: sameValue(code, actual, expected) ? 'pass' : 'fail' }
  })
  const incidentTime = factResults.find((item) => item.code === 'incident.occurred_at') || null

  // Assertions.
  const assertions = [...(oracle.assertions || []), ...globalAssertions(casesDir, oracle.family)].map((assertion) => {
    const judged = assertion.judge === 'state' ? judgeState(sources, assertion) : assertion.judge === 'text' ? judgeText(agentText, assertion) : { result: 'needs_human', detail: assertion.question }
    return { id: assertion.id, kind: assertion.kind, judge: assertion.judge, bind_at_rc1: Boolean(assertion.bind_at_rc1), ...judged }
  })

  // Staff side: what the claimant's questions look like in the staff to-answer list.
  const staffOpenItems = (staffClaim.open_items || []).map((item) => ({ owner: item.owner, state: item.state, subject: item.subject, claimant_wording: item.claimant_wording || null }))

  return { case_id: run.case_id, scenario_category: oracle.scenario_category, evidence, journey, triage, review, innocent_controls: innocentControls, facts: factResults, optional_facts: optionalResults, incident_time: incidentTime, assertions, staff_open_items: staffOpenItems }
}

function summarise(allScores) {
  // Packs whose end-state reads are incomplete are listed but kept out of every count.
  const incomplete = allScores.filter((s) => !s.evidence.complete)
  const scores = allScores.filter((s) => s.evidence.complete)
  const count = (predicate) => scores.filter(predicate).length
  const lines = [
    '| Pack | Category | Outcome | Claim | No follow-up | Messages | Questions | Time (s) | Turn median/max (ms) | Facts | Triage | Review | Assertions pass/fail/other |',
    '|---|---|---|---|---|---|---|---|---|---|---|---|---|',
  ]
  for (const s of incomplete) {
    lines.push(`| ${s.case_id} | ${s.scenario_category} | ${s.journey.outcome} | ${s.journey.claim_number || 'None'} | evidence incomplete: ${s.evidence.missing_reads.join(', ')} | | | | | | | | |`)
  }
  for (const s of scores) {
    const facts = `${s.facts.filter((f) => f.result === 'pass').length}/${s.facts.length}`
    const a = s.assertions
    const triageReasons = s.triage.reasons && s.triage.reasons.result !== 'not_implemented' ? ` (reasons ${s.triage.reasons.result})` : ''
    lines.push(`| ${s.case_id} | ${s.scenario_category} | ${s.journey.outcome} | ${s.journey.claim_number || 'None'} | ${s.journey.completed_without_follow_up ? 'Yes' : 'No'} | ${s.journey.claimant_messages} | ${s.journey.agent_questions} | ${s.journey.duration_s} | ${s.journey.turn_ms_median}/${s.journey.turn_ms_max} | ${facts} | ${s.triage.result}${triageReasons} | ${s.review.result} | ${a.filter((x) => x.result === 'pass').length}/${a.filter((x) => x.result === 'fail').length}/${a.filter((x) => !['pass', 'fail'].includes(x.result)).length} |`)
  }
  const lodgedFirst = count((s) => s.journey.outcome === 'lodged_first_time')
  const lodgedRetry = count((s) => s.journey.outcome === 'lodged_after_retry')
  const scoredTriage = scores.filter((s) => !['not_implemented', 'not_applicable'].includes(s.triage.result))
  const reasonsPass = scoredTriage.filter((s) => s.triage.reasons && s.triage.reasons.result === 'pass').length
  return [
    `Evidence incomplete (kept out of every count): ${incomplete.length}${incomplete.length ? ` (${incomplete.map((s) => s.case_id).join(', ')})` : ''}.`,
    `Packs: ${scores.length}. Lodged first time: ${lodgedFirst}. Lodged after a retry: ${lodgedRetry}. Stuck: ${count((s) => s.journey.outcome === 'stuck')}. Not run: ${count((s) => s.journey.outcome === 'runner_not_implemented')}.`,
    `Completed without follow-up (lodged, nothing owed by the claimant, no missing-information triage reason): ${count((s) => s.journey.completed_without_follow_up)}/${scores.length}. Within the effort target (under 5 minutes and under 10 questions): ${count((s) => s.journey.effort_within_target)}/${scores.length}.`,
    `Triage scored: ${scoredTriage.length} (class pass ${scoredTriage.filter((s) => s.triage.result === 'pass').length}, reasons pass ${reasonsPass}); not implemented: ${count((s) => s.triage.result === 'not_implemented')}; not applicable (no Claim expected): ${count((s) => s.triage.result === 'not_applicable')}. Review signals not implemented: ${count((s) => s.review.result === 'not_implemented')}.`,
    '',
    ...lines,
  ].join('\n')
}

function main() {
  const runDir = process.argv[2]
  const casesDir = (process.env.CORPUS_CASES_DIR || '').trim()
  if (!runDir || !casesDir) throw new Error('Usage: CORPUS_CASES_DIR=... node score.cjs <run folder>')
  const scores = fs.readdirSync(runDir)
    .filter((name) => fs.existsSync(path.join(runDir, name, 'run.json')))
    .map((name) => scorePack(path.join(runDir, name), casesDir))
  for (const s of scores) fs.writeFileSync(path.join(runDir, s.case_id, 'score.json'), JSON.stringify(s, null, 1))
  const summary = summarise(scores)
  fs.writeFileSync(path.join(runDir, 'summary.md'), `${summary}\n`)
  console.log(summary)
}

if (require.main === module) main()

module.exports = { scorePack, summarise, resolvePath, calendarDay, sameValue }
