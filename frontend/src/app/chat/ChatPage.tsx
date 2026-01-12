import React, { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { useChatStore, type Message } from '@/state/useChatStore'
import { useAuthStore } from '@/state/useAuthStore'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { createAgentStream, StreamEvent } from '@/lib/streaming'
import { chatAPI, agentAPI, documentAPI, modelsAPI } from '@/lib/api'
import { getErrorMessage } from '@/lib/utils'
import MarkdownMessage from '@/components/MarkdownMessage'
import JsonViewer from '@/components/JsonViewer'
import PlanProposal, { type PlanProposalData } from '@/components/PlanProposal'


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
  const [plusMenuOpen, setPlusMenuOpen] = useState(false)
  const [selectedOptions, setSelectedOptions] = useState<Array<{type: string, label: string, icon?: React.ReactNode, data?: any}>>([])
  const [inputFocused, setInputFocused] = useState(false)
  const [attachedFiles, setAttachedFiles] = useState<File[]>([])
  const [waitingForResponse, setWaitingForResponse] = useState(false)
  const [waitingMessageId, setWaitingMessageId] = useState<number | null>(null)
  const [streamComplete, setStreamComplete] = useState<Set<number>>(new Set()) // Track which messages have completed streaming
  const [statsDialogOpen, setStatsDialogOpen] = useState(false)
  const [stats, setStats] = useState<any>(null)
  const [loadingStats, setLoadingStats] = useState(false)
  const [expandedActivities, setExpandedActivities] = useState<string[]>([])
  const [expandedChains, setExpandedChains] = useState<string[]>([])
  const [expandedToolCalls, setExpandedToolCalls] = useState<Set<string>>(new Set())
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false)
  const [selectedModel, setSelectedModel] = useState<string>('gpt-4o-mini')
  const [availableModels, setAvailableModels] = useState<Array<{id: string, name: string, description: string}>>([])
  const [headerMoreMenuOpen, setHeaderMoreMenuOpen] = useState(false)
  const [chatsSectionOpen, setChatsSectionOpen] = useState(true)
  const [sessionMenuOpen, setSessionMenuOpen] = useState<number | null>(null)
  const [renameSessionId, setRenameSessionId] = useState<number | null>(null)
  const [renameSessionTitle, setRenameSessionTitle] = useState<string>('')
  const [executingPlanMessageId, setExecutingPlanMessageId] = useState<number | null>(null)
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
    
    // Load available models from backend
    const loadModels = async () => {
      try {
        const response = await modelsAPI.getAvailableModels()
        setAvailableModels(response.data.models || [])
        // Set default model if none selected
        if (response.data.models && response.data.models.length > 0 && !selectedModel) {
          setSelectedModel(response.data.models[0].id)
        }
      } catch (error: unknown) {
        toast.error(getErrorMessage(error, 'Failed to load models'))
      }
    }
    loadModels()
  }, [loadSessions, selectedModel]) // Only run once on mount

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
      // Clear stream complete flags when clearing session
      setStreamComplete(new Set())
    }
  }, [sessionId, loadSession, loadMessages, clearCurrentSession, currentSession])
  
  // Mark all loaded messages from database as stream complete (they're already finished)
  // Only run when session changes to avoid unnecessary updates
  useEffect(() => {
    if (currentSession && messages.length > 0) {
      setStreamComplete(prev => {
        const newSet = new Set(prev)
        messages.forEach(msg => {
          // Mark assistant messages from DB (positive IDs) as stream complete
          // Temporary messages (negative IDs) are still streaming
          if (msg.role === 'assistant' && msg.id > 0 && msg.id < 1000000000000) {
            newSet.add(msg.id)
          }
        })
        return newSet
      })
    }
  }, [currentSession?.id]) // Only run when session changes

  // Sync selected model with session model
  useEffect(() => {
    if (currentSession?.model_used) {
      setSelectedModel(currentSession.model_used)
    } else {
      setSelectedModel('gpt-4o-mini') // Default
    }
  }, [currentSession?.model_used])

  const handleModelChange = async (modelId: string) => {
    if (!currentSession || modelId === selectedModel) return
    
    try {
      await chatAPI.updateSessionModel(currentSession.id, modelId)
      setSelectedModel(modelId)
      // Update currentSession in store
      if (currentSession) {
        const updatedSession = { ...currentSession, model_used: modelId }
        set({ currentSession: updatedSession })
      }
      setModelDropdownOpen(false)
      toast.success(`Model changed to ${availableModels.find(m => m.id === modelId)?.name || modelId}`)
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, 'Failed to update model'))
    }
  }

  const handleSendWithMessage = useCallback(async (messageContent: string) => {
    if (!messageContent.trim() || sending || !currentSession) return

    const content = messageContent.trim()
    setSending(true)

    // Add user message immediately
    const tempUserMessageId = Date.now()
    const userMessage = {
      id: tempUserMessageId,
      role: 'user' as const,
      content,
      tokens_used: 0,
      created_at: new Date().toISOString(),
    }
    console.log(`[FRONTEND] Created temporary user message temp_id=${tempUserMessageId} session=${currentSession.id} content_preview=${content.substring(0, 50)}...`)
    set((state: { messages: Message[] }) => ({
      messages: [...state.messages, userMessage],
    }))

    try {
      const token = localStorage.getItem('access_token')
      if (!token) {
        throw new Error('No authentication token')
      }

      if (useStreaming) {
        // Clear any old temporary status messages before starting a new stream
        // They are ephemeral and should not persist across different streams
        set((state: { messages: Message[] }) => ({
          messages: state.messages.filter(
            (msg: Message) => !(msg.id < 0 && msg.role === 'system' && msg.metadata?.status_type === 'task_status')
          )
        }))
        
        // Create streaming message placeholder
        const assistantMessageId = Date.now() + 1
        console.log(`[FRONTEND] Created temporary assistant message temp_id=${assistantMessageId} session=${currentSession.id}`)
        setWaitingForResponse(true)
        setWaitingMessageId(assistantMessageId)
        // Reset stream complete flag for this new message
        setStreamComplete(prev => {
          const newSet = new Set(prev)
          newSet.delete(assistantMessageId) // Remove if it exists (shouldn't, but just in case)
          return newSet
        })
        
        
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
        let tokenBatchCount = 0
        let lastTokenLogTime = Date.now()
        const streamStartTime = Date.now()
        const eventTypeCounts: Record<string, number> = {}
        
        console.log(`[FRONTEND] Starting stream for session=${currentSession.id} message_preview=${content.substring(0, 50)}...`)
        
        const stream = createAgentStream(
          currentSession.id,
          content,
          token,
          (event: StreamEvent) => {
            const eventType = event.type as string
            eventTypeCounts[eventType] = (eventTypeCounts[eventType] || 0) + 1
            
            // Handle message_saved event to update temporary IDs with real DB IDs
            if (eventType === 'message_saved') {
              const savedData = event.data || {}
              const role = savedData.role
              const dbId = savedData.db_id
              const sessionId = savedData.session_id
              
              if (sessionId === currentSession.id && dbId) {
                console.log(`[FRONTEND] Updating temporary message with db_id=${dbId} role=${role} session=${sessionId}`)
                
                set((state: { messages: Message[] }) => {
                  // Find temporary message by role and update its ID
                  // For user messages, find the most recent user message with a temporary ID
                  // For assistant messages, find the message with the temporary assistantMessageId
                  const updatedMessages = state.messages.map((msg: Message) => {
                    if (role === 'user' && msg.role === 'user' && msg.id === tempUserMessageId) {
                      console.log(`[FRONTEND] Updating user message temp_id=${tempUserMessageId} -> db_id=${dbId}`)
                      return { ...msg, id: dbId }
                    } else if (role === 'assistant' && msg.role === 'assistant' && msg.id === assistantMessageId) {
                      console.log(`[FRONTEND] Updating assistant message temp_id=${assistantMessageId} -> db_id=${dbId}`)
                      return { ...msg, id: dbId }
                    }
                    return msg
                  })
                  
                  return { messages: updatedMessages }
                })
              }
              return // Don't process message_saved as a regular event
            }
            
            if (eventType === 'token') {
              tokenBatchCount++
              const now = Date.now()
              // Log token batches every 10 tokens or every 500ms, whichever comes first
              if (tokenBatchCount % 10 === 0 || (now - lastTokenLogTime) > 500) {
                console.log(`[FRONTEND] Processing tokens: batch=${tokenBatchCount} session=${currentSession.id}`)
                lastTokenLogTime = now
              }
              // First token received, hide loading indicator
              setWaitingForResponse(false)
              setWaitingMessageId(null)
              
              // Update the assistant message in store by appending the new token
              // Keep status until we have substantial content
              set((state: { messages: Message[] }) => {
                const currentMessage = state.messages.find((msg: Message) => msg.id === assistantMessageId)
                if (!currentMessage) {
                  return state // Message was removed, skip update
                }
                
                const currentContent = currentMessage.content || ''
                const tokenData = event.data || ''
                const newContent = currentContent + tokenData
                
                return {
                  messages: state.messages.map((msg: Message) =>
                    msg.id === assistantMessageId
                      ? { 
                          ...msg, 
                          content: newContent,
                          // Clear status only when we have substantial content (more than 50 chars)
                          status: newContent.length > 50 ? undefined : msg.status
                        }
                      : msg
                  ),
                }
              })
            } else if (eventType === 'update') {
              // Handle workflow state updates (agent_name, tool_calls, plan_proposal, status, etc.)
              const updateData = event.data || {}
              console.log(`[FRONTEND] Received update event session=${currentSession.id} task=${updateData.task || 'none'} status=${updateData.status || 'none'}`)
              
              // Handle task status updates - create/update system status messages in real-time
              if (updateData.task && updateData.status) {
                set((state: { messages: Message[] }) => {
                  // Check if status message already exists for this task (check both temp and DB messages)
                  const existingStatusMsg = state.messages.find(
                    (msg: Message) => 
                      msg.role === 'system' && 
                      msg.metadata?.status_type === 'task_status' &&
                      msg.metadata?.task === updateData.task
                  )
                  
                  if (existingStatusMsg) {
                    // Update existing status message (present -> past tense)
                    console.log(`[Status Update] Updating task ${updateData.task}: "${existingStatusMsg.content}" -> "${updateData.status}" (completed: ${updateData.is_completed})`)
                    return {
                      messages: state.messages.map((msg: Message) =>
                        msg.id === existingStatusMsg.id
                          ? {
                              ...msg,
                              content: updateData.status,
                              metadata: {
                                ...msg.metadata,
                                is_completed: updateData.is_completed === true
                              }
                            }
                          : msg
                      ),
                    }
                  } else {
                    // Create new status message with unique temporary ID
                    // Use negative ID to avoid conflicts with database IDs
                    const tempId = -(Date.now() + Math.random() * 1000)
                    const newStatusMessage: Message = {
                      id: tempId, // Temporary negative ID for real-time display
                      role: 'system',
                      content: updateData.status,
                      tokens_used: 0,
                      created_at: new Date().toISOString(),
                      metadata: {
                        task: updateData.task,
                        status_type: 'task_status',
                        is_completed: updateData.is_completed === true || false
                      }
                    }
                    
                    // Insert before the assistant message
                    const assistantIndex = state.messages.findIndex((msg: Message) => msg.id === assistantMessageId)
                    if (assistantIndex >= 0) {
                      const newMessages = [...state.messages]
                      newMessages.splice(assistantIndex, 0, newStatusMessage)
                      return { messages: newMessages }
                    } else {
                      return { messages: [...state.messages, newStatusMessage] }
                    }
                  }
                })
              }
              
              set((state: { messages: Message[] }) => {
                const currentMessage = state.messages.find((msg: Message) => msg.id === assistantMessageId)
                if (!currentMessage) {
                  return state
                }
                
                const updatedMetadata = {
                  ...currentMessage.metadata,
                  ...(updateData.agent_name && { agent_name: updateData.agent_name }),
                }
                
                // Handle tool status updates during streaming (Executing -> Executed)
                // But tool items (collapsible boxes) will only show after stream completes
                let updatedToolCalls = currentMessage.metadata?.tool_calls || []
                
                if (updateData.tool_calls) {
                  // Direct tool_calls array update - this comes after stream completes
                  // This is when we show the tool items
                  updatedMetadata.tool_calls = updateData.tool_calls
                } else if (updateData.tool && updateData.status) {
                  // During streaming, track tool status updates (Executing -> Executed)
                  // But don't create tool_calls array yet - tool items will only appear after stream completes
                  // Status updates are fine, but tool items (collapsible boxes) should wait
                }
                
                // Check if this is a plan_proposal response
                const updates: Partial<Message> = {
                  metadata: updatedMetadata,
                }
                
                // Update general status if provided (for task execution status, not tool-specific)
                // Only set general status if it's not a tool-specific update
                if (updateData.status && !updateData.tool) {
                  updates.status = updateData.status
                }
                
                if (updateData.type === 'plan_proposal' && updateData.plan) {
                  updates.response_type = 'plan_proposal'
                  updates.plan = updateData.plan
                }
                
                if (updateData.clarification) {
                  updates.clarification = updateData.clarification
                }
                
                return {
                  messages: state.messages.map((msg: Message) =>
                    msg.id === assistantMessageId
                      ? { ...msg, ...updates }
                      : msg
                  ),
                }
              })
            } else if (eventType === 'done') {
              // Handle completion event with final data
              // tool_calls are sent via update event (before done event), we just mark stream as complete
              const doneData = event.data || {}
              const duration = Date.now() - streamStartTime
              const eventSummary = Object.entries(eventTypeCounts)
                .map(([type, count]) => `${type}=${count}`)
                .join(', ')
              console.log(`[FRONTEND] Stream completed session=${currentSession.id} duration=${duration}ms tokens=${tokenBatchCount} events={${eventSummary}}`)
              
              // Mark stream as complete for this message - tool items can now be shown
              // tool_calls should already be set via update event, we just need to show them
              if (assistantMessageId) {
                setStreamComplete(prev => new Set(prev).add(assistantMessageId))
              }
              
              set((state: { messages: Message[] }) => {
                return {
                  messages: state.messages.map((msg: Message) =>
                    msg.id === assistantMessageId
                      ? {
                          ...msg,
                          ...(doneData.tokens_used && { tokens_used: doneData.tokens_used }),
                          ...(doneData.raw_tool_outputs && { raw_tool_outputs: doneData.raw_tool_outputs }),
                        }
                      : msg
                  ),
                }
              })
              
              // Mark all active temporary status messages as completed
              // This ensures they show as past tense even if on_chain_end events haven't fired yet
              set((state: { messages: Message[] }) => {
                return {
                  messages: state.messages.map((msg: Message) => {
                    // Update any active temporary status messages to completed
                    if (msg.id < 0 && 
                        msg.role === 'system' && 
                        msg.metadata?.status_type === 'task_status' &&
                        msg.metadata?.is_completed === false) {
                      // Convert to past tense
                      const pastTenseMap: Record<string, string> = {
                        "Processing with agent...": "Processed with agent",
                        "Routing to agent...": "Routed to agent",
                        "Loading conversation history...": "Loaded conversation history",
                        "Processing with greeter agent...": "Processed with greeter agent",
                        "Searching documents...": "Searched documents",
                        "Executing tools...": "Executed tools",
                        "Processing tool results...": "Processed tool results",
                        "Checking if summarization needed...": "Checked if summarization needed",
                        "Saving message...": "Saved message",
                      }
                      const pastContent = pastTenseMap[msg.content] || msg.content.replace(/ing\.\.\.$/, "ed").replace(/ing$/, "ed")
                      return {
                        ...msg,
                        content: pastContent,
                        metadata: {
                          ...msg.metadata,
                          is_completed: true
                        }
                      }
                    }
                    return msg
                  })
                }
              })
            } else if (eventType === 'error') {
              const errorData = event.data || {}
              const duration = Date.now() - streamStartTime
              console.error(`[FRONTEND] Error event received session=${currentSession.id} duration=${duration}ms error=${errorData.error || 'unknown'}`)
              
              toast.error(errorData.error || 'Streaming error occurred')
              setSending(false)
              setWaitingForResponse(false)
              setWaitingMessageId(null)
            } else {
              // Handle unknown event types gracefully
              console.debug(`[FRONTEND] Unknown event type received session=${currentSession.id} type=${eventType}`, event)
            }
          },
          (error: Error) => {
            const duration = Date.now() - streamStartTime
            console.error(`[FRONTEND] Stream connection error session=${currentSession.id} duration=${duration}ms error=${error.message}`)
            toast.error(error.message || 'Streaming connection error')
            setSending(false)
            setWaitingForResponse(false)
            setWaitingMessageId(null)
          },
          async () => {
            // Stream complete - no reload needed!
            // All data (content, tool_calls, agent_name, metadata) comes from the stream
            // Status messages are ephemeral and already updated in real-time
            // The assistant message is already complete with all metadata from update events
            const duration = Date.now() - streamStartTime
            const eventSummary = Object.entries(eventTypeCounts)
              .map(([type, count]) => `${type}=${count}`)
              .join(', ')
            console.log(`[FRONTEND] Stream handler completed session=${currentSession.id} duration=${duration}ms tokens=${tokenBatchCount} events={${eventSummary}}`)
            
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
          
          // Check if response contains plan_proposal
          if (response.data?.type === 'plan_proposal' && response.data?.plan) {
            // Update the assistant message with plan proposal
            set((state: { messages: Message[] }) => {
              const lastMessage = state.messages[state.messages.length - 1]
              if (lastMessage && lastMessage.role === 'assistant') {
                return {
                  messages: state.messages.map((msg: Message) =>
                    msg.id === lastMessage.id
                      ? {
                          ...msg,
                          response_type: 'plan_proposal',
                          plan: response.data.plan,
                          metadata: {
                            ...msg.metadata,
                            agent_name: response.data.agent_name || msg.metadata?.agent_name,
                          },
                        }
                      : msg
                  ),
                }
              }
              return state
            })
          }
          
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
    // Keep sidebar open - don't auto-close when selecting a chat
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

  const handleDeleteSession = async (id: number, e?: React.MouseEvent) => {
    if (e) {
      e.stopPropagation()
    }
    setSessionToDelete(id)
    setDeleteDialogOpen(true)
    setHeaderMoreMenuOpen(false)
    setSessionMenuOpen(null)
  }
  
  const handleDeleteCurrentChat = () => {
    if (currentSession) {
      handleDeleteSession(currentSession.id)
    }
  }

  const handleRenameSession = (sessionId: number, currentTitle: string) => {
    setRenameSessionId(sessionId)
    setRenameSessionTitle(currentTitle || '')
    setSessionMenuOpen(null)
  }

  const handleSaveRename = async () => {
    if (renameSessionId === null) return
    
    try {
      await chatAPI.updateSessionTitle(renameSessionId, renameSessionTitle.trim())
      await loadSessions()
      
      // Update current session if it's the one being renamed
      if (currentSession?.id === renameSessionId) {
        const updatedSession = { ...currentSession, title: renameSessionTitle.trim() }
        set({ currentSession: updatedSession })
      }
      
      setRenameSessionId(null)
      setRenameSessionTitle('')
      toast.success('Chat renamed successfully')
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, 'Failed to rename chat'))
    }
  }

  const handleCancelRename = () => {
    setRenameSessionId(null)
    setRenameSessionTitle('')
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

    // Add badge for files
    const fileNames = files.map(f => f.name).join(', ')
    const fileLabel = files.length === 1 ? fileNames : `${files.length} files`
    setSelectedOptions((prev) => [...prev, {
      type: 'files',
      label: fileLabel,
      icon: (
        <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
        </svg>
      ),
      data: files
    }])

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

  // Handle plus menu option selection
  const handlePlusMenuOption = (optionId: string) => {
    setPlusMenuOpen(false)
    
    if (optionId === 'add_files') {
      fileInputRef.current?.click()
    } else if (optionId === 'streaming') {
      setUseStreaming(!useStreaming)
    }
  }

  // Remove selected option badge
  const removeSelectedOption = (index: number) => {
    const option = selectedOptions[index]
    setSelectedOptions((prev) => prev.filter((_, i) => i !== index))
    
    // If it was a file option, also remove from attachedFiles
    if (option.type === 'files' && option.data) {
      setAttachedFiles((prev) => prev.filter((_, i) => !option.data.includes(i)))
    }
  }

  // Handle file selection from plus menu
  const handleFileSelectionFromPlus = () => {
    setPlusMenuOpen(false)
    fileInputRef.current?.click()
  }

  // Handle plan approval
  const handlePlanApproval = useCallback(async (messageId: number, plan: PlanProposalData) => {
    if (!currentSession || sending) return

    setExecutingPlanMessageId(messageId)
    setSending(true)

    try {
      const token = localStorage.getItem('access_token')
      if (!token) {
        throw new Error('No authentication token')
      }

      // Extract plan steps from proposal
      const planSteps = plan.plan.map((step) => ({
        action: step.action,
        tool: step.tool,
        props: step.props,
        agent: step.agent,
        query: step.query,
      }))

      if (useStreaming) {
        // Create streaming message for plan execution
        const executionMessageId = Date.now() + 1
        setWaitingForResponse(true)
        setWaitingMessageId(executionMessageId)
        set((state: { messages: Message[] }) => ({
          messages: [
            ...state.messages,
            {
              id: executionMessageId,
              role: 'assistant' as const,
              content: '',
              tokens_used: 0,
              created_at: new Date().toISOString(),
              metadata: { agent_name: plan.plan[0]?.agent || 'greeter' },
              response_type: 'answer',
            },
          ],
        }))

        // Stream plan execution
        const stream = createAgentStream(
          currentSession.id,
          '', // Empty message for plan execution
          token,
          (event: StreamEvent) => {
            if (event.type === 'token') {
              setWaitingForResponse(false)
              setWaitingMessageId(null)
              set((state: { messages: Message[] }) => {
                const currentMessage = state.messages.find((msg: Message) => msg.id === executionMessageId)
                const currentContent = currentMessage?.content || ''
                const tokenData = event.data || ''
                const newContent = currentContent + tokenData
                
                return {
                  messages: state.messages.map((msg: Message) =>
                    msg.id === executionMessageId
                      ? { ...msg, content: newContent }
                      : msg
                  ),
                }
              })
            } else if (event.type === 'update') {
              const updateData = event.data || {}
              set((state: { messages: Message[] }) => {
                const currentMessage = state.messages.find((msg: Message) => msg.id === executionMessageId)
                if (!currentMessage) return state
                
                const updatedMetadata = {
                  ...currentMessage.metadata,
                  ...(updateData.agent_name && { agent_name: updateData.agent_name }),
                  ...(updateData.tool_calls && { tool_calls: updateData.tool_calls }),
                }
                
                return {
                  messages: state.messages.map((msg: Message) =>
                    msg.id === executionMessageId
                      ? { ...msg, metadata: updatedMetadata }
                      : msg
                  ),
                }
              })
            } else if (event.type === 'done') {
              const doneData = event.data || {}
              set((state: { messages: Message[] }) => {
                return {
                  messages: state.messages.map((msg: Message) =>
                    msg.id === executionMessageId
                      ? {
                          ...msg,
                          ...(doneData.tokens_used && { tokens_used: doneData.tokens_used }),
                        }
                      : msg
                  ),
                }
              })
            } else if (event.type === 'error') {
              toast.error(event.data?.error || 'Plan execution error')
              setSending(false)
              setWaitingForResponse(false)
              setWaitingMessageId(null)
            }
          },
          (error: Error) => {
            toast.error(error.message || 'Plan execution connection error')
            setSending(false)
            setWaitingForResponse(false)
            setWaitingMessageId(null)
          },
          () => {
            loadMessages(currentSession.id)
            setSending(false)
            setWaitingForResponse(false)
            setWaitingMessageId(null)
            setExecutingPlanMessageId(null)
          },
          planSteps,
          'plan'
        )

        streamRef.current = stream
      } else {
        // Non-streaming plan execution
        setWaitingForResponse(true)
        setWaitingMessageId(null)
        try {
          const response = await agentAPI.runAgent({
            chat_session_id: currentSession.id,
            message: '', // Empty message for plan execution
            plan_steps: planSteps,
            flow: 'plan',
          })
          
          // Reload messages to get execution results
          loadMessages(currentSession.id)
        } finally {
          setSending(false)
          setWaitingForResponse(false)
          setWaitingMessageId(null)
          setExecutingPlanMessageId(null)
        }
      }
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, 'Failed to execute plan'))
      setSending(false)
      setExecutingPlanMessageId(null)
    }
  }, [currentSession, sending, useStreaming, loadMessages])

  // Handle plan rejection
  const handlePlanRejection = useCallback((messageId: number) => {
    // Update message to show rejection
    set((state: { messages: Message[] }) => ({
      messages: state.messages.map((msg: Message) =>
        msg.id === messageId
          ? {
              ...msg,
              content: msg.content || 'Plan rejected. You can modify your query or continue the conversation.',
              response_type: 'answer',
            }
          : msg
      ),
    }))
    toast.info('Plan rejected')
  }, [])

  return (
    <>
    <div className="flex h-[calc(100vh-145px)] bg-background">
      {/* Collapsible Sidebar */}
      <div className={`${sidebarOpen ? 'w-64' : 'w-0'} transition-all duration-300 overflow-hidden border-r flex flex-col bg-background`}>
        <div className="flex-1 overflow-y-auto min-w-[256px]">
          {/* Chats Section Header */}
          <div className="px-3 py-2 space-y-2">
            <div className="flex items-center justify-between">
              <button
                onClick={() => setChatsSectionOpen(!chatsSectionOpen)}
                className="flex items-center gap-1 text-sm font-medium text-muted-foreground hover:text-foreground transition-colors"
              >
                <span>Chats</span>
                <svg
                  className={`w-4 h-4 transition-transform ${chatsSectionOpen ? 'rotate-90' : ''}`}
                  fill="none"
                  stroke="currentColor"
                  viewBox="0 0 24 24"
                >
                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                </svg>
              </button>
            </div>
            {chatsSectionOpen && (
              <Button onClick={handleNewChat} className="w-full" size="sm">
                New Chat
              </Button>
            )}
          </div>

          {chatsSectionOpen && (
            <>
              {loading && sessions.length === 0 ? (
                <div className="px-3 py-2 text-center text-muted-foreground text-sm">Loading...</div>
              ) : sessions.length === 0 ? (
                <div className="px-3 py-2 text-center text-muted-foreground text-sm">
                  No chats yet
                </div>
              ) : (
                <div>
                  {sessions.map((session: { id: number; title: string; updated_at: string }) => (
                    <div
                      key={session.id}
                      className={`group relative px-3 py-2 mx-2 rounded-lg cursor-pointer transition-colors ${
                        currentSession?.id === session.id 
                          ? 'bg-primary/10 hover:bg-primary/15' 
                          : 'hover:bg-muted/50'
                      }`}
                    >
                      {renameSessionId === session.id ? (
                        <div className="flex items-center gap-2" onClick={(e) => e.stopPropagation()}>
                          <input
                            type="text"
                            value={renameSessionTitle}
                            onChange={(e) => setRenameSessionTitle(e.target.value)}
                            onKeyDown={(e) => {
                              if (e.key === 'Enter') {
                                handleSaveRename()
                              } else if (e.key === 'Escape') {
                                handleCancelRename()
                              }
                            }}
                            onClick={(e) => e.stopPropagation()}
                            className="flex-1 px-2 py-1 text-sm border rounded bg-background"
                            autoFocus
                          />
                          <button
                            onClick={handleSaveRename}
                            className="p-1 hover:bg-muted rounded"
                            title="Save"
                          >
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 13l4 4L19 7" />
                            </svg>
                          </button>
                          <button
                            onClick={handleCancelRename}
                            className="p-1 hover:bg-muted rounded"
                            title="Cancel"
                          >
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                            </svg>
                          </button>
                        </div>
                      ) : (
                        <>
                          <div
                            onClick={() => {
                              handleSelectSession(session.id)
                            }}
                            className="flex items-center justify-between"
                          >
                            <div className="flex-1 min-w-0">
                              <p className={`text-sm truncate ${
                                currentSession?.id === session.id 
                                  ? 'font-semibold text-foreground' 
                                  : 'font-medium'
                              }`}>
                                {session.title || 'Untitled Chat'}
                              </p>
                            </div>
                            <button
                              onClick={(e: React.MouseEvent) => {
                                e.stopPropagation()
                                setSessionMenuOpen(sessionMenuOpen === session.id ? null : session.id)
                              }}
                              className="ml-2 opacity-0 group-hover:opacity-100 transition-opacity p-1 hover:bg-muted rounded"
                              title="More options"
                            >
                              <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 12h.01M12 12h.01M19 12h.01M6 12a1 1 0 11-2 0 1 1 0 012 0zm7 0a1 1 0 11-2 0 1 1 0 012 0zm7 0a1 1 0 11-2 0 1 1 0 012 0z" />
                              </svg>
                            </button>
                          </div>

                          {/* Three-dot menu dropdown */}
                          {sessionMenuOpen === session.id && (
                            <>
                              <div
                                className="fixed inset-0 z-10"
                                onClick={() => setSessionMenuOpen(null)}
                              />
                              <div className="absolute right-0 top-full mt-1 w-48 bg-background border rounded-lg shadow-lg p-1 z-20">
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    handleRenameSession(session.id, session.title || '')
                                  }}
                                  className="w-full flex items-center gap-2 px-3 py-2 hover:bg-muted rounded-md transition-colors text-left text-sm"
                                >
                                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                                  </svg>
                                  <span>Rename</span>
                                </button>
                                <button
                                  onClick={(e) => {
                                    e.stopPropagation()
                                    handleDeleteSession(session.id, e)
                                  }}
                                  className="w-full flex items-center gap-2 px-3 py-2 hover:bg-muted rounded-md transition-colors text-left text-sm text-destructive"
                                >
                                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                                  </svg>
                                  <span>Delete</span>
                                </button>
                              </div>
                            </>
                          )}
                        </>
                      )}
                    </div>
                  ))}
                </div>
              )}
            </>
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
            <div className="px-4 py-1 flex items-center justify-between bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
              <div className="flex items-center gap-2">
                <button
                  onClick={() => setSidebarOpen(!sidebarOpen)}
                  className="p-1 hover:bg-muted rounded-md transition-colors"
                  aria-label="Toggle sidebar"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
                  </svg>
                </button>
                {/* Model Selection Dropdown */}
                <div className="relative">
                  <button
                    onClick={() => setModelDropdownOpen(!modelDropdownOpen)}
                    className="flex items-center gap-1 px-2 py-0.5 hover:bg-muted rounded-md transition-colors text-sm"
                  >
                    <span className="font-medium">
                      {availableModels.find(m => m.id === selectedModel)?.name || selectedModel}
                    </span>
                    <svg 
                      className={`w-3 h-3 transition-transform ${modelDropdownOpen ? 'rotate-180' : ''}`}
                      fill="none" 
                      stroke="currentColor" 
                      viewBox="0 0 24 24"
                    >
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                    </svg>
                  </button>
                  
                  {/* Model Dropdown Menu */}
                  {modelDropdownOpen && (
                    <>
                      <div
                        className="fixed inset-0 z-10"
                        onClick={() => setModelDropdownOpen(false)}
                      />
                      <div className="absolute top-full left-0 mt-1 w-56 bg-background border rounded-lg shadow-lg p-1 z-20">
                        {availableModels.map((model) => (
                          <button
                            key={model.id}
                            onClick={() => handleModelChange(model.id)}
                            className={`w-full flex flex-col items-start px-3 py-2 hover:bg-muted rounded-md transition-colors text-left ${
                              selectedModel === model.id ? 'bg-muted' : ''
                            }`}
                          >
                            <span className="text-sm font-medium">{model.name}</span>
                            <span className="text-xs text-muted-foreground">{model.description}</span>
                          </button>
                        ))}
                      </div>
                    </>
                  )}
                </div>
              </div>
              <div className="flex items-center gap-1">
                {/* Three dots menu */}
                <div className="relative">
                  <button
                    onClick={() => setHeaderMoreMenuOpen(!headerMoreMenuOpen)}
                    className="p-1 hover:bg-muted rounded-md transition-colors"
                    aria-label="More options"
                    title="More options"
                  >
                    <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 12h.01M12 12h.01M19 12h.01M6 12a1 1 0 11-2 0 1 1 0 012 0zm7 0a1 1 0 11-2 0 1 1 0 012 0zm7 0a1 1 0 11-2 0 1 1 0 012 0z" />
                    </svg>
                  </button>
                  
                  {/* More Menu Dropdown */}
                  {headerMoreMenuOpen && (
                    <>
                      <div
                        className="fixed inset-0 z-10"
                        onClick={() => setHeaderMoreMenuOpen(false)}
                      />
                      <div className="absolute top-full right-0 mt-1 w-48 bg-background border rounded-lg shadow-lg p-1 z-20">
                        <button
                          onClick={() => {
                            handleOpenStats()
                            setHeaderMoreMenuOpen(false)
                          }}
                          className="w-full flex items-center gap-2 px-3 py-2 hover:bg-muted rounded-md transition-colors text-left text-sm"
                        >
                          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                          </svg>
                          <span>Statistics</span>
                        </button>
                        {currentSession && (
                          <button
                            onClick={() => handleDeleteCurrentChat()}
                            className="w-full flex items-center gap-2 px-3 py-2 hover:bg-muted rounded-md transition-colors text-left text-sm text-destructive"
                          >
                            <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 7l-.867 12.142A2 2 0 0116.138 21H7.862a2 2 0 01-1.995-1.858L5 7m5 4v6m4-6v6m1-10V4a1 1 0 00-1-1h-4a1 1 0 00-1 1v3M4 7h16" />
                            </svg>
                            <span>Delete chat</span>
                          </button>
                        )}
                      </div>
                    </>
                  )}
                </div>
              </div>
            </div>

            {/* Messages Area */}
            <div className="flex-1 overflow-y-auto">
              {messages.length === 0 ? (
                <div className="flex items-center justify-center min-h-[60vh]">
                  <div className="w-full max-w-2xl px-4">
                    <div className="text-center mb-8">
                      <h2 className="text-4xl font-light text-foreground/80 mb-2">
                        What can I help with?
                      </h2>
                    </div>
                    {/* Centered Input Area */}
                    <div className="relative">
                      {/* Selected Options Badges */}
                      {selectedOptions.length > 0 && (
                        <div className="flex flex-wrap gap-2 mb-3 justify-center">
                          {selectedOptions.map((option, idx) => (
                            <div
                              key={idx}
                              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-primary/10 text-primary text-sm"
                            >
                              {option.icon}
                              <span>{option.label}</span>
                              <button
                                onClick={() => removeSelectedOption(idx)}
                                className="ml-1 hover:bg-primary/20 rounded-full p-0.5 transition-colors"
                                aria-label="Remove"
                              >
                                <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" />
                                </svg>
                              </button>
                            </div>
                          ))}
                        </div>
                      )}
                      
                      {/* Input Bar */}
                      <div className="relative flex flex-col bg-background border rounded-2xl shadow-sm">
                        {/* Textarea Area */}
                        <textarea
                          value={input}
                          onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => {
                            setInput(e.target.value)
                            e.target.style.height = 'auto'
                            e.target.style.height = `${Math.min(e.target.scrollHeight, 200)}px`
                          }}
                          onFocus={() => setInputFocused(true)}
                          onBlur={() => setInputFocused(false)}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' && !e.shiftKey) {
                              e.preventDefault()
                              handleSend()
                            }
                          }}
                          placeholder="Ask anything"
                          className="flex-1 min-h-[52px] max-h-[200px] px-4 pt-3 pb-2 border-0 bg-transparent resize-none focus:outline-none text-[15px] leading-relaxed"
                          disabled={sending}
                          rows={1}
                        />

                        {/* Bottom Controls */}
                        <div className="flex items-center justify-between px-3 pb-2.5">
                          {/* Plus Button */}
                          <div className="relative flex-shrink-0">
                            <button
                              type="button"
                              onClick={() => setPlusMenuOpen(!plusMenuOpen)}
                              className="w-8 h-8 rounded-full hover:bg-muted flex items-center justify-center transition-colors"
                              aria-label="More options"
                              disabled={sending}
                            >
                              <svg className="w-5 h-5 text-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                              </svg>
                            </button>
                            
                            {/* Plus Menu Dropdown */}
                            {plusMenuOpen && (
                              <>
                                <div
                                  className="fixed inset-0 z-10"
                                  onClick={() => setPlusMenuOpen(false)}
                                />
                                <div className="absolute bottom-full left-0 mb-2 w-64 bg-background border rounded-lg shadow-lg p-2 z-20">
                                  <button
                                    type="button"
                                    onClick={handleFileSelectionFromPlus}
                                    className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-muted rounded-md text-sm text-left transition-colors"
                                  >
                                    <svg className="w-5 h-5 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                                    </svg>
                                    <span>Add photos & files</span>
                                  </button>
                                  <div className="flex items-center justify-between px-3 py-2.5 hover:bg-muted rounded-md cursor-pointer transition-colors">
                                    <div className="flex items-center gap-3">
                                      <svg className="w-5 h-5 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                                      </svg>
                                      <span className="text-sm">Streaming</span>
                                    </div>
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
                                      aria-checked={useStreaming}
                                      role="switch"
                                    >
                                      <span
                                        className={`
                                          inline-block h-4 w-4 transform rounded-full bg-white transition-transform
                                          ${useStreaming ? 'translate-x-5' : 'translate-x-0.5'}
                                        `}
                                      />
                                    </button>
                                  </div>
                                  <button
                                    type="button"
                                    className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-muted rounded-md text-sm text-left transition-colors"
                                    disabled
                                  >
                                    <svg className="w-5 h-5 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z" />
                                    </svg>
                                    <span className="text-muted-foreground">... More</span>
                                  </button>
                                </div>
                              </>
                            )}
                          </div>

                          <input
                            ref={fileInputRef}
                            type="file"
                            multiple
                            onChange={handleFileSelect}
                            className="hidden"
                            disabled={sending}
                          />

                          {/* Send Button */}
                          <button
                            type="submit"
                            onClick={handleSend}
                            disabled={sending || (!input.trim() && attachedFiles.length === 0)}
                            className="p-2 rounded-lg hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                            aria-label="Send message"
                          >
                            <svg className="w-5 h-5 text-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                            </svg>
                          </button>
                        </div>
                      </div>
                    </div>
                  </div>
                </div>
              ) : (
                <div className="max-w-3xl mx-auto px-4 py-8">
                  <div className="space-y-6">
                    {(() => {
                      // Deduplicate messages by ID before rendering
                      const seenIds = new Set<number>()
                      const uniqueMessages = messages.filter((msg: Message) => {
                        if (seenIds.has(msg.id)) {
                          return false
                        }
                        seenIds.add(msg.id)
                        return true
                      })
                      
                      return uniqueMessages.map((msg: Message) => {
                        const agentName = getAgentName(msg)
                        // Show loading indicator for streaming mode when message exists but has no content yet
                        const isPlanProposal = msg.response_type === 'plan_proposal' && msg.plan
                        const isExecutingPlan = executingPlanMessageId === msg.id
                        const hasClarification = msg.clarification
                        const hasRawToolOutputs = msg.raw_tool_outputs && msg.raw_tool_outputs.length > 0
                        const isStatusMessage = msg.role === 'system' && msg.metadata?.status_type === 'task_status'
                        
                        // Render status messages as system messages with animation (like Cursor chat)
                        if (isStatusMessage) {
                          const isCompleted = msg.metadata?.is_completed === true
                          // Check if previous message is also a status message to reduce gap
                          const msgIndex = messages.indexOf(msg)
                          const prevMsg = msgIndex > 0 ? messages[msgIndex - 1] : null
                          const isPrevStatus = prevMsg?.role === 'system' && prevMsg?.metadata?.status_type === 'task_status'
                          
                          return (
                            <div
                              key={msg.id}
                              className="flex gap-2 items-center justify-start"
                              style={{ 
                                lineHeight: '1',
                                marginTop: isPrevStatus ? '-4px' : '0',
                                marginBottom: '0',
                                paddingTop: '0',
                                paddingBottom: '0'
                              }}
                            >
                              <div className="w-6 h-6 flex items-center justify-center flex-shrink-0" style={{ margin: '0', padding: '0' }}>
                                {/* Animated dot for active status, static for completed */}
                                {!isCompleted ? (
                                  <span 
                                    className="w-1.5 h-1.5 bg-primary rounded-full" 
                                    style={{ 
                                      animation: 'breathe 1.4s ease-in-out infinite',
                                    }}
                                  ></span>
                                ) : (
                                  <span className="w-1.5 h-1.5 bg-muted-foreground/40 rounded-full"></span>
                                )}
                              </div>
                              <div className="flex flex-col max-w-[85%]" style={{ margin: '0', padding: '0' }}>
                                <div 
                                  className={`text-xs px-1 ${isCompleted ? 'text-muted-foreground italic' : 'text-foreground'}`} 
                                  style={{ 
                                    lineHeight: '1',
                                    margin: '0',
                                    padding: '0'
                                  }}
                                >
                                  {msg.content}
                                </div>
                              </div>
                            </div>
                          )
                        }
                        
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
                                  : 'bg-muted text-foreground'
                              }`}
                            >
                              {msg.role === 'user' ? (
                                <p className="text-[15px] leading-relaxed whitespace-pre-wrap break-words">
                                  {msg.content}
                                </p>
                              ) : isPlanProposal && msg.plan ? (
                                // Plan proposal rendering
                                <PlanProposal
                                  plan={msg.plan}
                                  onApprove={() => handlePlanApproval(msg.id, msg.plan!)}
                                  onReject={() => handlePlanRejection(msg.id)}
                                  isExecuting={isExecutingPlan}
                                />
                              ) : hasClarification ? (
                                // Clarification request rendering
                                <div className="space-y-3">
                                  <div className="text-sm text-muted-foreground italic">
                                    {msg.clarification}
                                  </div>
                                  <div className="text-sm">
                                    Please provide clarification to continue.
                                  </div>
                                </div>
                              ) : (
                                // Regular answer rendering
                                <MarkdownMessage content={msg.content} />
                              )}
                            </div>
                            
                            {/* Raw tool outputs from plan execution */}
                            {hasRawToolOutputs && (
                              <div className="mt-3 px-1 space-y-2">
                                <div className="text-xs font-semibold text-muted-foreground mb-2">
                                  Plan Execution Results:
                                </div>
                                {msg.raw_tool_outputs!.map((output, idx) => (
                                  <div
                                    key={idx}
                                    className="border rounded-lg bg-muted/30 p-3 space-y-2"
                                  >
                                    <div className="flex items-center gap-2">
                                      <span className="text-sm font-medium">
                                        {output.tool || `Tool ${idx + 1}`}
                                      </span>
                                    </div>
                                    {output.output && (
                                      <div className="text-xs bg-background/50 p-2 rounded border max-h-64 overflow-auto">
                                        <JsonViewer 
                                          data={output.output} 
                                          collapsed={2}
                                        />
                                      </div>
                                    )}
                                    {output.error && (
                                      <div className="text-xs text-destructive bg-destructive/10 p-2 rounded">
                                        Error: {output.error}
                                      </div>
                                    )}
                                  </div>
                                ))}
                              </div>
                            )}
                            {/* Tool calls - collapsible boxes (displayed at end of message, only after stream completes) */}
                            {/* Tool status updates (Executing -> Executed) show during streaming, but tool items only after stream ends */}
                            {/* For DB messages (positive IDs): always show if they have tool_calls. For temporary messages (negative IDs): only show after streamComplete */}
                            {msg.role === 'assistant' && 
                             msg.metadata?.tool_calls && 
                             Array.isArray(msg.metadata.tool_calls) && 
                             msg.metadata.tool_calls.length > 0 && 
                             (msg.id > 0 || streamComplete.has(msg.id)) && (
                              <div className="mt-3 px-1 space-y-2">
                                {msg.metadata.tool_calls.map((toolCall: any, idx: number) => {
                                  const toolCallId = `tool-${msg.id}-${idx}`
                                  const isExpanded = expandedToolCalls.has(toolCallId)
                                  const toolName = toolCall.tool || toolCall.name || 'Tool'
                                  
                                  // Extract document references from RAG tool results
                                  const extractDocReferences = (result: string) => {
                                    const docRefs: Array<{ title: string; page?: number }> = []
                                    // Look for patterns like [Document Title, page X] or [Document Title]
                                    const refPattern = /\[([^\]]+?)(?:,\s*page\s+(\d+))?\]/g
                                    let match
                                    while ((match = refPattern.exec(result)) !== null) {
                                      const title = match[1].trim()
                                      const page = match[2] ? parseInt(match[2]) : undefined
                                      if (title && !docRefs.find(ref => ref.title === title && ref.page === page)) {
                                        docRefs.push({ title, page })
                                      }
                                    }
                                    return docRefs
                                  }
                                  
                                  const docReferences = toolCall.result ? extractDocReferences(String(toolCall.result)) : []
                                  
                                  return (
                                    <div
                                      key={idx}
                                      className="border rounded-lg bg-muted/30 overflow-hidden"
                                    >
                                      <button
                                        onClick={() => {
                                          setExpandedToolCalls((prev) => {
                                            const next = new Set(prev)
                                            if (next.has(toolCallId)) {
                                              next.delete(toolCallId)
                                            } else {
                                              next.add(toolCallId)
                                            }
                                            return next
                                          })
                                        }}
                                        className="w-full px-3 py-2 flex items-center justify-between hover:bg-muted/50 transition-colors"
                                      >
                                        <div className="flex items-center gap-2">
                                          <svg className="w-4 h-4 text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
                                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
                                          </svg>
                                          <span className="text-sm font-medium">{toolName}</span>
                                          {docReferences.length > 0 && (
                                            <span className="text-xs text-muted-foreground">
                                              ({docReferences.length} {docReferences.length === 1 ? 'document' : 'documents'})
                                            </span>
                                          )}
                                        </div>
                                        <svg
                                          className={`w-4 h-4 text-muted-foreground transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                                          fill="none"
                                          stroke="currentColor"
                                          viewBox="0 0 24 24"
                                        >
                                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                                        </svg>
                                      </button>
                                      
                                      {isExpanded && (
                                        <div className="px-3 py-2 border-t bg-muted/20 space-y-3">
                                          {/* Tool arguments */}
                                          {toolCall.args && (
                                            <div>
                                              <div className="text-xs font-semibold text-muted-foreground mb-1">Arguments</div>
                                              <div className="text-xs font-mono bg-background/50 p-2 rounded">
                                                {typeof toolCall.args === 'string' 
                                                  ? toolCall.args 
                                                  : JSON.stringify(toolCall.args, null, 2)}
                                              </div>
                                            </div>
                                          )}
                                          
                                          {/* Document references */}
                                          {docReferences.length > 0 && (
                                            <div>
                                              <div className="text-xs font-semibold text-muted-foreground mb-1">Document References</div>
                                              <div className="flex flex-wrap gap-1.5">
                                                {docReferences.map((ref, refIdx) => (
                                                  <button
                                                    key={refIdx}
                                                    onClick={() => {
                                                      // Navigate to documents page and open preview
                                                      navigate('/documents')
                                                      // Could enhance this to open specific document preview
                                                    }}
                                                    className="inline-flex items-center gap-1 px-2 py-1 text-xs bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200 rounded hover:bg-blue-200 dark:hover:bg-blue-800 transition-colors cursor-pointer"
                                                  >
                                                    <svg className="w-3 h-3" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                                                    </svg>
                                                    {ref.title}
                                                    {ref.page && <span className="text-muted-foreground"> (p. {ref.page})</span>}
                                                  </button>
                                                ))}
                                              </div>
                                            </div>
                                          )}
                                          
                                          {/* Tool result preview */}
                                          {toolCall.result && (
                                            <div>
                                              <div className="text-xs font-semibold text-muted-foreground mb-1">Result Preview</div>
                                              <div className="max-h-64 overflow-auto border rounded bg-background/50 p-2">
                                                <JsonViewer 
                                                  data={toolCall.result} 
                                                  collapsed={2}
                                                />
                                              </div>
                                            </div>
                                          )}
                                          
                                          {/* Tool execution status */}
                                          {toolCall.status && (
                                            <div>
                                              <div className="text-xs font-semibold text-muted-foreground mb-1">Status</div>
                                              <div className={`text-xs px-2 py-1 rounded inline-block ${
                                                toolCall.status === 'completed' ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' :
                                                toolCall.status === 'executing' ? 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200' :
                                                toolCall.status === 'error' ? 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200' :
                                                'bg-muted text-muted-foreground'
                                              }`}>
                                                {toolCall.status}
                                              </div>
                                            </div>
                                          )}
                                          
                                          {/* Raw tool output (for plan execution) */}
                                          {toolCall.raw_output && (
                                            <div>
                                              <div className="text-xs font-semibold text-muted-foreground mb-1">Raw Output</div>
                                              <div className="max-h-64 overflow-auto border rounded bg-background/50 p-2">
                                                <JsonViewer 
                                                  data={toolCall.raw_output} 
                                                  collapsed={1}
                                                />
                                              </div>
                                            </div>
                                          )}
                                        </div>
                                      )}
                                    </div>
                                  )
                                })}
                              </div>
                            )}
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
                      })
                    })()}
                    {/* Loading indicator removed - status messages are now shown as system messages */}
                    <div ref={messagesEndRef} />
                  </div>
                </div>
              )}
            </div>

            {/* Input Area - Only show when messages exist */}
            {messages.length > 0 && (
              <div className="bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 animate-slide-up">
              <div className="max-w-3xl mx-auto px-4 pt-2 pb-1">
                {error && (
                  <div className="mb-3 p-3 bg-destructive/10 text-destructive text-sm rounded-lg">
                    {error}
                  </div>
                )}
                
                {/* Selected Options Badges */}
                {selectedOptions.length > 0 && (
                  <div className="mb-3 flex flex-wrap gap-2">
                    {selectedOptions.map((option, idx) => (
                      <div
                        key={idx}
                        className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-primary/10 text-primary text-sm"
                      >
                        {option.icon}
                        <span>{option.label}</span>
                        <button
                          onClick={() => removeSelectedOption(idx)}
                          className="ml-1 hover:bg-primary/20 rounded-full p-0.5 transition-colors"
                          aria-label="Remove"
                        >
                          <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24">
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
                  <div className="relative flex flex-col bg-background border rounded-2xl shadow-sm">
                    {/* Textarea Area */}
                    <textarea
                      value={input}
                      onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => {
                        setInput(e.target.value)
                        // Auto-resize textarea
                        e.target.style.height = 'auto'
                        e.target.style.height = `${Math.min(e.target.scrollHeight, 200)}px`
                      }}
                      onFocus={() => setInputFocused(true)}
                      onBlur={() => setInputFocused(false)}
                      onKeyDown={(e) => {
                        if (e.key === 'Enter' && !e.shiftKey) {
                          e.preventDefault()
                          handleSend()
                        }
                      }}
                      placeholder="Message..."
                      className="flex-1 min-h-[52px] max-h-[200px] px-4 pt-3 pb-2 border-0 bg-transparent resize-none focus:outline-none text-[15px] leading-relaxed"
                      disabled={sending}
                      rows={1}
                    />

                    {/* Bottom Controls */}
                    <div className="flex items-center justify-between px-3 pb-2.5">
                      {/* Plus Button */}
                      <div className="relative flex-shrink-0">
                        <button
                          type="button"
                          onClick={() => setPlusMenuOpen(!plusMenuOpen)}
                          className="w-8 h-8 rounded-full hover:bg-muted flex items-center justify-center transition-colors"
                          aria-label="More options"
                          disabled={sending}
                        >
                          <svg className="w-5 h-5 text-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" />
                          </svg>
                        </button>
                        
                        {/* Plus Menu Dropdown */}
                        {plusMenuOpen && (
                          <>
                            <div
                              className="fixed inset-0 z-10"
                              onClick={() => setPlusMenuOpen(false)}
                            />
                            <div className="absolute bottom-full left-0 mb-2 w-64 bg-background border rounded-lg shadow-lg p-2 z-20">
                              <button
                                type="button"
                                onClick={handleFileSelectionFromPlus}
                                className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-muted rounded-md text-sm text-left transition-colors"
                              >
                                <svg className="w-5 h-5 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15.172 7l-6.586 6.586a2 2 0 102.828 2.828l6.414-6.586a4 4 0 00-5.656-5.656l-6.415 6.585a6 6 0 108.486 8.486L20.5 13" />
                                </svg>
                                <span>Add photos & files</span>
                              </button>
                              <div className="flex items-center justify-between px-3 py-2.5 hover:bg-muted rounded-md cursor-pointer transition-colors">
                                <div className="flex items-center gap-3">
                                  <svg className="w-5 h-5 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 10V3L4 14h7v7l9-11h-7z" />
                                  </svg>
                                  <span className="text-sm">Streaming</span>
                                </div>
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
                                  aria-checked={useStreaming}
                                  role="switch"
                                >
                                  <span
                                    className={`
                                      inline-block h-4 w-4 transform rounded-full bg-white transition-transform
                                      ${useStreaming ? 'translate-x-5' : 'translate-x-0.5'}
                                    `}
                                  />
                                </button>
                              </div>
                              <button
                                type="button"
                                className="w-full flex items-center gap-3 px-3 py-2.5 hover:bg-muted rounded-md text-sm text-left transition-colors"
                                disabled
                              >
                                <svg className="w-5 h-5 text-muted-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                                  <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 5v.01M12 12v.01M12 19v.01M12 6a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2zm0 7a1 1 0 110-2 1 1 0 010 2z" />
                                </svg>
                                <span className="text-muted-foreground">... More</span>
                              </button>
                            </div>
                          </>
                        )}
                      </div>

                      <input
                        ref={fileInputRef}
                        type="file"
                        multiple
                        onChange={handleFileSelect}
                        className="hidden"
                        disabled={sending}
                      />

                      {/* Send Button */}
                      <button
                        type="submit"
                        onClick={handleSend}
                        disabled={sending || (!input.trim() && attachedFiles.length === 0)}
                        className="p-2 rounded-lg hover:bg-muted transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
                        aria-label="Send message"
                      >
                        <svg className="w-5 h-5 text-foreground" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                          <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 19l9 2-9-18-9 18 9-2zm0 0v-8" />
                        </svg>
                      </button>
                    </div>
                  </div>
                </form>
              </div>
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
                          
                          // Find the user message for this chain
                          // Look for the first activity that has a user message or input_preview
                          const userMessage = chain.activities.find((activity: any) => 
                            activity.category === 'llm' && activity.input_preview
                          )?.input_preview || 
                          chain.activities.find((activity: any) => 
                            activity.message
                          )?.message ||
                          // Try to find matching user message from messages array by timestamp
                          (() => {
                            if (!chain.first_timestamp) return null
                            const chainTime = new Date(chain.first_timestamp).getTime()
                            const userMsg = messages.find((msg: Message) => {
                              if (msg.role !== 'user') return false
                              const msgTime = new Date(msg.created_at).getTime()
                              // Match if within 5 seconds
                              return Math.abs(msgTime - chainTime) < 5000
                            })
                            return userMsg?.content || null
                          })() ||
                          'No message preview available'
                          
                          // Truncate long messages
                          const displayMessage = typeof userMessage === 'string' 
                            ? (userMessage.length > 100 ? userMessage.substring(0, 100) + '...' : userMessage)
                            : 'No message preview available'
                          
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
                                  <div className="flex items-center gap-2 flex-wrap">
                                    <svg
                                      className={`w-4 h-4 text-muted-foreground transition-transform ${isChainExpanded ? 'rotate-90' : ''}`}
                                      fill="none"
                                      stroke="currentColor"
                                      viewBox="0 0 24 24"
                                    >
                                      <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
                                    </svg>
                                    <span className="font-semibold text-sm text-muted-foreground">Message:</span>
                                    <span className="text-sm font-medium">{displayMessage}</span>
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
                                  <div className="text-xs text-muted-foreground mt-1 ml-6">
                                    {displayMessage !== 'No message preview available' && displayMessage.length > 100 && (
                                      <span className="italic">(truncated)</span>
                                    )}
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
                                    // Get indentation level (0 = root, 1 = child, 2 = grandchild, etc.)
                                    const level = activity.level || 0
                                    const indentPx = level * 20  // 20px per level
                                    
                                    return (
                                      <div key={activity.id || activityIndex} className="relative">
                                        {/* Indentation container */}
                                        <div style={{ marginLeft: `${indentPx}px`, position: 'relative' }}>
                                          {/* Vertical connecting lines for nested activities */}
                                          {level > 0 && (
                                            <>
                                              {/* Vertical line from parent */}
                                              <div 
                                                className="absolute top-0 bottom-0 w-0.5 bg-muted/50" 
                                                style={{ 
                                                  left: `${-20}px`,
                                                  height: '100%'
                                                }}
                                              ></div>
                                              {/* Horizontal connector line */}
                                              <div 
                                                className="absolute top-2 w-4 h-0.5 bg-muted/50" 
                                                style={{ 
                                                  left: `${-20}px`
                                                }}
                                              ></div>
                                            </>
                                          )}
                                          
                                          {/* Timeline dot */}
                                          <div className="absolute -left-3 top-0 w-3 h-3 rounded-full bg-primary/70 border-2 border-background z-10"></div>
                                          
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
