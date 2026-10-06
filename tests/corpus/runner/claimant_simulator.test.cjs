// The claimant backend is chosen from the environment (#1222). Nothing here calls a model.
// Run with: node --test tests/corpus/runner/claimant_simulator.test.cjs
const assert = require('node:assert/strict')
const { test } = require('node:test')

const { claimantFromEnvironment } = require('./claimant_simulator.cjs')

test('Ollama is the default backend and needs its server and model', () => {
  assert.equal(claimantFromEnvironment({ CLAIMANT_OLLAMA_URL: 'http://127.0.0.1:11434', CLAIMANT_MODEL: 'qwen3.8:27b' }).backend, 'ollama')
  assert.throws(() => claimantFromEnvironment({ CLAIMANT_MODEL: 'qwen3.8:27b' }), /CLAIMANT_OLLAMA_URL/)
})

test('the Claude CLI backend needs no server and defaults to haiku', async () => {
  const claimant = claimantFromEnvironment({ CLAIMANT_BACKEND: 'claude' })
  assert.equal(claimant.backend, 'claude')
  assert.equal(typeof claimant.ask, 'function')
})

test('an unknown backend is refused instead of falling back', () => {
  assert.throws(() => claimantFromEnvironment({ CLAIMANT_BACKEND: 'openai', CLAIMANT_OLLAMA_URL: 'http://x', CLAIMANT_MODEL: 'm' }), /ollama or claude/)
})
