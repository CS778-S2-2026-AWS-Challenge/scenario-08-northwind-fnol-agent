import { describe, expect, it } from 'vitest'

import { claimantModelChoices } from './modelProducts.js'

const qwen = { id: 'qwen-local', label: 'qwen3.8-27b', availability: 'available', image_input: false, document_input: false }
const gpt = { id: 'openrouter-gpt4o-mini', label: 'openai/gpt-4o', availability: 'available', image_input: true, document_input: true }
const gemini = { id: 'google-gemini35-flash-lite', label: 'gemini-3.5-flash-lite', availability: 'available', image_input: true, document_input: true }
const nova = { id: 'bedrock-nova2-lite', label: 'nova', availability: 'unavailable', image_input: true, document_input: false }

const summary = (choices) => choices.map(({ id, label }) => [label, id])

describe('claimant model products', () => {
  it('names each published service in a fixed order', () => {
    expect(summary(claimantModelChoices([qwen, nova, gpt, gemini]))).toEqual([
      ['Northwind Assist (Default)', 'openrouter-gpt4o-mini'],
      ['Northwind Assist (Bedrock)', 'bedrock-nova2-lite'],
      ['Northwind Assist (Local)', 'qwen-local'],
    ])
  })

  it('keeps an unavailable service listed so the composer can grey it out', () => {
    const bedrock = claimantModelChoices([nova]).at(0)
    expect(bedrock.availability).toBe('unavailable')
  })

  it('says Local handles text only', () => {
    const local = claimantModelChoices([qwen]).at(0)
    expect(local.description).toMatch(/Text only/)
    expect(local.image_input).toBe(false)
  })

  it('offers only what is published', () => {
    expect(summary(claimantModelChoices([gemini]))).toEqual([])
    expect(claimantModelChoices([])).toEqual([])
  })
})
