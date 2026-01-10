import React, { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { useChatStore, type Message } from '@/state/useChatStore'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { createAgentStream, StreamEvent } from '@/lib/streaming'
import { chatAPI, agentAPI } from '@/lib/api'
import { getErrorMessage } from '@/lib/utils'

interface ActivityTimelineItem {
  id: string | null
  trace_id?: string | null
  type: string
  category: 'llm_call' | 'tool_call' | 'event' | 'other'
  name: string
  agent?: string
  tool?: string
  tools?: Array<{ name: string; input?: string | Record<string, unknown> }>
  timestamp: string | null
  latency_ms: number | null
  tokens?: {
    input: number
    output: number
    total: number
  }
  cost?: number
  model?: string
  input_preview?: string
  output_preview?: string
  message?: string
}

interface ActivityChain {
  trace_id: string
  activities: ActivityTimelineItem[]
  total_tokens: number
  total_cost: number
  first_timestamp: string | null
  agents: string[]
}

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
  activity_timeline?: ActivityTimelineItem[]
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
  const [useStreaming, setUseStreaming] = useState(true) // Toggle for streaming vs non-streaming
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [sessionToDelete, setSessionToDelete] = useState<number | null>(null)
  const [deleteAllDialogOpen, setDeleteAllDialogOpen] = useState(false)
  const [expandedActivities, setExpandedActivities] = useState<string[]>([])
  const [expandedChains, setExpandedChains] = useState<string[]>([])
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
    deleteAllSessions,
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
      initialMessageSentRef.current = false
    } else {
      clearCurrentSession()
    }
  }, [sessionId, loadSession, clearCurrentSession])

  const loadChatStats = useCallback(async (sessionId: number) => {
    setLoadingStats(true)
    try {
      const response = await chatAPI.getStats(sessionId)
      setStats(response.data)
    } catch (error: unknown) {
      // Silently fail for new chats with no messages - stats will be available after first message
      if (error && typeof error === 'object' && 'response' in error) {
        const apiError = error as { response?: { status?: number } }
        if (apiError.response?.status !== 404 && apiError.response?.status !== 422) {
          // Error is logged but not shown to user for expected failures
        }
      }
      setStats(null)
    } finally {
      setLoadingStats(false)
    }
  }, [])

  const handleSendWithMessage = useCallback(async (messageContent: string) => {
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

    try {
      const token = localStorage.getItem('access_token')
      if (!token) {
        throw new Error('No authentication token')
      }

      if (useStreaming) {
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
      } else {
        // Use non-streaming (regular API call via agent.runAgent)
        // No placeholder needed - response comes back immediately
        const response = await agentAPI.runAgent({
          chat_session_id: currentSession.id,
          message: content,
        })
        // Reload messages to get both user and assistant messages from backend
        loadMessages(currentSession.id)
        loadChatStats(currentSession.id)
        setSending(false)
      }
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, 'Failed to send message'))
      setSending(false)
    }
  }, [currentSession, sending, useStreaming, loadMessages, loadChatStats])

  // Load stats only after session is loaded and when on stats tab
  useEffect(() => {
    if (currentSession && activeTab === 'stats') {
      loadChatStats(currentSession.id)
    }
  }, [currentSession?.id, activeTab, loadChatStats])

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
  }, [currentSession?.id, messages.length, sending, handleSendWithMessage])

  useEffect(() => {
    messagesEndRef.current?.scrollIntoView({ behavior: 'smooth' })
  }, [messages])

  useEffect(() => {
    // Refresh stats when messages change and we're on stats tab
    if (currentSession && activeTab === 'stats' && messages.length > 0) {
      loadChatStats(currentSession.id)
    }
  }, [messages.length, currentSession?.id, activeTab, loadChatStats])

  const handleNewChat = async () => {
    const newSession = await createSession()
    if (newSession) {
      navigate(`/chat/${newSession.id}`)
    }
  }

  const handleSelectSession = (id: number) => {
    navigate(`/chat/${id}`)
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

  const handleDeleteSession = async (id: number, e: React.MouseEvent) => {
    e.stopPropagation()
    setSessionToDelete(id)
    setDeleteDialogOpen(true)
  }

  const confirmDeleteSession = async () => {
    if (sessionToDelete === null) return
    
    await deleteSession(sessionToDelete)
    if (currentSession?.id === sessionToDelete) {
      navigate('/chat')
    }
    setDeleteDialogOpen(false)
    setSessionToDelete(null)
  }

  const cancelDeleteSession = () => {
    setDeleteDialogOpen(false)
    setSessionToDelete(null)
  }

  const handleDeleteAllSessions = () => {
    setDeleteAllDialogOpen(true)
  }

  const confirmDeleteAllSessions = async () => {
    try {
      await deleteAllSessions()
      navigate('/chat')
      toast.success('All chat sessions deleted successfully')
      setDeleteAllDialogOpen(false)
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, 'Failed to delete all sessions'))
    }
  }

  const cancelDeleteAllSessions = () => {
    setDeleteAllDialogOpen(false)
  }

  const getAgentName = (msg: Message): string => {
    if (msg.role === 'user') return ''
    return msg.metadata?.agent_name || 'assistant'
  }

  const formatAgentName = (name: string): string => {
    return name.charAt(0).toUpperCase() + name.slice(1)
  }

  return (
    <>
    <div className="flex h-[calc(100vh-200px)]">
      {/* Sidebar */}
      <div className="w-64 border-r flex flex-col">
        <div className="p-4 border-b space-y-2">
          <Button onClick={handleNewChat} className="w-full">
            New Chat
          </Button>
          {sessions.length > 0 && (
            <Button 
              onClick={handleDeleteAllSessions} 
              variant="destructive" 
              className="w-full"
            >
              Delete All Chats
            </Button>
          )}
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
                      onClick={(e: React.MouseEvent) => handleDeleteSession(session.id, e)}
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
                  {/* Streaming Toggle */}
                  <div className="mb-2 flex items-center gap-2">
                    <label className="flex items-center gap-2 text-sm cursor-pointer">
                      <input
                        type="checkbox"
                        checked={useStreaming}
                        onChange={(e) => setUseStreaming(e.target.checked)}
                        className="w-4 h-4"
                        disabled={sending}
                      />
                      <span className={useStreaming ? 'text-primary' : 'text-muted-foreground'}>
                        Streaming {useStreaming ? '(ON)' : '(OFF)'}
                      </span>
                    </label>
                  </div>
                  <form
                    onSubmit={(e: React.FormEvent<HTMLFormElement>) => {
                      e.preventDefault()
                      handleSend()
                    }}
                    className="flex gap-2"
                  >
                    <input
                      type="text"
                      value={input}
                      onChange={(e: React.ChangeEvent<HTMLInputElement>) => setInput(e.target.value)}
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

                    {/* Activity Timeline */}
                    <div className="border rounded-lg p-4">
                      <h3 className="font-semibold mb-4">Activity Timeline</h3>
                      {stats.activity_timeline && stats.activity_timeline.length > 0 ? (() => {
                        // Group activities by trace_id (message chains)
                        const chainsMap = new Map<string, ActivityChain>()
                        
                        stats.activity_timeline.forEach((activity, index) => {
                          const traceId = activity.trace_id || `no-trace-${index}`
                          
                          if (!chainsMap.has(traceId)) {
                            chainsMap.set(traceId, {
                              trace_id: traceId,
                              activities: [],
                              total_tokens: 0,
                              total_cost: 0,
                              first_timestamp: activity.timestamp,
                              agents: []
                            })
                          }
                          
                          const chain = chainsMap.get(traceId)!
                          chain.activities.push(activity)
                          
                          if (activity.tokens) {
                            chain.total_tokens += activity.tokens.total
                          }
                          if (activity.cost) {
                            chain.total_cost += activity.cost
                          }
                          if (activity.agent && !chain.agents.includes(activity.agent)) {
                            chain.agents.push(activity.agent)
                          }
                          if (activity.timestamp && (!chain.first_timestamp || activity.timestamp < chain.first_timestamp)) {
                            chain.first_timestamp = activity.timestamp
                          }
                        })
                        
                        const chains = Array.from(chainsMap.values()).sort((a, b) => {
                          if (!a.first_timestamp || !b.first_timestamp) return 0
                          return a.first_timestamp.localeCompare(b.first_timestamp)
                        })
                        
                        return (
                          <div className="space-y-4">
                            {chains.map((chain) => {
                              // Expand chains by default (if not explicitly collapsed)
                              // If expandedChains is empty, all chains are expanded by default
                              // If a chain ID is in expandedChains, it means user clicked to collapse it
                              const isChainExpanded = !expandedChains.includes(chain.trace_id)
                              
                              return (
                                <div key={chain.trace_id} className="border rounded-lg p-3 bg-muted/20">
                                  {/* Chain Header - Collapsible */}
                                  <div 
                                    className="flex items-start justify-between cursor-pointer hover:bg-muted/50 rounded p-2 -m-2"
                                    onClick={() => {
                                      setExpandedChains((prev: string[]) => 
                                        prev.includes(chain.trace_id) 
                                          ? prev.filter(id => id !== chain.trace_id) // Remove from collapsed list (expand it)
                                          : [...prev, chain.trace_id] // Add to collapsed list
                                      )
                                    }}
                                  >
                                    <div className="flex-1">
                                      <div className="flex items-center gap-2">
                                        <svg
                                          className={`w-4 h-4 text-muted-foreground transition-transform ${isChainExpanded ? 'rotate-90' : ''}`}
                                          fill="none"
                                          stroke="currentColor"
                                          viewBox="0 0 24 24"
                                        >
                                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                                        </svg>
                                        <span className="font-semibold">Message Chain</span>
                                        {chain.agents.length > 0 && (
                                          <div className="flex gap-1">
                                            {chain.agents.map(agent => (
                                              <span key={agent} className="text-xs px-2 py-0.5 rounded bg-primary/10 text-primary">
                                                {agent}
                                              </span>
                                            ))}
                                          </div>
                                        )}
                                        <span className="text-xs text-muted-foreground">
                                          {chain.activities.length} {chain.activities.length === 1 ? 'activity' : 'activities'}
                                        </span>
                                      </div>
                                      {chain.first_timestamp && (
                                        <div className="text-xs text-muted-foreground mt-1 ml-6">
                                          {new Date(chain.first_timestamp).toLocaleString()}
                                        </div>
                                      )}
                                    </div>
                                    
                                    {/* Chain Summary */}
                                    <div className="text-right text-sm">
                                      <div className="text-muted-foreground">
                                        {chain.total_tokens || 0} tokens
                                      </div>
                                      {(chain.total_cost || 0) > 0 && (
                                        <div className="text-muted-foreground">
                                          ${chain.total_cost.toFixed(6)}
                                        </div>
                                      )}
                                    </div>
                                  </div>

                                  {/* Chain Activities - Collapsible */}
                                  {isChainExpanded && (
                                    <div className="mt-3 space-y-3 pl-6 border-l-2 border-muted">
                                      {chain.activities.map((activity, activityIndex) => {
                                        const activityKey = `${chain.trace_id}-${activity.id || String(activityIndex)}`
                                        const isExpanded = expandedActivities.includes(activityKey)
                                        const hasDetails = !!(activity.model || activity.tools?.length || activity.input_preview || activity.output_preview || activity.message)
                                        
                                        return (
                                          <div key={activity.id || activityIndex} className="relative">
                                            {/* Timeline dot */}
                                            <div className="absolute -left-3 top-0 w-3 h-3 rounded-full bg-primary/70 border-2 border-background"></div>
                                            
                                            <div className="space-y-2">
                                              {/* Activity Header - Clickable if has details */}
                                              <div 
                                                className={`flex items-start justify-between ${hasDetails ? 'cursor-pointer hover:bg-muted/50 rounded p-2 -m-2' : ''}`}
                                                onClick={() => {
                                                  if (hasDetails) {
                                                    setExpandedActivities((prev: string[]) => 
                                                      prev.includes(activityKey) 
                                                        ? prev.filter(key => key !== activityKey)
                                                        : [...prev, activityKey]
                                                    )
                                                  }
                                                }}
                                              >
                                                <div className="flex-1">
                                                  <div className="flex items-center gap-2">
                                                    {hasDetails && (
                                                      <svg
                                                        className={`w-4 h-4 text-muted-foreground transition-transform ${isExpanded ? 'rotate-90' : ''}`}
                                                        fill="none"
                                                        stroke="currentColor"
                                                        viewBox="0 0 24 24"
                                                      >
                                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                                                      </svg>
                                                    )}
                                                    <span className="font-medium text-sm">{activity.name}</span>
                                                    {activity.agent && (
                                                      <span className="text-xs px-2 py-0.5 rounded bg-primary/10 text-primary">
                                                        {activity.agent}
                                                      </span>
                                                    )}
                                                    {activity.tool && (
                                                      <span className="text-xs px-2 py-0.5 rounded bg-secondary text-secondary-foreground">
                                                        {activity.tool}
                                                      </span>
                                                    )}
                                                    <span className="text-xs text-muted-foreground capitalize">
                                                      {activity.category.replace('_', ' ')}
                                                    </span>
                                                  </div>
                                                  {activity.timestamp && (
                                                    <div className="text-xs text-muted-foreground mt-1 ml-6">
                                                      {new Date(activity.timestamp).toLocaleString()}
                                                      {activity.latency_ms && (
                                                        <span className="ml-2">• {activity.latency_ms.toFixed(0)}ms</span>
                                                      )}
                                                    </div>
                                                  )}
                                                </div>
                                                
                                                {/* Tokens and Cost */}
                                                <div className="text-right text-sm">
                                                  {activity.tokens && (
                                                    <div className="text-muted-foreground">
                                                      {activity.tokens.total} tokens
                                                    </div>
                                                  )}
                                                  {activity.cost && (
                                                    <div className="text-muted-foreground">
                                                      ${activity.cost.toFixed(6)}
                                                    </div>
                                                  )}
                                                </div>
                                              </div>

                                              {/* Collapsible Details */}
                                              {isExpanded && hasDetails && (
                                                <div className="mt-2 space-y-2 pl-6">
                                                  {/* Model info */}
                                                  {activity.model && (
                                                    <div className="text-xs text-muted-foreground">
                                                      Model: {activity.model}
                                                    </div>
                                                  )}

                                                  {/* Tool calls */}
                                                  {activity.tools && activity.tools.length > 0 && (
                                                    <div className="mt-2 space-y-1">
                                                      {activity.tools.map((tool, toolIndex) => (
                                                        <div key={toolIndex} className="text-sm bg-muted/50 p-2 rounded">
                                                          <span className="font-mono text-xs">{tool.name}</span>
                                                          {tool.input && (
                                                            <div className="text-xs text-muted-foreground mt-1 break-words">
                                                              {typeof tool.input === 'string' ? tool.input : JSON.stringify(tool.input).substring(0, 200)}
                                                            </div>
                                                          )}
                                                        </div>
                                                      ))}
                                                    </div>
                                                  )}

                                                  {/* Input/Output previews */}
                                                  {(activity.input_preview || activity.output_preview) && (
                                                    <div className="mt-2 space-y-1 text-sm">
                                                      {activity.input_preview && (
                                                        <div className="bg-muted/30 p-2 rounded">
                                                          <div className="text-xs text-muted-foreground mb-1">Input:</div>
                                                          <div className="text-xs font-mono break-words">{activity.input_preview}</div>
                                                        </div>
                                                      )}
                                                      {activity.output_preview && (
                                                        <div className="bg-muted/30 p-2 rounded">
                                                          <div className="text-xs text-muted-foreground mb-1">Output:</div>
                                                          <div className="text-xs font-mono break-words">{activity.output_preview}</div>
                                                        </div>
                                                      )}
                                                    </div>
                                                  )}

                                                  {/* Event message */}
                                                  {activity.message && (
                                                    <div className="text-sm text-muted-foreground italic">
                                                      {activity.message}
                                                    </div>
                                                  )}
                                                </div>
                                              )}
                                            </div>
                                          </div>
                                        )
                                      })}
                                    </div>
                                  )}
                                </div>
                              )
                            })}
                          </div>
                        )
                      })() : (
                        <div className="text-center text-muted-foreground py-8">
                          No activity timeline data available
                        </div>
                      )}
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

    {/* Delete Confirmation Dialog */}
    {deleteDialogOpen && (
      <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={cancelDeleteSession}>
        <div className="bg-background border rounded-lg p-6 max-w-md w-full mx-4 shadow-lg" onClick={(e) => e.stopPropagation()}>
          <h3 className="text-lg font-semibold mb-2">Delete Chat Session</h3>
          <p className="text-muted-foreground mb-6">
            Are you sure you want to delete this chat session? This action cannot be undone.
          </p>
          <div className="flex justify-end gap-3">
            <Button variant="outline" onClick={cancelDeleteSession}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={confirmDeleteSession}>
              Delete
            </Button>
          </div>
        </div>
      </div>
    )}

    {/* Delete All Confirmation Dialog */}
    {deleteAllDialogOpen && (
      <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={cancelDeleteAllSessions}>
        <div className="bg-background border rounded-lg p-6 max-w-md w-full mx-4 shadow-lg" onClick={(e) => e.stopPropagation()}>
          <h3 className="text-lg font-semibold mb-2">Delete All Chat Sessions</h3>
          <p className="text-muted-foreground mb-6">
            Are you sure you want to delete all {sessions.length} chat session{sessions.length !== 1 ? 's' : ''}? This action cannot be undone.
          </p>
          <div className="flex justify-end gap-3">
            <Button variant="outline" onClick={cancelDeleteAllSessions}>
              Cancel
            </Button>
            <Button variant="destructive" onClick={confirmDeleteAllSessions}>
              Delete All
            </Button>
          </div>
        </div>
      </div>
    )}
    </>
  )
}
