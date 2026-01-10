import React, { useEffect, useState } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import { useChatStore, type ChatSession } from '@/state/useChatStore'
import { documentAPI } from '@/lib/api'
import { toast } from 'sonner'
import { getErrorMessage } from '@/lib/utils'

interface Document {
  id: number
  name: string
  created_at: string
  updated_at: string
}

export default function DashboardPage() {
  const { sessions, loadSessions, createSession } = useChatStore()
  const navigate = useNavigate()
  const [documents, setDocuments] = useState<Document[]>([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    setLoading(true)
    try {
      await loadSessions()
      try {
        const response = await documentAPI.getDocuments()
        setDocuments(response.data.documents || [])
      } catch (error: unknown) {
        // Documents endpoint might not be implemented yet - silently fail
      }
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, 'Failed to load dashboard data'))
    } finally {
      setLoading(false)
    }
  }

  const handleNewChat = async () => {
    const session = await createSession()
    if (session) {
      navigate(`/chat/${session.id}`)
    }
  }

  // Sort sessions by updated_at (most recent first)
  const sortedSessions = [...sessions].sort((a, b) => {
    return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
  })

  // Sort documents by updated_at (most recent first)
  const sortedDocuments = [...documents].sort((a, b) => {
    return new Date(b.updated_at).getTime() - new Date(a.updated_at).getTime()
  })

  return (
    <div>
      <h1 className="text-3xl font-bold mb-6">Dashboard</h1>
      
      <div className="grid gap-4 md:grid-cols-2 mb-8">
        <div className="p-6 border rounded-lg">
          <h2 className="text-xl font-semibold mb-2">Start New Chat</h2>
          <p className="text-muted-foreground mb-4">
            Begin a new conversation with the agent
          </p>
          <Button onClick={handleNewChat}>New Chat</Button>
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

      {loading ? (
        <div className="text-center py-8">Loading...</div>
      ) : (
        <div className="grid gap-6 md:grid-cols-2">
          {/* Latest Chats */}
          <div>
            <h2 className="text-xl font-semibold mb-4">Latest Chats</h2>
            {sortedSessions.length === 0 ? (
              <p className="text-muted-foreground">No chats yet</p>
            ) : (
              <div className="space-y-2">
                {sortedSessions.slice(0, 5).map((session: ChatSession) => (
                  <Link
                    key={session.id}
                    to={`/chat/${session.id}`}
                    className="block p-4 border rounded-lg hover:bg-muted transition-colors"
                  >
                    <div className="flex justify-between items-start">
                      <div>
                        <h3 className="font-medium">{session.title || 'Untitled Chat'}</h3>
                        <p className="text-sm text-muted-foreground">
                          {new Date(session.updated_at).toLocaleDateString()}
                        </p>
                      </div>
                      <span className="text-xs text-muted-foreground">
                        {session.tokens_used.toLocaleString()} tokens
                      </span>
                    </div>
                  </Link>
                ))}
              </div>
            )}
          </div>

          {/* Latest Documents */}
          <div>
            <h2 className="text-xl font-semibold mb-4">Latest Documents</h2>
            {sortedDocuments.length === 0 ? (
              <p className="text-muted-foreground">No documents yet</p>
            ) : (
              <div className="space-y-2">
                {sortedDocuments.slice(0, 5).map((doc: Document) => (
                  <div
                    key={doc.id}
                    className="p-4 border rounded-lg hover:bg-muted transition-colors"
                  >
                    <div className="flex justify-between items-start">
                      <div>
                        <h3 className="font-medium">{doc.name}</h3>
                        <p className="text-sm text-muted-foreground">
                          {new Date(doc.updated_at).toLocaleDateString()}
                        </p>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
