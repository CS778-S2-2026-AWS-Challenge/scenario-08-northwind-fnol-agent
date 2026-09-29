function attachmentMediaType(attachment) {
  const localFile = attachment?.previewFile || attachment?.stagedFile || attachment?.retryFile
  return attachment?.mediaType || attachment?.media_type || localFile?.type || ''
}

function requirementLabel({ image, document }) {
  if (image && document) return 'images and PDF documents'
  if (image) return 'images'
  if (document) return 'PDF documents'
  return ''
}

export function attachmentInputRequirements(attachments = []) {
  return attachments.reduce((requirements, attachment) => {
    const mediaType = attachmentMediaType(attachment)
    return {
      image: requirements.image || mediaType.startsWith('image/'),
      document: requirements.document || mediaType === 'application/pdf',
    }
  }, { image: false, document: false })
}

export function modelAttachmentCompatibility(attachments, model) {
  const requirements = attachmentInputRequirements(attachments)
  const missing = {
    image: requirements.image && Boolean(model) && model.image_input !== true,
    document: requirements.document && Boolean(model) && model.document_input !== true,
  }
  const compatible = !missing.image && !missing.document
  const requiredLabel = requirementLabel(requirements)
  const missingLabel = requirementLabel(missing)
  const attachedFileCount = attachments.filter((attachment) => attachmentMediaType(attachment)).length
  const attachmentCopy = attachedFileCount === 1
    ? 'Your file is still attached.'
    : 'Your files are still attached.'
  const unsupportedFileCount = attachments.filter((attachment) => {
    const mediaType = attachmentMediaType(attachment)
    return (missing.image && mediaType.startsWith('image/'))
      || (missing.document && mediaType === 'application/pdf')
  }).length
  const unsupportedFileCopy = unsupportedFileCount === 1 ? 'file' : 'files'

  return {
    compatible,
    hasRequirements: Boolean(requirements.image || requirements.document),
    statusLabel: !model || !requiredLabel
      ? ''
      : compatible
        ? `Supports ${requiredLabel}`
        : `Does not support ${missingLabel}`,
    message: compatible
      ? ''
      : `This model cannot process ${missingLabel}. ${attachmentCopy} Choose a model marked “Supports ${requiredLabel}” or remove the unsupported ${unsupportedFileCopy}.`,
  }
}
