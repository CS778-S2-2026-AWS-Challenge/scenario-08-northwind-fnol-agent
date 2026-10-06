// The runner recognises the same question asked again (#1222). Nothing here opens a browser.
// Run with: node --test tests/corpus/runner/runner.test.cjs
const assert = require('node:assert/strict')
const { test } = require('node:test')

const { questionSentences, trackQuestions } = require('./runner.cjs')

test('each question sentence of a reply is listed on its own, normalised', () => {
  assert.deepEqual(questionSentences('Thanks for the details. What is the vehicle registration number?'), ['what is the vehicle registration number'])
  assert.deepEqual(questionSentences('Got it. What is the vehicle registration number?'), ['what is the vehicle registration number'])
  assert.deepEqual(questionSentences('Was anyone hurt? Is the car drivable?'), ['was anyone hurt', 'is the car drivable'])
  assert.deepEqual(questionSentences('A few things:\n1. When did it happen?\n2. Where was the car?'), ['when did it happen', 'where was the car'])
  assert.deepEqual(questionSentences('Is it drivable? Is it drivable?'), ['is it drivable'])
  assert.deepEqual(questionSentences('Your claim is ready. We will be in touch.'), [])
})

test('a question repeated inside replies that ask other things is answered once more, then stuck', () => {
  const asked = new Map()
  assert.deepEqual(trackQuestions(asked, 'What is the registration?'), { repeated: [], third: [] })
  assert.deepEqual(trackQuestions(asked, 'What is the registration? What colour is it?'), { repeated: ['what is the registration'], third: [] })
  assert.deepEqual(trackQuestions(asked, 'What is the registration? Is it drivable?'), { repeated: [], third: ['what is the registration'] })
})

test('questions asked once each are never a repeat, however they are grouped', () => {
  const asked = new Map()
  trackQuestions(asked, 'When did it happen? Where were you?')
  assert.deepEqual(trackQuestions(asked, 'Was anyone hurt?'), { repeated: [], third: [] })
  assert.deepEqual(trackQuestions(asked, 'Is the car drivable? Do you have photos?'), { repeated: [], third: [] })
})
