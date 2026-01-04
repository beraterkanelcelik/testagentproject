import React, { useState, useEffect, useRef } from 'react'

// Type declarations for React event types
type ReactMouseEvent = React.MouseEvent
type ReactFormEvent = React.FormEvent<HTMLFormElement>
type ReactChangeEvent = React.ChangeEvent<HTMLInputElement>
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { useChatStore, type Message } from '@/state/useChatStore'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { createAgentStream, StreamEvent } from '@/lib/streaming'
import { chatAPI } from '@/lib/api'

interface ChatStats {
  session_id: number
  title: string
  created_at: string
  updated_at: string
  total_messages: number
  user_messages: number
  assistant_messages: number
  total_tokens: number
  message_tokens: number
  input_tokens: number
  output_tokens: number
  cached_tokens: number
  model_used: string | null
  cost: {
    total: number
    input: number
    output: number
    cached: number
  }
  agent_usage: Record<string, number>
  tool_usage: Record<string, number>
}

export default function ChatPage() {
  const { sessionId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [activeTab, setActiveTab] = useState<'chat' | 'stats'>('chat')
  const [stats, setStats] = useState<ChatStats | null>(null)
  const [loadingStats, setLoadingStats] = useState(false)
  const streamRef = useRef<ReturnType<typeof createAgentStream> | null>(null)
  const initialMessageSentRef = useRef(false)
  const initialMessageRef = useRef<string | null>(null)

  const {
    sessions,
    currentSession,
    messages,
    loading,
    error,
    loadSessions,
    createSession,
    loadSession,
    loadMessages,
    deleteSession,
    clearCurrentSession,
    set,
  } = useChatStore()

  useEffect(() => {
    loadSessions()
  }, [loadSessions])

  // Store initial message from location state when component mounts or sessionId changes
  useEffect(() => {
    // Reset refs when sessionId changes
    initialMessageSentRef.current = false
    initialMessageRef.current = null
    
    const state = location.state as { initialMessage?: string } | null
    if (state?.initialMessage) {
      initialMessageRef.current = state.initialMessage
      // Clear the location state immediately to prevent re-triggering
      window.history.replaceState({ ...window.history.state, state: null }, '')
    }
  }, [sessionId])

  useEffect(() => {
    if (sessionId) {
      loadSession(Number(sessionId))
      loadChatStats(Number(sessionId))
      initialMessageSentRef.current = false
    } else {
      clearCurrentSession()
    }
  }, [sessionId, loadSession, clearCurrentSession])

  // Handle initial message from navigation state - only once when session is loaded
  useEffect(() => {
    if (
      initialMessageRef.current &&
      currentSession &&
      messages.length === 0 &&
      !initialMessageSentRef.current &&
      !sending
    ) {
      const initialMessage = initialMessageRef.current
      initialMessageSentRef.current = true
      
      // Auto-send the initial message after a short delay to ensure session is ready
      const timeoutId = setTimeout(() => {
        handleSendWithMessage(initialMessage)
        // Clear the ref after sending
        initialMessageRef.current = null
      }, 500)
      
      return () => {
        clearTimeout(timeoutId)
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [currentSession?.id, messages.length, sending])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    // Refresh stats when messages change
    if (currentSession && activeTab === 'stats') {
      loadChatStats(currentSession.id)
    }
  }, [messages, currentSession, activeTab])

  const loadChatStats = async (sessionId: number) => {
    setLoadingStats(true)
    try {
      const response = await chatAPI.getStats(sessionId)
      setStats(response.data)
    } catch (error: any) {
      console.error('Failed to load stats:', error)
    } finally {
      setLoadingStats(false)
    }
  }

  const handleNewChat = async () => {
    const newSession = await createSession()
    if (newSession) {
      navigate(`/chat/${newSession.id}`)
    }
  }

  const handleSelectSession = (id: number) => {
    navigate(`/chat/${id}`)
  }

  const handleSendWithMessage = async (messageContent: string) => {
    if (!messageContent.trim() || sending || !currentSession) return

    const content = messageContent.trim()
    setSending(true)

    // Add user message immediately
    const userMessage = {
      id: Date.now(),
      role: 'user' as const,
      content,
      tokens_used: 0,
      created_at: new Date().toISOString(),
    }
    set((state: { messages: Message[] }) => ({
      messages: [...state.messages, userMessage],
    }))

    // Create streaming message placeholder
    const assistantMessageId = Date.now() + 1
    set((state: { messages: Message[] }) => ({
      messages: [
        ...state.messages,
        {
          id: assistantMessageId,
          role: 'assistant' as const,
          content: '',
          tokens_used: 0,
          created_at: new Date().toISOString(),
          metadata: { agent_name: 'greeter' },
        },
      ],
    }))

    try {
      const token = localStorage.getItem('access_token')
      if (!token) {
        throw new Error('No authentication token')
      }

      // Use streaming
      const stream = createAgentStream(
        currentSession.id,
        content,
        token,
        (event: StreamEvent) => {
          if (event.type === 'token') {
            // Update the assistant message in store by appending the new token
            set((state: { messages: Message[] }) => {
              const currentMessage = state.messages.find((msg: Message) => msg.id === assistantMessageId)
              const currentContent = currentMessage?.content || ''
              const newContent = currentContent + event.data
              
              return {
                messages: state.messages.map((msg: Message) =>
                  msg.id === assistantMessageId
                    ? { ...msg, content: newContent }
                    : msg
                ),
              }
            })
          } else if (event.type === 'error') {
            toast.error(event.data?.error || 'Streaming error occurred')
            setSending(false)
          }
        },
        (error: Error) => {
          toast.error(error.message || 'Streaming connection error')
          setSending(false)
        },
        () => {
          // Stream complete, reload messages to get final saved version
          loadMessages(currentSession.id)
          loadChatStats(currentSession.id)
          setSending(false)
        }
      )

      streamRef.current = stream
    } catch (error: any) {
      toast.error(error.message || 'Failed to send message')
      // Remove the placeholder assistant message on error
      set((state: { messages: Message[] }) => ({
        messages: state.messages.filter((msg: Message) => msg.id !== assistantMessageId),
      }))
      setSending(false)
    }
  }

  const handleSend = async () => {
    if (!input.trim()) return
    const content = input.trim()
    setInput('')
    await handleSendWithMessage(content)
  }

  // Cleanup stream on unmount
  useEffect(() => {
    return () => {
      if (streamRef.current) {
        streamRef.current.close()
      }
    }
  }, [])

  const handleDeleteSession = async (id: number, e: ReactMouseEvent) => {
    e.stopPropagation()
    if (confirm('Are you sure you want to delete this chat session?')) {
      await deleteSession(id)
      if (currentSession?.id === id) {
        navigate('/chat')
      }
    }
  }

  const getAgentName = (msg: Message): string => {
    if (msg.role === 'user') return ''
    return msg.metadata?.agent_name || 'assistant'
  }

  const formatAgentName = (name: string): string => {
    return name.charAt(0).toUpperCase() + name.slice(1)
  }

  return (
    <div className="flex h-[calc(100vh-200px)]">
      {/* Sidebar */}
      <div className="w-64 border-r flex flex-col">
        <div className="p-4 border-b">
          <Button onClick={handleNewChat} className="w-full">
            New Chat
          </Button>
        </div>
        <div className="flex-1 overflow-y-auto">
          {loading && sessions.length === 0 ? (
            <div className="p-4 text-center text-muted-foreground">Loading...</div>
          ) : sessions.length === 0 ? (
            <div className="p-4 text-center text-muted-foreground text-sm">
              No chat sessions yet. Create a new chat to get started.
            </div>
          ) : (
            <div className="divide-y">
              {sessions.map((session: { id: number; title: string; updated_at: string }) => (
                <div
                  key={session.id}
                  onClick={() => handleSelectSession(session.id)}
                  className={`p-3 cursor-pointer hover:bg-muted transition-colors ${
                    currentSession?.id === session.id ? 'bg-muted' : ''
                  }`}
                >
                  <div className="flex items-start justify-between">
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-sm truncate">
                        {session.title || 'Untitled Chat'}
                      </p>
                      <p className="text-xs text-muted-foreground mt-1">
                        {new Date(session.updated_at).toLocaleDateString()}
                      </p>
                    </div>
                    <button
                      onClick={(e: ReactMouseEvent) => handleDeleteSession(session.id, e)}
                      className="ml-2 text-muted-foreground hover:text-destructive"
                      title="Delete session"
                    >
                      ×
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* Chat Window */}
      <div className="flex-1 flex flex-col">
        {!currentSession ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center">
              <h2 className="text-xl font-semibold mb-2">No chat selected</h2>
              <p className="text-muted-foreground mb-4">
                Select a chat from the sidebar or create a new one
              </p>
              <Button onClick={handleNewChat}>New Chat</Button>
            </div>
          </div>
        ) : (
          <>
            {/* Chat Header */}
            <div className="border-b p-4">
              <div className="flex items-center justify-between">
                <div>
                  <h2 className="font-semibold">{currentSession.title || 'Untitled Chat'}</h2>
                  <p className="text-sm text-muted-foreground">
                    Created {new Date(currentSession.created_at).toLocaleDateString()}
                  </p>
                </div>
                {/* Tabs */}
                <div className="flex gap-2">
                  <Button
                    variant={activeTab === 'chat' ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => setActiveTab('chat')}
                  >
                    Chat
                  </Button>
                  <Button
                    variant={activeTab === 'stats' ? 'default' : 'outline'}
                    size="sm"
                    onClick={() => {
                      setActiveTab('stats')
                      loadChatStats(currentSession.id)
                    }}
                  >
                    Stats
                  </Button>
                </div>
              </div>
            </div>

            {/* Content Area */}
            {activeTab === 'chat' ? (
              <>
                {/* Messages */}
                <div className="flex-1 overflow-y-auto p-4 space-y-4">
                  {messages.length === 0 ? (
                    <div className="text-center text-muted-foreground py-8">
                      Start a conversation by typing a message below
                    </div>
                  ) : (
                    messages.map((msg: Message) => {
                      const agentName = getAgentName(msg)
                      return (
                        <div
                          key={msg.id}
                          className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                        >
                          <div className={`max-w-[70%] ${msg.role === 'user' ? '' : 'flex flex-col'}`}>
                            {agentName && (
                              <div className="text-xs text-muted-foreground mb-1 px-1">
                                {formatAgentName(agentName)}
                              </div>
                            )}
                            <div
                              className={`rounded-lg p-3 ${
                                msg.role === 'user'
                                  ? 'bg-primary text-primary-foreground'
                                  : 'bg-muted'
                              }`}
                            >
                              <p className="whitespace-pre-wrap">{msg.content}</p>
                              {msg.tokens_used > 0 && (
                                <p className="text-xs opacity-70 mt-2">
                                  {msg.tokens_used} tokens
                                </p>
                              )}
                            </div>
                          </div>
                        </div>
                      )
                    })
                  )}
                  <div ref={messagesEndRef} />
                </div>

                {/* Input */}
                <div className="border-t p-4">
                  {error && (
                    <div className="mb-2 p-2 bg-destructive/10 text-destructive text-sm rounded">
                      {error}
                    </div>
                  )}
                  <form
                    onSubmit={(e: ReactFormEvent) => {
                      e.preventDefault()
                      handleSend()
                    }}
                    className="flex gap-2"
                  >
                    <input
                      type="text"
                      value={input}
                      onChange={(e: ReactChangeEvent) => setInput(e.target.value)}
                      placeholder="Type your message..."
                      className="flex-1 px-4 py-2 border rounded-md"
                      disabled={sending}
                    />
                    <Button type="submit" disabled={sending || !input.trim()}>
                      {sending ? 'Sending...' : 'Send'}
                    </Button>
                  </form>
                </div>
              </>
            ) : (
              /* Stats Tab */
              <div className="flex-1 overflow-y-auto p-6">
                {loadingStats ? (
                  <div className="text-center text-muted-foreground py-8">Loading stats...</div>
                ) : stats ? (
                  <div className="space-y-6">
                    {/* Overview */}
                    <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                      <div className="border rounded-lg p-4">
                        <div className="text-sm text-muted-foreground">Total Messages</div>
                        <div className="text-2xl font-bold mt-1">{stats.total_messages}</div>
                      </div>
                      <div className="border rounded-lg p-4">
                        <div className="text-sm text-muted-foreground">User Messages</div>
                        <div className="text-2xl font-bold mt-1">{stats.user_messages}</div>
                      </div>
                      <div className="border rounded-lg p-4">
                        <div className="text-sm text-muted-foreground">Assistant Messages</div>
                        <div className="text-2xl font-bold mt-1">{stats.assistant_messages}</div>
                      </div>
                      <div className="border rounded-lg p-4">
                        <div className="text-sm text-muted-foreground">Total Tokens</div>
                        <div className="text-2xl font-bold mt-1">{stats.total_tokens.toLocaleString()}</div>
                      </div>
                    </div>

                    {/* Token Breakdown */}
                    <div className="border rounded-lg p-4">
                      <h3 className="font-semibold mb-4">Token Usage</h3>
                      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                        <div>
                          <div className="text-sm text-muted-foreground">Input Tokens</div>
                          <div className="text-xl font-bold mt-1">{(stats.input_tokens || 0).toLocaleString()}</div>
                        </div>
                        <div>
                          <div className="text-sm text-muted-foreground">Output Tokens</div>
                          <div className="text-xl font-bold mt-1">{(stats.output_tokens || 0).toLocaleString()}</div>
                        </div>
                        <div>
                          <div className="text-sm text-muted-foreground">Cached Tokens</div>
                          <div className="text-xl font-bold mt-1">{(stats.cached_tokens || 0).toLocaleString()}</div>
                        </div>
                        <div>
                          <div className="text-sm text-muted-foreground">Total Tokens</div>
                          <div className="text-xl font-bold mt-1">{stats.total_tokens.toLocaleString()}</div>
                        </div>
                      </div>
                    </div>

                    {/* Cost Breakdown */}
                    {stats.cost && (
                      <div className="border rounded-lg p-4">
                        <h3 className="font-semibold mb-4">Cost Breakdown</h3>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                          <div>
                            <div className="text-sm text-muted-foreground">Input Cost</div>
                            <div className="text-xl font-bold mt-1">${(stats.cost.input || 0).toFixed(6)}</div>
                          </div>
                          <div>
                            <div className="text-sm text-muted-foreground">Output Cost</div>
                            <div className="text-xl font-bold mt-1">${(stats.cost.output || 0).toFixed(6)}</div>
                          </div>
                          <div>
                            <div className="text-sm text-muted-foreground">Cached Cost</div>
                            <div className="text-xl font-bold mt-1">${(stats.cost.cached || 0).toFixed(6)}</div>
                          </div>
                          <div>
                            <div className="text-sm text-muted-foreground">Total Cost</div>
                            <div className="text-xl font-bold mt-1 text-primary">${(stats.cost.total || 0).toFixed(6)}</div>
                          </div>
                        </div>
                      </div>
                    )}

                    {/* Agent Usage */}
                    <div className="border rounded-lg p-4">
                      <h3 className="font-semibold mb-4">Agent Usage</h3>
                      {Object.keys(stats.agent_usage).length > 0 ? (
                        <div className="space-y-2">
                          {Object.entries(stats.agent_usage).map(([agent, count]) => (
                            <div key={agent} className="flex items-center justify-between">
                              <span className="capitalize">{agent}</span>
                              <span className="font-medium">{count} messages</span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-muted-foreground text-sm">No agent usage data yet</p>
                      )}
                    </div>

                    {/* Tool Usage */}
                    <div className="border rounded-lg p-4">
                      <h3 className="font-semibold mb-4">Tool Usage</h3>
                      {Object.keys(stats.tool_usage).length > 0 ? (
                        <div className="space-y-2">
                          {Object.entries(stats.tool_usage).map(([tool, count]) => (
                            <div key={tool} className="flex items-center justify-between">
                              <span className="font-mono text-sm">{tool}</span>
                              <span className="font-medium">{count} calls</span>
                            </div>
                          ))}
                        </div>
                      ) : (
                        <p className="text-muted-foreground text-sm">No tools used yet</p>
                      )}
                    </div>

                    {/* Session Info */}
                    <div className="border rounded-lg p-4">
                      <h3 className="font-semibold mb-4">Session Information</h3>
                      <div className="space-y-2 text-sm">
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">Model Used:</span>
                          <span>{stats.model_used || 'Not specified'}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">Created:</span>
                          <span>{new Date(stats.created_at).toLocaleString()}</span>
                        </div>
                        <div className="flex justify-between">
                          <span className="text-muted-foreground">Last Updated:</span>
                          <span>{new Date(stats.updated_at).toLocaleString()}</span>
                        </div>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className="text-center text-muted-foreground py-8">
                    No statistics available
                  </div>
                )}
              </div>
            )}
          </>
        )}
      </div>
    </div>
  )
}
