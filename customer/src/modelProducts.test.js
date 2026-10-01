import { describe, expect, it } from 'vitest'

import { claimantModelChoices } from './modelProducts.js'

const qwen = { id: 'qwen-local', label: 'qwen3.8-27b', availability: 'available', image_input: false, document_input: false }
const gpt = { id: 'openrouter-gpt4o-mini', label: 'openai/gpt-4o-mini', availability: 'available', image_input: true, document_input: true }
const gemini = { id: 'google-gemini35-flash-lite', label: 'gemini-3.5-flash-lite', availability: 'available', image_input: true, document_input: true }
const textOnly = { id: 'nowcoding-gpt55', label: 'gpt-5.5', availability: 'available', image_input: false, document_input: false }
const offline = { id: 'bedrock-nova2-lite', label: 'nova', availability: 'unavailable', image_input: true, document_input: true }

const summary = (choices) => choices.map(({ id, label }) => [label, id])

describe('claimant model products', () => {
  it('shows one cloud profile as Assist and the local profile as Private', () => {
    expect(summary(claimantModelChoices([qwen, gpt, gemini], { defaultModelId: 'openrouter-gpt4o-mini' })))
      .toEqual([['Northwind Assist', 'openrouter-gpt4o-mini'], ['Northwind Private', 'qwen-local']])
  })

  it('says Private handles text only', () => {
    const [, privateChoice] = claimantModelChoices([qwen, gpt])
    expect(privateChoice.description).toMatch(/Text only/)
    expect(privateChoice.image_input).toBe(false)
  })

  it('keeps the selected cloud profile behind Assist', () => {
    expect(summary(claimantModelChoices([qwen, gpt, gemini], {
      selectedModelId: 'google-gemini35-flash-lite',
      defaultModelId: 'openrouter-gpt4o-mini',
    }))[0]).toEqual(['Northwind Assist', 'google-gemini35-flash-lite'])
  })

  it('prefers an available profile that reads files when the default is Private', () => {
    expect(summary(claimantModelChoices([qwen, offline, textOnly, gemini], { defaultModelId: 'qwen-local' }))[0])
      .toEqual(['Northwind Assist', 'google-gemini35-flash-lite'])
    expect(summary(claimantModelChoices([qwen, offline, textOnly], { defaultModelId: 'qwen-local' }))[0])
      .toEqual(['Northwind Assist', 'nowcoding-gpt55'])
  })

  it('offers whatever is published', () => {
    expect(summary(claimantModelChoices([qwen]))).toEqual([['Northwind Private', 'qwen-local']])
    expect(summary(claimantModelChoices([gpt]))).toEqual([['Northwind Assist', 'openrouter-gpt4o-mini']])
    expect(claimantModelChoices([])).toEqual([])
  })
})
