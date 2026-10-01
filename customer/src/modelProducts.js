// Claimants choose between two Northwind products, not between model
// configurations. The runtime may publish several cloud profiles; the claimant
// sees one of them as Northwind Assist and the on-premises profile as
// Northwind Private. Profile ids still travel to the backend unchanged.

export const PRIVATE_MODEL_PROFILE_ID = 'qwen-local'

export const MODEL_PRODUCTS = {
  assist: {
    label: 'Northwind Assist',
    description: 'Fast. Reads your photos and documents.',
  },
  private: {
    label: 'Northwind Private',
    description: "Text only. Your details stay on Northwind's own servers.",
  },
}

const isAvailable = (model) => model.availability !== 'unavailable'
const readsFiles = (model) => Boolean(model.image_input && model.document_input)

function assistModel(cloudModels, selectedModelId, defaultModelId) {
  const byId = (id) => cloudModels.find((model) => model.id === id)
  const selected = byId(selectedModelId)
  if (selected && isAvailable(selected)) return selected
  const preferred = byId(defaultModelId)
  if (preferred && isAvailable(preferred)) return preferred
  return cloudModels.find((model) => isAvailable(model) && readsFiles(model))
    || cloudModels.find(isAvailable)
    || cloudModels[0]
    || null
}

export function claimantModelChoices(models = [], { selectedModelId = '', defaultModelId = '' } = {}) {
  const privateModel = models.find((model) => model.id === PRIVATE_MODEL_PROFILE_ID)
  const cloudModels = models.filter((model) => model.id !== PRIVATE_MODEL_PROFILE_ID)
  const assist = assistModel(cloudModels, selectedModelId, defaultModelId)
  return [
    assist && { ...assist, ...MODEL_PRODUCTS.assist },
    privateModel && { ...privateModel, ...MODEL_PRODUCTS.private },
  ].filter(Boolean)
}
