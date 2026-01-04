import React, { useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { useAuthStore } from '@/state/useAuthStore'
import { useChatStore } from '@/state/useChatStore'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'

type ReactFormEvent = React.FormEvent<HTMLFormElement>
type ReactChangeEvent = React.ChangeEvent<HTMLInputElement>

export default function HomePage() {
  const { isAuthenticated } = useAuthStore()
  const { createSession } = useChatStore()
  const navigate = useNavigate()
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)

  const handleSubmit = async (e: ReactFormEvent) => {
    e.preventDefault()
    if (!input.trim() || !isAuthenticated) return

    const message = input.trim()
    setInput('')
    setSending(true)
    try {
      const session = await createSession()
      if (session) {
        navigate(`/chat/${session.id}`, { 
          state: { initialMessage: message } 
        })
      } else {
        toast.error('Failed to create chat session')
        setSending(false)
      }
    } catch (error: any) {
      toast.error('Failed to start chat')
      setSending(false)
    }
  }

  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh]">
      <h1 className="text-4xl font-bold mb-4">AI Agent Chat</h1>
      <p className="text-muted-foreground mb-8">
        Chat with AI agents powered by LangChain and LangGraph
      </p>
      
      {isAuthenticated ? (
        <div className="w-full max-w-2xl">
          <form onSubmit={handleSubmit} className="flex gap-2">
            <input
              type="text"
              value={input}
              onChange={(e: ReactChangeEvent) => setInput(e.target.value)}
              placeholder="Ask me anything..."
              className="flex-1 px-4 py-3 border rounded-lg focus:outline-none focus:ring-2 focus:ring-primary"
              disabled={sending}
            />
            <Button type="submit" size="lg" disabled={sending || !input.trim()}>
              {sending ? 'Starting...' : 'Send'}
            </Button>
          </form>
        </div>
      ) : (
        <div className="flex gap-4">
          <Link to="/login">
            <Button variant="outline" size="lg">Login</Button>
          </Link>
          <Link to="/signup">
            <Button size="lg">Sign Up</Button>
          </Link>
        </div>
      )}
    </div>
  )
}
