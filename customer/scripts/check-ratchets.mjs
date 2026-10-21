// Quality ratchets for the claimant client: numbers that may only go down.
//
// 1. App.jsx size and its useState count. New client state belongs in a state module
//    (see src/claimantFlow.js), not in the one large component.
// 2. Components that import api.js. Components render projections and raise events;
//    talking to the API is the job of App.jsx and controller modules.
// 3. Hard-coded colours (hex, rgb(), hsl()) per source file. Colours come from the
//    shared token library (frontend/shared/design-tokens.css).
//
// The current numbers live in quality-baseline.json. A change that genuinely needs a
// higher number raises it in that file in the same pull request, so the increase is
// visible in the diff and has to be explained there.

import { readFileSync, readdirSync, statSync } from 'node:fs'
import { join, relative, sep } from 'node:path'
import { fileURLToPath } from 'node:url'

const root = fileURLToPath(new URL('..', import.meta.url))
const src = join(root, 'src')
const baseline = JSON.parse(readFileSync(join(root, 'quality-baseline.json'), 'utf8'))

const SOURCE = /\.(js|jsx|css)$/
const TEST = /\.test\.(js|jsx)$/
const API_IMPORT = /from\s+['"](\.\.?\/)+api(\.js)?['"]/
const COLOUR = /#[0-9a-fA-F]{3,8}\b|\brgba?\(|\bhsla?\(/g

function sourceFiles(directory) {
  return readdirSync(directory).flatMap((name) => {
    const path = join(directory, name)
    if (statSync(path).isDirectory()) return sourceFiles(path)
    return SOURCE.test(name) && !TEST.test(name) ? [path] : []
  })
}

const posix = (path) => relative(src, path).split(sep).join('/')
const failures = []
const lowered = []

function atMost(label, actual, allowed) {
  if (actual > allowed) failures.push(`${label}: ${actual}, baseline allows ${allowed}`)
  else if (actual < allowed) lowered.push(`${label}: ${actual} (baseline ${allowed})`)
}

const app = readFileSync(join(src, 'App.jsx'), 'utf8')
atMost('App.jsx lines', app.split('\n').length - (app.endsWith('\n') ? 1 : 0), baseline.appJsxLines)
atMost('App.jsx useState calls', (app.match(/useState\(/g) || []).length, baseline.appJsxUseState)

const files = sourceFiles(src)
const allowedApiImports = new Set(baseline.componentsImportingApi)
for (const path of files) {
  const name = posix(path)
  if (!name.startsWith('components/')) continue
  const importsApi = API_IMPORT.test(readFileSync(path, 'utf8'))
  if (importsApi && !allowedApiImports.has(name)) {
    failures.push(`${name} imports api.js; move the request into App.jsx or a controller module`)
  } else if (!importsApi && allowedApiImports.has(name)) {
    lowered.push(`${name} no longer imports api.js`)
  }
}

for (const path of files) {
  const name = posix(path)
  const count = (readFileSync(path, 'utf8').match(COLOUR) || []).length
  const allowed = baseline.hardCodedColours[name] ?? 0
  if (count > allowed) {
    failures.push(`${name}: ${count} hard-coded colours, baseline allows ${allowed}; use a design token`)
  } else if (count < allowed) {
    lowered.push(`${name}: ${count} hard-coded colours (baseline ${allowed})`)
  }
}

if (lowered.length) {
  console.info('Below the baseline; lower quality-baseline.json to lock this in:')
  for (const line of lowered) console.info(`  ${line}`)
}
if (failures.length) {
  console.error('Quality ratchets failed:')
  for (const line of failures) console.error(`  ${line}`)
  process.exit(1)
}
console.info('Quality ratchets passed.')
