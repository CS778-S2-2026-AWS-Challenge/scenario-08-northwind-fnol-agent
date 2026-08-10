import { useState } from 'react'

function App() {
  const [message, setMessage] = useState('')
  const [reply, setReply] = useState('')

  async function sendMessage() {
    setReply('Sending...')

    try {
      const response = await fetch(
        'http://127.0.0.1:8000/api/claims/message',
        {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            message: message,
          }),
        }
      )

      if (!response.ok) {
        throw new Error('Backend request failed')
      }

      const data = await response.json()
      setReply(data.reply)
    } catch (error) {
      setReply('Connection failed: ' + error.message)
    }
  }

  return (
    <div>
      <h1>Northwind Insurance</h1>
      <h2>Customer Claim Test</h2>

      <input
        value={message}
        onChange={(event) => setMessage(event.target.value)}
        placeholder="Describe what happened"
      />

      <button onClick={sendMessage}>
        Send
      </button>

      <p>Backend reply: {reply}</p>
    </div>
  )
}

export default App
