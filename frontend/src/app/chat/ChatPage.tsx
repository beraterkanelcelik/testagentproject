import React, { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { useChatStore, type Message } from '@/state/useChatStore'
import { useAuthStore } from '@/state/useAuthStore'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { createAgentStream, StreamEvent } from '@/lib/streaming'
import { chatAPI, agentAPI, documentAPI } from '@/lib/api'
import { getErrorMessage } from '@/lib/utils'


export default function ChatPage() {
  const { sessionId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()
  const messagesEndRef = useRef<HTMLDivElement>(null)
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [useStreaming, setUseStreaming] = useState(true) // Toggle for streaming vs non-streaming
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [sessionToDelete, setSessionToDelete] = useState<number | null>(null)
  const [deleteAllDialogOpen, setDeleteAllDialogOpen] = useState(false)
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [moreMenuOpen, setMoreMenuOpen] = useState(false)
  const [attachedFiles, setAttachedFiles] = useState<File[]>([])
  const [waitingForResponse, setWaitingForResponse] = useState(false)
  const [waitingMessageId, setWaitingMessageId] = useState<number | null>(null)
  const [statsDialogOpen, setStatsDialogOpen] = useState(false)
  const [stats, setStats] = useState<any>(null)
  const [loadingStats, setLoadingStats] = useState(false)
  const [expandedActivities, setExpandedActivities] = useState<string[]>([])
  const [expandedChains, setExpandedChains] = useState<string[]>([])
  const fileInputRef = useRef<HTMLInputElement>(null)
  const streamRef = useRef<ReturnType<typeof createAgentStream> | null>(null)
  const initialMessageSentRef = useRef(false)
  const initialMessageRef = useRef<string | null>(null)

  const { user } = useAuthStore()
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
    // Load sessions list on mount, but don't reload if already loaded
    if (sessions.length === 0) {
      loadSessions()
    }
  }, []) // Only run once on mount

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
      const sessionIdNum = Number(sessionId)
      // Only load session if it's not already loaded or if it's a different session
      if (!currentSession || currentSession.id !== sessionIdNum) {
        loadSession(sessionIdNum)
      } else {
        // Session is already loaded, but ensure messages are loaded
        loadMessages(sessionIdNum)
      }
      initialMessageSentRef.current = false
    } else {
      clearCurrentSession()
    }
  }, [sessionId, loadSession, loadMessages, clearCurrentSession, currentSession])


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
        setWaitingForResponse(true)
        setWaitingMessageId(assistantMessageId)
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
              // First token received, hide loading indicator
              setWaitingForResponse(false)
              setWaitingMessageId(null)
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
              setWaitingForResponse(false)
              setWaitingMessageId(null)
            }
          },
          (error: Error) => {
            toast.error(error.message || 'Streaming connection error')
            setSending(false)
            setWaitingForResponse(false)
            setWaitingMessageId(null)
          },
          () => {
            // Stream complete, reload messages to get final saved version
            loadMessages(currentSession.id)
            setSending(false)
            setWaitingForResponse(false)
            setWaitingMessageId(null)
          }
        )

        streamRef.current = stream
      } else {
        // Use non-streaming (regular API call via agent.runAgent)
        setWaitingForResponse(true)
        setWaitingMessageId(null)
        try {
          const response = await agentAPI.runAgent({
            chat_session_id: currentSession.id,
            message: content,
          })
          // Reload messages to get both user and assistant messages from backend
          loadMessages(currentSession.id)
        } finally {
          setSending(false)
          setWaitingForResponse(false)
          setWaitingMessageId(null)
        }
      }
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, 'Failed to send message'))
      setSending(false)
    }
  }, [currentSession, sending, useStreaming, loadMessages])

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


  const handleNewChat = async () => {
    const newSession = await createSession()
    if (newSession) {
      navigate(`/chat/${newSession.id}`)
    }
  }

  const handleSelectSession = (id: number) => {
    navigate(`/chat/${id}`)
    // Keep sidebar open on mobile/tablet, close on desktop for better UX
    if (window.innerWidth >= 768) {
      setSidebarOpen(false)
    }
  }

  const handleSend = async () => {
    if (!input.trim() && attachedFiles.length === 0) return
    const content = input.trim()
    setInput('')
    setAttachedFiles([]) // Clear attached files after sending
    if (content) {
      await handleSendWithMessage(content)
    }
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

  const loadChatStats = useCallback(async (sessionId: number) => {
    setLoadingStats(true)
    try {
      const response = await chatAPI.getStats(sessionId)
      setStats(response.data)
    } catch (error: unknown) {
      if (error && typeof error === 'object' && 'response' in error) {
        const apiError = error as { response?: { status?: number } }
        if (apiError.response?.status !== 404 && apiError.response?.status !== 422) {
          toast.error('Failed to load statistics')
        }
      }
      setStats(null)
    } finally {
      setLoadingStats(false)
    }
  }, [])

  const handleOpenStats = () => {
    setMoreMenuOpen(false)
    if (currentSession) {
      setStatsDialogOpen(true)
      loadChatStats(currentSession.id)
    }
  }

  const handleFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || [])
    if (files.length === 0) return

    // Add files to attached files list
    setAttachedFiles((prev) => [...prev, ...files])

    // Upload files
    for (const file of files) {
      try {
        await documentAPI.uploadDocument(file)
        toast.success(`File "${file.name}" uploaded successfully`)
      } catch (error: unknown) {
        toast.error(getErrorMessage(error, `Failed to upload ${file.name}`))
      }
    }

    // Reset file input
    if (fileInputRef.current) {
      fileInputRef.current.value = ''
    }
  }

  const handleRemoveFile = (index: number) => {
    setAttachedFiles((prev) => prev.filter((_, i) => i !== index))
  }

  return (
    <>
    <div className="flex h-[calc(100vh-145px)] bg-background">
      {/* Collapsible Sidebar */}
      <div className={`${sidebarOpen ? 'w-64' : 'w-0'} transition-all duration-300 overflow-hidden border-r flex flex-col bg-background`}>
        <div className="p-4 border-b space-y-2 min-w-[256px]">
          <Button onClick={handleNewChat} className="w-full">
            New Chat
          </Button>
          {sessions.length > 0 && (
            <Button 
              onClick={handleDeleteAllSessions} 
              variant="destructive" 
              className="w-full"
            >
              Delete All
            </Button>
          )}
        </div>
        <div className="flex-1 overflow-y-auto min-w-[256px]">
          {loading && sessions.length === 0 ? (
            <div className="p-4 text-center text-muted-foreground text-sm">Loading...</div>
          ) : sessions.length === 0 ? (
            <div className="p-4 text-center text-muted-foreground text-sm">
              No chats yet
            </div>
          ) : (
            <div className="divide-y">
              {sessions.map((session: { id: number; title: string; updated_at: string }) => (
                <div
                  key={session.id}
                  onClick={() => {
                    handleSelectSession(session.id)
                  }}
                  className={`p-3 cursor-pointer hover:bg-muted/50 transition-colors ${
                    currentSession?.id === session.id ? 'bg-muted/50' : ''
                  }`}
                >
                  <div className="flex items-start justify-between group">
                    <div className="flex-1 min-w-0">
                      <p className="font-medium text-sm truncate">
                        {session.title || 'Untitled Chat'}
                      </p>
                      <p className="text-xs text-muted-foreground mt-0.5">
                        {new Date(session.updated_at).toLocaleDateString()}
                      </p>
                    </div>
                    <button
                      onClick={(e: React.MouseEvent) => handleDeleteSession(session.id, e)}
                      className="ml-2 text-muted-foreground hover:text-destructive opacity-0 group-hover:opacity-100 transition-opacity text-lg leading-none"
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

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {!currentSession ? (
          <div className="flex-1 flex items-center justify-center">
            <div className="text-center max-w-md">
              <h2 className="text-2xl font-semibold mb-2">Start a new conversation</h2>
              <p className="text-muted-foreground mb-6">
                Create a new chat to begin talking with AI agents
              </p>
              <Button onClick={handleNewChat} size="lg">New Chat</Button>
            </div>
          </div>
        ) : (
          <>
            {/* Minimal Header */}
            <div className="border-b px-4 py-3 flex items-center justify-between bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
              <div className="flex items-center gap-3">
                <button
                  onClick={() => setSidebarOpen(!sidebarOpen)}
                  className="p-1.5 hover:bg-muted rounded-md transition-colors"
                  aria-label="Toggle sidebar"
                >
                  <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                  </svg>
                </button>
                <h2 className="font-medium text-sm truncate">
                  {currentSession.title || 'Untitled Chat'}
                </h2>
              </div>
            </div>

            {/* Messages Area */}
            <div className="flex-1 overflow-y-auto">
              <div className="max-w-3xl mx-auto px-4 py-8">
                {messages.length === 0 ? (
                  <div className="flex items-center justify-center h-full">
                    <div className="text-center">
                      <p className="text-muted-foreground text-sm">
                        Start a conversation by typing a message below
                      </p>
                    </div>
                  </div>
                ) : (
                  <div className="space-y-6">
                    {messages.map((msg: Message) => {
                      const agentName = getAgentName(msg)
                      // Show loading indicator for streaming mode when message exists but has no content yet
                      const isWaiting = useStreaming && waitingForResponse && msg.id === waitingMessageId && !msg.content
                      return (
                        <div
                          key={msg.id}
                          className={`flex gap-3 items-start ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}
                        >
                          {msg.role === 'assistant' && (
                            <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0 mt-1">
                              <svg className="w-5 h-5 text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                              </svg>
                            </div>
                          )}
                          <div className="flex flex-col max-w-[85%]">
                            {msg.role === 'assistant' && agentName && (
                              <div className="text-xs text-muted-foreground mb-1.5 px-1">
                                {formatAgentName(agentName)}
                              </div>
                            )}
                            <div
                              className={`rounded-2xl px-4 py-3 inline-block ${
                                msg.role === 'user'
                                  ? 'bg-primary text-primary-foreground'
                                  : 'bg-muted'
                              }`}
                            >
                              {isWaiting ? (
                                <div className="flex items-center gap-1.5 py-1">
                                  <span 
                                    className="w-2 h-2 bg-muted-foreground rounded-full" 
                                    style={{ 
                                      animation: 'breathe 1.4s ease-in-out infinite',
                                      animationDelay: '0ms'
                                    }}
                                  ></span>
                                  <span 
                                    className="w-2 h-2 bg-muted-foreground rounded-full" 
                                    style={{ 
                                      animation: 'breathe 1.4s ease-in-out infinite',
                                      animationDelay: '200ms'
                                    }}
                                  ></span>
                                  <span 
                                    className="w-2 h-2 bg-muted-foreground rounded-full" 
                                    style={{ 
                                      animation: 'breathe 1.4s ease-in-out infinite',
                                      animationDelay: '400ms'
                                    }}
                                  ></span>
                                </div>
                              ) : (
                                <p className="text-[15px] leading-relaxed whitespace-pre-wrap break-words">
                                  {msg.content}
                                </p>
                              )}
                            </div>
                          </div>
                          {msg.role === 'user' && (
                            <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center flex-shrink-0 mt-1">
                              <span className="text-primary-foreground text-sm font-medium">
                                {user?.email?.[0]?.toUpperCase() || 'U'}
                              </span>
                            </div>
                          )}
                        </div>
                      )
                    })}
                    {/* Show loading indicator for non-streaming mode when waiting */}
                    {waitingForResponse && !useStreaming && (
                      <div className="flex gap-3 items-start justify-start">
                        <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0 mt-1">
                          <svg className="w-5 h-5 text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
                          </svg>
                        </div>
                        <div className="flex flex-col max-w-[85%]">
                          <div className="rounded-2xl px-4 py-3 inline-block bg-muted">
                            <div className="flex items-center gap-1.5 py-1">
                              <span 
                                className="w-2 h-2 bg-muted-foreground rounded-full" 
                                style={{ 
                                  animation: 'breathe 1.4s ease-in-out infinite',
                                  animationDelay: '0ms'
                                }}
                              ></span>
                              <span 
                                className="w-2 h-2 bg-muted-foreground rounded-full" 
                                style={{ 
                                  animation: 'breathe 1.4s ease-in-out infinite',
                                  animationDelay: '200ms'
                                }}
                              ></span>
                              <span 
                                className="w-2 h-2 bg-muted-foreground rounded-full" 
                                style={{ 
                                  animation: 'breathe 1.4s ease-in-out infinite',
                                  animationDelay: '400ms'
                                }}
                              ></span>
                            </div>
                          </div>
                        </div>
                      </div>
                    )}
                    <div ref={messagesEndRef} />
                  </div>
                )}
              </div>
            </div>

            {/* Input Area */}
            <div className="border-t bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
              <div className="max-w-3xl mx-auto px-4 py-4">
                {error && (
                  <div className="mb-3 p-3 bg-destructive/10 text-destructive text-sm rounded-lg">
                    {error}
                  </div>
                )}
                
                {/* Attached Files */}
                {attachedFiles.length > 0 && (
                  <div className="mb-3 flex flex-wrap gap-2">
                    {attachedFiles.map((file, index) => (
                      <div
                        key={index}
                        className="flex items-center gap-2 px-3 py-1.5 bg-muted rounded-lg text-sm"
                      >
                        <svg className="w-4 h-4 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                        </svg>
                        <span className="text-xs truncate max-w-[150px]">{file.name}</span>
                        <button
                          type="button"
                          onClick={() => handleRemoveFile(index)}
                          className="text-muted-foreground hover:text-foreground"
                          aria-label="Remove file"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                          </svg>
                        </button>
                      </div>
                    ))}
                  </div>
                )}

                <form
                  onSubmit={(e: React.FormEvent<HTMLFormElement>) => {
                    e.preventDefault()
                    handleSend()
                  }}
                  className="relative"
                >
                  <div className="relative flex items-end gap-2">
                    {/* File Attachment Button */}
                    <button
                      type="button"
                      onClick={() => fileInputRef.current?.click()}
                      className="p-2.5 hover:bg-muted rounded-lg transition-colors flex-shrink-0"
                      aria-label="Attach file"
                      disabled={sending}
                    >
                      <svg className="w-5 h-5 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                      </svg>
                    </button>
                    <input
                      ref={fileInputRef}
                      type="file"
                      multiple
                      onChange={handleFileSelect}
                      className="hidden"
                      disabled={sending}
                    />

                    <textarea
                      value={input}
                      onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => {
                        setInput(e.target.value)
                        // Auto-resize textarea
                        e.target.style.height = 'auto'
                        e.target.style.height = `${Math.min(e.target.scrollHeight, 200)}px`
                      }}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                          e.preventDefault()
                          handleSend()
                        }
                      }}
                      placeholder="Message..."
                      className="flex-1 min-h-[52px] max-h-[200px] px-4 py-3 pr-24 border rounded-2xl resize-none focus:outline-none focus:ring-2 focus:ring-primary/20 bg-background"
                      disabled={sending}
                      rows={1}
                    />
                    
                    {/* More Menu Button */}
                    <div className="relative flex-shrink-0">
                      <button
                        type="button"
                        onClick={() => setMoreMenuOpen(!moreMenuOpen)}
                        className="p-2.5 hover:bg-muted rounded-lg transition-colors"
                        aria-label="More options"
                        disabled={sending}
                      >
                        <svg className="w-5 h-5 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z" />
                        </svg>
                      </button>
                      
                      {/* More Menu Dropdown */}
                      {moreMenuOpen && (
                        <>
                          <div
                            className="fixed inset-0 z-10"
                            onClick={() => setMoreMenuOpen(false)}
                          />
                          <div className="absolute bottom-full right-0 mb-2 w-56 bg-background border rounded-lg shadow-lg p-2 z-20">
                            <button
                              type="button"
                              onClick={handleOpenStats}
                              className="w-full flex items-center gap-2 px-3 py-2 hover:bg-muted rounded-md text-sm text-left"
                            >
                              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                              </svg>
                              <span>Statistics</span>
                            </button>
                            <div className="flex items-center justify-between px-3 py-2 hover:bg-muted rounded-md cursor-pointer">
                              <span className="text-sm">Streaming</span>
                              <button
                                type="button"
                                onClick={() => !sending && setUseStreaming(!useStreaming)}
                                disabled={sending}
                                className={`
                                  relative inline-flex h-5 w-9 items-center rounded-full transition-colors
                                  focus:outline-none focus:ring-2 focus:ring-primary focus:ring-offset-2
                                  ${useStreaming ? 'bg-primary' : 'bg-muted'}
                                  ${sending ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}
                                `}
                                role="switch"
                                aria-checked={useStreaming}
                              >
                                <span
                                  className={`
                                    inline-block h-3.5 w-3.5 transform rounded-full bg-white transition-transform
                                    ${useStreaming ? 'translate-x-5' : 'translate-x-0.5'}
                                  `}
                                />
                              </button>
                            </div>
                          </div>
                        </>
                      )}
                    </div>

                    {/* Send Button */}
                    <button
                      type="submit"
                      disabled={sending || (!input.trim() && attachedFiles.length === 0)}
                      className="p-2.5 rounded-lg bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 disabled:cursor-not-allowed transition-colors flex-shrink-0"
                      aria-label="Send message"
                    >
                      {sending ? (
                        <svg className="w-5 h-5 animate-spin" fill="none" viewBox="0 0 24 24">
                          <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"></circle>
                          <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4zm2 5.291A7.962 7.962 0 014 12H0c0 3.042 1.135 5.824 3 7.938l3-2.647z"></path>
                        </svg>
                      ) : (
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                        </svg>
                      )}
                    </button>
                  </div>
                </form>
              </div>
            </div>
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

    {/* Stats Dialog */}
    {statsDialogOpen && (
      <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50" onClick={() => setStatsDialogOpen(false)}>
        <div className="bg-background border rounded-lg p-6 max-w-4xl w-full mx-4 shadow-lg max-h-[90vh] overflow-y-auto" onClick={(e) => e.stopPropagation()}>
          <div className="flex items-center justify-between mb-4">
            <h3 className="text-lg font-semibold">Chat Statistics</h3>
            <button
              onClick={() => setStatsDialogOpen(false)}
              className="text-muted-foreground hover:text-foreground"
              aria-label="Close"
            >
              <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
          
          {loadingStats ? (
            <div className="text-center text-muted-foreground py-8">Loading statistics...</div>
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
                  <div className="text-2xl font-bold mt-1">{stats.total_tokens?.toLocaleString() || 0}</div>
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
                    <div className="text-xl font-bold mt-1">{stats.total_tokens?.toLocaleString() || 0}</div>
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
              {stats.agent_usage && Object.keys(stats.agent_usage).length > 0 && (
                <div className="border rounded-lg p-4">
                  <h3 className="font-semibold mb-4">Agent Usage</h3>
                  <div className="space-y-2">
                    {Object.entries(stats.agent_usage).map(([agent, count]) => (
                      <div key={agent} className="flex items-center justify-between">
                        <span className="capitalize">{agent}</span>
                        <span className="font-medium">{count as number} messages</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

              {/* Tool Usage */}
              {stats.tool_usage && Object.keys(stats.tool_usage).length > 0 && (
                <div className="border rounded-lg p-4">
                  <h3 className="font-semibold mb-4">Tool Usage</h3>
                  <div className="space-y-2">
                    {Object.entries(stats.tool_usage).map(([tool, count]) => (
                      <div key={tool} className="flex items-center justify-between">
                        <span className="font-mono text-sm">{tool}</span>
                        <span className="font-medium">{count as number} calls</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}

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
              {stats.activity_timeline && stats.activity_timeline.length > 0 && (
                <div className="border rounded-lg p-4">
                  <h3 className="font-semibold mb-4">Activity Timeline</h3>
                  {(() => {
                    // Group activities by trace_id (message chains)
                    const chainsMap = new Map<string, any>()
                    
                    stats.activity_timeline.forEach((activity: any, index: number) => {
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
                        chain.total_tokens += activity.tokens.total || 0
                      }
                      if (activity.cost) {
                        chain.total_cost += activity.cost || 0
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
                          const isChainExpanded = !expandedChains.includes(chain.trace_id)
                          
                          return (
                            <div key={chain.trace_id} className="border rounded-lg p-3 bg-muted/20">
                              {/* Chain Header - Collapsible */}
                              <div 
                                className="flex items-start justify-between cursor-pointer hover:bg-muted/50 rounded p-2 -m-2"
                                onClick={() => {
                                  setExpandedChains((prev: string[]) => 
                                    prev.includes(chain.trace_id) 
                                      ? prev.filter(id => id !== chain.trace_id)
                                      : [...prev, chain.trace_id]
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
                                    <span className="font-semibold text-sm">Message Chain</span>
                                    {chain.agents.length > 0 && (
                                      <div className="flex gap-1">
                                        {chain.agents.map((agent: string) => (
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
                                  {chain.activities.map((activity: any, activityIndex: number) => {
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
                                                  {activity.category?.replace('_', ' ') || 'other'}
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
                                                  {activity.tokens.total || 0} tokens
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
                                                  {activity.tools.map((tool: any, toolIndex: number) => (
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
                  })()}
                </div>
              )}
            </div>
          ) : (
            <div className="text-center text-muted-foreground py-8">
              No statistics available
            </div>
          )}
        </div>
      </div>
    )}
    </>
  )
}
