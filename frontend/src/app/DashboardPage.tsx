// @ts-nocheck
import React from 'react'
import { Link } from 'react-router-dom'
import { Button } from '@/components/ui/button'

export default function DashboardPage() {
  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Dashboard</h1>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="p-6 border rounded-lg">
          <h2 className="text-xl font-semibold mb-2">Start New Chat</h2>
          <p className="text-muted-foreground mb-4">
            Begin a new conversation with the AI agent
          </p>
          <Link to="/chat">
            <Button>New Chat</Button>
          </Link>
        </div>
        <div className="p-6 border rounded-lg">
          <h2 className="text-xl font-semibold mb-2">Documents</h2>
          <p className="text-muted-foreground mb-4">
            Upload and manage your documents
          </p>
          <Link to="/documents">
            <Button variant="outline">View Documents</Button>
          </Link>
        </div>
      </div>
    </div>
  )
}
