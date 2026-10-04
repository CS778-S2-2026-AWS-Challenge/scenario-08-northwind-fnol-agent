// Claimants choose between Northwind Assist services, not between model
// configurations. Each published runtime profile maps to one named service;
// a service whose profile is unavailable stays listed and is greyed out by the
// composer. Profile ids still travel to the backend unchanged.

export const PRIVATE_MODEL_PROFILE_ID = 'qwen-local'

export const MODEL_PRODUCTS = [
  {
    id: 'openrouter-gpt4o-mini',
    label: 'Northwind Assist (Default)',
    description: 'Fast. Reads your photos and documents.',
  },
  {
    id: 'bedrock-nova2-lite',
    label: 'Northwind Assist (Bedrock)',
    description: 'Runs on Amazon Bedrock. Reads your photos.',
  },
  {
    id: PRIVATE_MODEL_PROFILE_ID,
    label: 'Northwind Assist (Local)',
    description: "Text only. Your details stay on Northwind's own servers.",
  },
]

export function claimantModelChoices(models = []) {
  return MODEL_PRODUCTS.flatMap((product) => {
    const model = models.find((item) => item.id === product.id)
    return model ? [{ ...model, ...product }] : []
  })
}
