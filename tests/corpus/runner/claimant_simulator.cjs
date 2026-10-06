// The claimant simulator (#1222): a model that plays the claimant. Everything it knows is in its
// prompt, the claimant view and what the screen shows; it has no tools and cannot open a file.
// Two backends, chosen with CLAIMANT_BACKEND, both independent of the system under test and of
// the team's keys:
//   ollama  the operator's own Ollama server (CLAIMANT_OLLAMA_URL, CLAIMANT_MODEL); temperature 0
//           and a fixed seed, so the same screen gives the same reply. The default.
//   claude  the Claude Code CLI on the operator's own login, with no tools, no MCP servers and no
//           session, from an empty working directory (CLAIMANT_MODEL, default haiku). Its
//           temperature cannot be set, so replies can differ run to run.
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const { spawnSync } = require('node:child_process')

const SYSTEM_PROMPT = `You play a person reporting an insurance claim to Northwind Insurance through its website chat.
You are the claimant, not an assistant. Stay in character for the whole conversation.

Rules:
- Answer only what the latest message on the screen asks, using only the facts in your brief.
- Never make anything up. Do not add details, opinions or consequences that are not in your brief (for
  example how safe the car is, how bad the damage looks, or what you think it will cost) unless the brief
  states them.
- If the brief does not contain the answer, say you don't know or don't have it, in your own voice.
- Do not volunteer facts you were not asked about. Do not correct the agent, hint at what it should ask,
  or mention documents it has not asked for, unless your persona says you would.
- Hand over a material only when the agent explicitly asks you to send, upload or share that document or
  photo, or the screen shows an item with an Upload button for it. Then use the matching material id from
  your brief. If you have nothing that matches, say so. A question about a fact (for example a cost or a
  date) is not a request for a document: answer it in words and upload nothing.
- A material that is not available yet: say you will have it later.
- You send each document or photo once. When the agent describes or summarises a file you already sent,
  it is reading that file: do not apologise and do not send it again. If the agent asks again for a file
  you already sent, say you already sent it.
- Your documents and photos are marked as synthetic test material. That is normal; when the agent mentions
  it, the file is still the one you meant to send.
- Answer exactly the question asked. Do not add other facts, even related ones, and do not ask the agent
  questions back unless your persona says you would.
- Speak the way your persona describes. Keep answers as short as a real person typing in a chat.
- If the latest message asks you nothing (it only thanks you, confirms something, or says something is
  coming), type nothing: leave the message empty.
- To press a button on the screen, put its exact label from "Buttons you can press" in "press"; otherwise
  leave "press" empty. Press a button when the agent asks you to use it, or when it is how you do what you
  already agreed to in the conversation. Never press an Edit button.
- When you press a button, that is all you do this turn: leave the message empty and upload nothing.
- When the agent asks you to check a summary, compare it with your brief and press "Looks right" (or "All
  correct") when it is right. When the agent says your part is done and a button such as "Check your
  details", "Add payout and contact details" or "Review and agree" is on the screen, press it: that is how
  you finish your claim.
- Giving permission to share your details is your own choice: follow your persona, and otherwise agree only
  to what you already said yes to in the conversation.

Reply with JSON only, no other text:
{"message": "<what you type in the chat box, may be empty>", "upload": ["<material id>", ...], "press": "<button label or empty>"}`

function claimantBrief(view) {
  const facts = Object.entries(view.facts).map(([key, value]) => `- ${key}: ${JSON.stringify(value)}`)
  const materials = view.materials.map((item) => `- ${item.id}: ${item.label} (available from: ${item.available_from})`)
  return [
    'YOUR BRIEF',
    `Persona: ${view.persona}`,
    `How you answer: ${view.answer_policy}`,
    'What you know:',
    ...facts,
    'Documents and photos you have (refer to them by id):',
    ...(materials.length ? materials : ['- none']),
  ].join('\n')
}

