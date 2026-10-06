// The claimant simulator's view of one controlled-corpus pack, and the guard that keeps the
// oracle and the setup out of it (#1222).
//
// The view is built field by field, not file by file. The simulator sees what a claimant knows:
// the first message as written, the persona and answer policy, the facts, and for each material
// the file and a hand-written plain-language label. It never sees `evidence_kind`, how a material
// was generated (prompt, purpose), materials marked `include: false`, `setup.json` or `oracle/`.
const fs = require('node:fs')
const path = require('node:path')

function readJson(file) {
  return JSON.parse(fs.readFileSync(file, 'utf8'))
}

function buildClaimantView(caseDir, labels) {
  const caseId = path.basename(path.resolve(caseDir))
  const factsDoc = readJson(path.join(caseDir, 'input', 'facts.json'))
  const materialsDoc = readJson(path.join(caseDir, 'input', 'materials.json'))
  // The runner reads provenance only for each file's material id and include flag.
  const provenance = readJson(path.join(caseDir, 'provenance.json'))
  const byFile = new Map(provenance.materials.map((entry) => [entry.file, { id: entry.id, include: entry.include }]))
  const caseLabels = labels[caseId]
  if (!caseLabels) throw new Error(`No material labels for ${caseId}`)

  const materials = []
  for (const entry of materialsDoc.materials) {
    const origin = byFile.get(entry.file)
    if (!origin) throw new Error(`${caseId}: ${entry.file} has no provenance entry`)
    if (origin.include === false) continue
    const label = caseLabels[origin.id]
    if (!label) throw new Error(`${caseId}: no label for material ${origin.id}`)
    materials.push({ id: origin.id, file: entry.file, label, available_from: entry.available_from })
  }

  return {
    case_id: caseId,
    // Sent exactly as written, typos included; only the file's final line break is dropped.
    initial_message: fs.readFileSync(path.join(caseDir, 'input', 'initial_message.txt'), 'utf8').replace(/\r?\n$/, ''),
    persona: factsDoc.persona,
    answer_policy: factsDoc.answer_policy,
    facts: factsDoc.facts,
    materials,
  }
}

function stringLeaves(value, out = new Set()) {
  if (typeof value === 'string') {
    const text = value.trim()
    if (text.length >= 4) out.add(text)
  } else if (Array.isArray(value)) {
    for (const item of value) stringLeaves(item, out)
  } else if (value && typeof value === 'object') {
    for (const item of Object.values(value)) stringLeaves(item, out)
  }
  return out
}

// Values that exist only in the oracle or the setup. A value the claimant legitimately knows (a
// policy number in the facts, the product family) is not a leak, and neither is a word of the
// fixed prompt template (`scaffold`), which is code and carries nothing from the pack.
function hiddenValues(caseDir, view, scaffold = '') {
  const hidden = stringLeaves(readJson(path.join(caseDir, 'oracle', 'labels.json')))
  stringLeaves(readJson(path.join(caseDir, 'setup.json')), hidden)
  const allowed = `${JSON.stringify(view)}\n${scaffold}`.toLowerCase()
  return [...hidden].filter((value) => !allowed.includes(value.toLowerCase()))
}

function assertNoLeak(promptPart, hidden) {
  const text = promptPart.toLowerCase()
  const leaked = hidden.filter((value) => text.includes(value.toLowerCase()))
  if (leaked.length) {
    throw new Error(`The claimant prompt contains ${leaked.length} oracle or setup value(s), e.g. ${JSON.stringify(leaked[0].slice(0, 80))}`)
  }
}

module.exports = { buildClaimantView, hiddenValues, assertNoLeak, stringLeaves }
