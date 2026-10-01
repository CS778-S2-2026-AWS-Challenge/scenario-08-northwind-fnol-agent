// Plain-text views of conversation messages and evidence status.

export function messageText(message) {
  if (typeof message?.content?.text === 'string') return message.content.text
  if (typeof message?.content?.summary === 'string') return message.content.summary
  return ''
}

export function evidenceFileStatusLabel(fileStatus, status) {
  if (fileStatus === 'awaiting_upload') return 'Upload incomplete'
  if (fileStatus === 'processing') return 'Processing'
  if (fileStatus === 'failed') return 'Processing failed'
  if (fileStatus === 'ready') return 'Ready'
  if (fileStatus) return fileStatus
  return status === 'received' ? 'Received' : status
}