// The prompt has two parts. `brief` comes from the pack and is what the leak guard checks; `screen`
// is only the text the claimant can see on the page (the transcript, the latest reply, chips,
// cards and buttons). Network data is never part of it.
function buildClaimantPrompt(view, transcript, screen) {
  const brief = claimantBrief(view)
  const conversation = transcript.map((turn) => `${turn.who === 'claimant' ? 'You' : 'Northwind'}: ${turn.text}`).join('\n')
  const user = [
    brief,
    '',
    'CONVERSATION SO FAR',
    conversation || '(none)',
    '',
    'WHAT THE SCREEN SHOWS NOW',
    screen,
    '',
    'Write your next chat message as JSON.',
  ].join('\n')
  return { system: SYSTEM_PROMPT, brief, user }
}

// The fixed template with an empty brief: the words the prompt always contains.
function promptScaffold() {
  const empty = buildClaimantPrompt({ persona: '', answer_policy: '', facts: {}, materials: [] }, [], '')
  return `${empty.system}\n${empty.brief}`
}

function claudeExecutable() {
  const fromEnv = process.env.CLAIMANT_CLAUDE_EXE
  if (fromEnv) return fromEnv
  const shim = path.join(path.dirname(process.execPath), 'node_modules', '@anthropic-ai', 'claude-code', 'bin', process.platform === 'win32' ? 'claude.exe' : 'claude')
  if (fs.existsSync(shim)) return shim
  throw new Error('Claude Code CLI not found; set CLAIMANT_CLAUDE_EXE')
}

// Variables a host app injects for its own session; the simulator uses the operator's CLI login.
function cleanEnvironment() {
  const env = { ...process.env }
  for (const name of Object.keys(env)) {
    if (name === 'ANTHROPIC_BASE_URL' || name === 'CLAUDECODE' || name.startsWith('CLAUDE_CODE_') || name.startsWith('CLAUDE_AGENT_') || name === 'CLAUDE_PID') {
      delete env[name]
    }
  }
  return env
}

function askClaimant(prompt, { model = 'haiku', timeoutMs = 120000 } = {}) {
  const sandbox = fs.mkdtempSync(path.join(os.tmpdir(), 'corpus-claimant-'))
  const started = Date.now()
  try {
    const run = spawnSync(claudeExecutable(), [
      '-p', '--model', model, '--tools', '', '--strict-mcp-config', '--no-session-persistence',
      '--system-prompt', prompt.system, '--output-format', 'json',
    ], { input: prompt.user, cwd: sandbox, env: cleanEnvironment(), encoding: 'utf8', timeout: timeoutMs, windowsHide: true })
    if (run.error) throw run.error
    const envelope = JSON.parse(run.stdout)
    if (envelope.is_error || envelope.terminal_reason === 'api_error') {
      throw new Error(`claimant model call failed: ${String(envelope.result).slice(0, 200)}`)
    }
    const raw = String(envelope.result || '').trim().replace(/^```(?:json)?\s*|\s*```$/g, '')
    const reply = JSON.parse(raw)
    return {
      message: typeof reply.message === 'string' ? reply.message : '',
      upload: Array.isArray(reply.upload) ? reply.upload.map(String) : [],
      press: typeof reply.press === 'string' ? reply.press.trim() : '',
      model: Object.keys(envelope.modelUsage || {}).join(',') || model,
      cost_usd: envelope.total_cost_usd || 0,
      ms: Date.now() - started,
      raw,
    }
  } finally {
    // The CLI can still hold the directory for a moment on Windows; a leftover empty folder is harmless.
    try {
      fs.rmSync(sandbox, { recursive: true, force: true, maxRetries: 5, retryDelay: 200 })
    } catch {
      // ignore
    }
  }
}

const REPLY_SCHEMA = {
  type: 'object',
  properties: { message: { type: 'string' }, upload: { type: 'array', items: { type: 'string' } }, press: { type: 'string' } },
  required: ['message', 'upload', 'press'],
}

