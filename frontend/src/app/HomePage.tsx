import React from 'react'
import { Link } from 'react-router-dom'
import { useAuthStore } from '@/state/useAuthStore'
import { Button } from '@/components/ui/button'

export default function HomePage() {
  const { isAuthenticated } = useAuthStore()

  return (
    <div className="flex flex-col items-center justify-center min-h-[60vh]">
      <h1 className="text-4xl font-bold mb-4">AI Agent Chat</h1>
      <p className="text-muted-foreground mb-8">
        Chat with AI agents powered by LangChain and LangGraph
      </p>
      {isAuthenticated ? (
        <Link to="/dashboard">
          <Button size="lg">Go to Dashboard</Button>
        </Link>
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
