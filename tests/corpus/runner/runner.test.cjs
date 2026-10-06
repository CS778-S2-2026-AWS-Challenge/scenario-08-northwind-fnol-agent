// The runner recognises the same question asked again (#1222). Nothing here opens a browser.
// Run with: node --test tests/corpus/runner/runner.test.cjs
const assert = require('node:assert/strict')
const { test } = require('node:test')

const { questionKey } = require('./runner.cjs')

test('the same question asked again gives the same key, and a reply without a question gives none', () => {
  const first = questionKey('Thanks for the details. What is the vehicle registration number?')
  assert.equal(first, 'what is the vehicle registration number')
  assert.equal(questionKey('Got it. What is the vehicle registration number?'), first)
  assert.notEqual(questionKey('What is the vehicle colour?'), first)
  assert.equal(questionKey('Your claim is ready. We will be in touch.'), null)
  assert.equal(questionKey('Was anyone hurt? Is the car drivable?'), 'was anyone hurt | is the car drivable')
})