// The operator's own model served by Ollama (for example over Tailscale). Temperature 0 and a
// fixed seed make a rerun with the same screen give the same reply.
async function askOllamaClaimant(prompt, { url, model, seed = 20261006, timeoutMs = 300000 }) {
  if (!url || !model) throw new Error('The Ollama claimant needs CLAIMANT_OLLAMA_URL and CLAIMANT_MODEL')
  const started = Date.now()
  const response = await fetch(`${url.replace(/\/$/, '')}/api/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    signal: AbortSignal.timeout(timeoutMs),
    body: JSON.stringify({
      model,
      stream: false,
      think: false,
      format: REPLY_SCHEMA,
      options: { temperature: 0, seed, num_ctx: 16384 },
      messages: [{ role: 'system', content: prompt.system }, { role: 'user', content: prompt.user }],
    }),
  })
  if (!response.ok) throw new Error(`claimant model call failed: HTTP ${response.status} ${(await response.text()).slice(0, 200)}`)
  const body = await response.json()
  const raw = String((body.message || {}).content || '').trim()
  const reply = JSON.parse(raw)
  return {
    message: typeof reply.message === 'string' ? reply.message : '',
    upload: Array.isArray(reply.upload) ? reply.upload.map(String) : [],
    press: typeof reply.press === 'string' ? reply.press.trim() : '',
    model: body.model || model,
    cost_usd: 0,
    tokens: { prompt: body.prompt_eval_count || 0, output: body.eval_count || 0 },
    ms: Date.now() - started,
    raw,
  }
}

// Name and digest of the claimant model, recorded with every run so it can be reproduced.
async function describeOllamaModel({ url, model }) {
  const response = await fetch(`${url.replace(/\/$/, '')}/api/tags`, { signal: AbortSignal.timeout(15000) })
  const tags = await response.json()
  const entry = (tags.models || []).find((item) => item.name === model)
  if (!entry) throw new Error(`Model ${model} is not on ${url}`)
  return { backend: 'ollama', url, model, digest: entry.digest, parameter_size: entry.details?.parameter_size, quantization: entry.details?.quantization_level, temperature: 0 }
}

function describeClaudeCli(model) {
  const run = spawnSync(claudeExecutable(), ['--version'], { env: cleanEnvironment(), encoding: 'utf8', windowsHide: true, timeout: 30000 })
  return {
    backend: 'claude-cli',
    model,
    cli_version: String(run.stdout || '').trim(),
    temperature: 'CLI default, cannot be set',
    note: 'Replies can differ run to run; the exact model of every reply is in claimant.jsonl.',
  }
}

// The claimant chosen by CLAIMANT_BACKEND: `describe()` for the run record, `ask(prompt)` per turn.
function claimantFromEnvironment(env = process.env) {
  const backend = String(env.CLAIMANT_BACKEND || 'ollama').trim()
  if (backend === 'ollama') {
    const config = { url: String(env.CLAIMANT_OLLAMA_URL || '').trim(), model: String(env.CLAIMANT_MODEL || '').trim() }
    if (!config.url || !config.model) throw new Error('CLAIMANT_BACKEND=ollama needs CLAIMANT_OLLAMA_URL and CLAIMANT_MODEL')
    return { backend, describe: () => describeOllamaModel(config), ask: (prompt) => askOllamaClaimant(prompt, config) }
  }
  if (backend === 'claude') {
    const model = String(env.CLAIMANT_MODEL || 'haiku').trim()
    return { backend, describe: async () => describeClaudeCli(model), ask: async (prompt) => askClaimant(prompt, { model }) }
  }
  throw new Error(`CLAIMANT_BACKEND must be ollama or claude, not "${backend}"`)
}

module.exports = {
  askOllamaClaimant,
  describeOllamaModel,
  claimantFromEnvironment,
  SYSTEM_PROMPT,
  buildClaimantPrompt,
  claimantBrief,
  promptScaffold,
  askClaimant,
  cleanEnvironment,
}
