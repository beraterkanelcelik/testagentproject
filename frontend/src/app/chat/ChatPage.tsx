/**
 * ChatPage Component
 * 
 * Main chat interface orchestrating all chat-related components.
 * 
 * Architecture:
 * - Uses Temporal workflows for durability (equivalent to LangGraph's checkpointing)
 * - Uses Redis for real-time streaming (equivalent to LangGraph's streaming)
 * - Custom HITL mechanism bridges Temporal signals with LangGraph's tool approval flow
 * 
 * The review pattern follows LangGraph's interrupt() -> Command() flow:
 * 1. Tool requires approval -> Workflow pauses (interrupt equivalent)
 * 2. Frontend shows review UI with tool details
 * 3. User approves -> Sends signal (Command equivalent)
 * 4. Workflow resumes with approved tool result
 * 
 * Component Organization:
 * - ChatSidebar: Session list and management (frontend/src/components/chat/ChatSidebar.tsx)
 * - ChatHeader: Model selection and menu (frontend/src/components/chat/ChatHeader.tsx)
 * - MessageList: Messages container (frontend/src/components/chat/MessageList.tsx)
 * - MessageItem: Individual message rendering (frontend/src/components/chat/MessageItem.tsx)
 * - ToolCallItem: Tool call display with approval (frontend/src/components/chat/ToolCallItem.tsx)
 * - ChatInput: Input area with file attachments (frontend/src/components/chat/ChatInput.tsx)
 * - StatsDialog: Statistics modal (frontend/src/components/chat/StatsDialog.tsx)
 * - DeleteDialogs: Delete confirmation dialogs (frontend/src/components/chat/DeleteDialogs.tsx)
 * 
 * Hooks:
 * - useToolApproval: Tool approval logic (frontend/src/hooks/useToolApproval.ts)
 * - useSessionManagement: Session CRUD operations (frontend/src/hooks/useSessionManagement.ts)
 * 
 * Location: frontend/src/app/chat/ChatPage.tsx
 */
import React, { useState, useEffect, useRef, useCallback } from 'react'
import { useParams, useNavigate, useLocation } from 'react-router-dom'
import { useChatStore, type Message } from '@/state/useChatStore'
import { useAuthStore } from '@/state/useAuthStore'
import { Button } from '@/components/ui/button'
import { toast } from 'sonner'
import { createAgentStream, StreamEvent } from '@/lib/streaming'
import { chatAPI, agentAPI, documentAPI, modelsAPI } from '@/lib/api'
import { getErrorMessage } from '@/lib/utils'
import type { PlanProposalData } from '@/components/PlanProposal'
import { generateTempMessageId, generateTempStatusMessageId } from '@/constants/messages'

// Import extracted components
import ChatSidebar from '@/components/chat/ChatSidebar'
import ChatHeader from '@/components/chat/ChatHeader'
import MessageList from '@/components/chat/MessageList'
import ChatInput from '@/components/chat/ChatInput'
import StatsDialog from '@/components/chat/StatsDialog'
import DeleteDialogs from '@/components/chat/DeleteDialogs'
import { useToolApproval } from '@/hooks/useToolApproval'


export default function ChatPage() {
  // ============================================================================
  // ROUTING & NAVIGATION
  // ============================================================================
  const { sessionId } = useParams()
  const navigate = useNavigate()
  const location = useLocation()

  // ============================================================================
  // STATE MANAGEMENT
  // ============================================================================
  // Note: Most UI state is managed here, but some is delegated to components
  // - ChatSidebar manages its own session menu state (passed as props)
  // - ChatHeader manages its own dropdown state (internal)
  // - ChatInput manages its own plus menu state (internal)
  
  // Input state
  const [input, setInput] = useState('')
  const [sending, setSending] = useState(false)
  const [inputFocused, setInputFocused] = useState(false)
  const [attachedFiles, setAttachedFiles] = useState<File[]>([])
  const [selectedOptions, setSelectedOptions] = useState<Array<{type: string, label: string, icon?: React.ReactNode, data?: any}>>([])
  
  // UI state
  const [sidebarOpen, setSidebarOpen] = useState(true)
  const [chatsSectionOpen, setChatsSectionOpen] = useState(true)
  const [sessionMenuOpen, setSessionMenuOpen] = useState<number | null>(null)
  const [renameSessionId, setRenameSessionId] = useState<number | null>(null)
  const [renameSessionTitle, setRenameSessionTitle] = useState<string>('')
  
  // Dialog state
  const [deleteDialogOpen, setDeleteDialogOpen] = useState(false)
  const [sessionToDelete, setSessionToDelete] = useState<number | null>(null)
  const [deleteAllDialogOpen, setDeleteAllDialogOpen] = useState(false)
  const [statsDialogOpen, setStatsDialogOpen] = useState(false)
  const [stats, setStats] = useState<any>(null)
  const [loadingStats, setLoadingStats] = useState(false)
  
  // Message & streaming state
  const [waitingForResponse, setWaitingForResponse] = useState(false)
  const [waitingMessageId, setWaitingMessageId] = useState<number | null>(null)
  const [streamComplete, setStreamComplete] = useState<Set<number>>(new Set()) // Track which messages have completed streaming
  const [expandedToolCalls, setExpandedToolCalls] = useState<Set<string>>(new Set())
  const [executingPlanMessageId, setExecutingPlanMessageId] = useState<number | null>(null)
  
  // Stats dialog state
  const [expandedActivities, setExpandedActivities] = useState<string[]>([])
  const [expandedChains, setExpandedChains] = useState<string[]>([])
  
  // Model selection state
  const [selectedModel, setSelectedModel] = useState<string>('gpt-4o-mini')
  const [availableModels, setAvailableModels] = useState<Array<{id: string, name: string, description: string}>>([])
  
  // Refs for streaming
  const processedInterruptsRef = useRef<Set<string>>(new Set())
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
      // Note: ChatHeader manages its own dropdown state, so no need to close it here
      toast.success(`Model changed to ${availableModels.find(m => m.id === modelId)?.name || modelId}`)
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, 'Failed to update model'))
    }
  }

  // ============================================================================
  // STREAMING LOGIC
  // ============================================================================
  // Location: Complex streaming logic for SSE (Server-Sent Events)
  // This function handles:
  // - Creating streaming connections
  // - Processing stream events (token, update, done, error, interrupt, final, heartbeat)
  // - Managing message state during streaming
  // - Handling tool approval interrupts (HITL)
  // - Status message creation/updates
  // 
  // Note: This is the most complex part of ChatPage (~750 lines)
  // Future improvement: Could be extracted to useChatStreaming hook
  const handleSendWithMessage = useCallback(async (messageContent: string) => {
    if (!messageContent.trim() || sending || !currentSession) return

    const content = messageContent.trim()
    setSending(true)

    // Add user message immediately
    const tempUserMessageId = generateTempMessageId()
    const userMessage = {
      id: tempUserMessageId,
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

      {
        // Clear processed interrupts for new message stream
        processedInterruptsRef.current.clear()
        // Also clear any stale approving states from previous message
        setApprovingToolCalls(new Set())
        
        // Clear any old temporary status messages before starting a new stream
        // They are ephemeral and should not persist across different streams
        set((state: { messages: Message[] }) => ({
          messages: state.messages.filter(
            (msg: Message) => !(msg.id < 0 && msg.role === 'system' && msg.metadata?.status_type === 'task_status')
          )
        }))
        
        // Create streaming message placeholder
        const assistantMessageId = Date.now() + 1
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
        
        console.log(`[FRONTEND] [STREAM_START] Starting agent stream session=${currentSession.id} message_preview=${content.substring(0, 50)}...`)
        
        const stream = createAgentStream(
          currentSession.id,
          content,
          token,
          (event: StreamEvent) => {
            const eventType = event.type
            eventTypeCounts[eventType] = (eventTypeCounts[eventType] || 0) + 1
            
            // Log critical human-in-the-loop events (aligned with LangGraph interrupt pattern)
            // Reference: https://docs.langchain.com/oss/python/langgraph/use-functional-api#review-tool-calls
            // This is the equivalent of LangGraph's interrupt() in our Temporal + Redis architecture
            if (eventType === 'update' && event.data?.type === 'tool_approval_required') {
              console.log(`[HITL] [REVIEW] Stream event: tool_approval_required (interrupt equivalent) session=${currentSession.id}`, event.data)
            }
            
            // Handle message_saved event to update temporary IDs with real DB IDs
            if (eventType === 'message_saved') {
              const savedData = event.data || {}
              const role = savedData.role
              const dbId = savedData.db_id
              const sessionId = savedData.session_id
              
              if (sessionId === currentSession.id && dbId) {
                set((state: { messages: Message[] }) => {
                  // Find temporary message by role and update its ID
                  // For user messages, find the most recent user message with a temporary ID
                  // For assistant messages, find the message with the temporary assistantMessageId
                  const updatedMessages = state.messages.map((msg: Message) => {
                    if (role === 'user' && msg.role === 'user' && msg.id === tempUserMessageId) {
                      return { ...msg, id: dbId }
                    } else if (role === 'assistant' && msg.role === 'assistant' && msg.id === assistantMessageId) {
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
              
              // Log first token and periodic token batches
              if (tokenBatchCount === 1) {
                const timeToFirstToken = Date.now() - streamStartTime
                console.log(`[FRONTEND] [STREAM] First token received session=${currentSession.id} time_to_first_token=${timeToFirstToken}ms`)
              } else if (tokenBatchCount % 50 === 0) {
                const elapsed = Date.now() - streamStartTime
                console.log(`[FRONTEND] [STREAM] Token batch: ${tokenBatchCount} tokens received session=${currentSession.id} elapsed=${elapsed}ms`)
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
              
              // Log update events with key information
              if (updateData.agent_name) {
                console.log(`[FRONTEND] [UPDATE] Agent name updated: agent=${updateData.agent_name} session=${currentSession.id}`)
              }
              if (updateData.tool_calls && Array.isArray(updateData.tool_calls)) {
                const toolCallCount = updateData.tool_calls.length
                const pendingCount = updateData.tool_calls.filter((tc: any) => tc.status === 'pending').length
                console.log(`[FRONTEND] [UPDATE] Tool calls updated: total=${toolCallCount} pending=${pendingCount} session=${currentSession.id}`)
              }
              
              // Human-in-the-Loop Tool Review (aligned with LangGraph best practices)
              // Reference: https://docs.langchain.com/oss/python/langgraph/use-functional-api#review-tool-calls
              // This handles the "interrupt" equivalent in our Temporal + Redis architecture
              // When a tool requires approval, the workflow pauses and waits for human review
              if (updateData.type === 'tool_approval_required' && updateData.tool_info) {
                const toolInfo = updateData.tool_info
                console.log(`[HITL] [REVIEW] Received tool_approval_required event (interrupt equivalent): tool=${toolInfo.tool} tool_call_id=${toolInfo.tool_call_id} session=${currentSession?.id} args=`, toolInfo.args)
                
                // Update the assistant message to mark the tool as pending
                set((state: { messages: Message[] }) => {
                  const currentMessage = state.messages.find((msg: Message) => msg.id === assistantMessageId)
                  if (!currentMessage) {
                    console.warn(`[HITL] Could not find assistant message with id=${assistantMessageId} for tool_approval_required event`)
                    return state
                  }
                  
                  const existingToolCalls = currentMessage.metadata?.tool_calls || []
                  const toolCallExists = existingToolCalls.some((tc: any) => 
                    (tc.id === toolInfo.tool_call_id) || 
                    (tc.name === toolInfo.tool || tc.tool === toolInfo.tool)
                  )
                  
                  if (!toolCallExists) {
                    // Add new tool call with pending status
                    console.log(`[HITL] Adding new pending tool call to message: tool=${toolInfo.tool} tool_call_id=${toolInfo.tool_call_id}`)
                    const newToolCall = {
                      id: toolInfo.tool_call_id,
                      name: toolInfo.tool,
                      tool: toolInfo.tool,
                      args: toolInfo.args || {},
                      status: 'pending',
                      requires_approval: true
                    }
                    
                    return {
                      messages: state.messages.map((msg: Message) =>
                        msg.id === assistantMessageId
                          ? {
                              ...msg,
                              metadata: {
                                ...msg.metadata,
                                tool_calls: [...existingToolCalls, newToolCall]
                              }
                            }
                          : msg
                      ),
                    }
                  } else {
                    // Update existing tool call to pending (for review - aligned with LangGraph pattern)
                    console.log(`[HITL] [REVIEW] Updating existing tool call to pending for review: tool=${toolInfo.tool} tool_call_id=${toolInfo.tool_call_id}`)
                    return {
                      messages: state.messages.map((msg: Message) =>
                        msg.id === assistantMessageId
                          ? {
                              ...msg,
                              metadata: {
                                ...msg.metadata,
                                tool_calls: existingToolCalls.map((tc: any) => {
                                  if ((tc.id === toolInfo.tool_call_id) || 
                                      (tc.name === toolInfo.tool || tc.tool === toolInfo.tool)) {
                                    return {
                                      ...tc,
                                      id: toolInfo.tool_call_id,
                                      status: 'pending',
                                      requires_approval: true
                                    }
                                  }
                                  return tc
                                })
                              }
                            }
                          : msg
                      ),
                    }
                  }
                })
              }

              // Handle task status updates - create/update system status messages in real-time
              // BUT: Stop updating status messages once answer tokens start arriving
              if (updateData.task && updateData.status) {
                set((state: { messages: Message[] }) => {
                  // Check if assistant message already has content (tokens have started arriving)
                  const assistantMsg = state.messages.find((msg: Message) => msg.id === assistantMessageId)
                  const hasAnswerTokens = assistantMsg?.content && assistantMsg.content.trim().length > 0
                  
                  // If answer tokens have started, don't update status messages anymore
                  // They should remain frozen at their last state
                  if (hasAnswerTokens) {
                    return state
                  }
                  
                  // Check if status message already exists for this task (check both temp and DB messages)
                  const existingStatusMsg = state.messages.find(
                    (msg: Message) => 
                      msg.role === 'system' && 
                      msg.metadata?.status_type === 'task_status' &&
                      msg.metadata?.task === updateData.task
                  )
                  
                  if (existingStatusMsg) {
                    // Update existing status message (present -> past tense)
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
                    const tempId = generateTempStatusMessageId()
                    const newStatusMessage: Message = {
                      id: tempId,
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
                
                // Handle tool calls during streaming - they appear immediately as they're added
                // Tool calls are shown in chronological order as events come in
                let updatedToolCalls = currentMessage.metadata?.tool_calls || []
                
                if (updateData.tool_calls) {
                  // Direct tool_calls array update - tool calls appear immediately
                  const pendingTools = (updateData.tool_calls || []).filter((tc: any) => tc.status === 'pending' && tc.requires_approval)
                  if (pendingTools.length > 0) {
                    console.log(`[HITL] Received tool_calls with ${pendingTools.length} pending tools requiring approval:`, pendingTools.map((tc: any) => ({ tool: tc.name || tc.tool, tool_call_id: tc.id, status: tc.status })))
                  }
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
              // Mark stream as complete for this message
              // Tool calls are already visible (shown immediately as they come in)
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
                          ...(doneData.context_usage && { context_usage: doneData.context_usage }),
                          // Extract agent_name from done event (backend sends "agent" key)
                          ...(doneData.agent && {
                            metadata: {
                              ...msg.metadata,
                              agent_name: doneData.agent,
                            },
                          }),
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
            } else if (eventType === 'interrupt') {
              // LangGraph native interrupt pattern - workflow paused for approval
              // Connection remains open but with shorter timeout (5 min) for scalability
              // This balances resource usage with UX (no reconnection needed)
              console.log(`[HITL] [INTERRUPT] Workflow interrupted - connection will timeout after 5 minutes if no resume session=${currentSession.id}`)
              
              // Extract interrupt payload - handle multiple formats from backend
              const interruptData = event.data || event.interrupt
              let interruptValue: any = null
              
              // Handle different interrupt data formats:
              // 1. Array format: [{value: {...}, resumable: true, ns: [...]}]
              // 2. Tuple format: (Interrupt(value={...}, id='...'),) - Python tuple serialized
              // 3. Direct Interrupt object: {value: {...}, id: '...'}
              if (interruptData) {
                if (Array.isArray(interruptData) && interruptData.length > 0) {
                  // Array format - extract value from first element
                  const firstItem = interruptData[0]
                  if (firstItem?.value) {
                    interruptValue = firstItem.value
                  } else if (firstItem?.type === 'tool_approval') {
                    // Direct value in array
                    interruptValue = firstItem
                  }
                } else if (typeof interruptData === 'object') {
                  // Direct object - could be Interrupt object with .value or direct payload
                  if (interruptData.value) {
                    interruptValue = interruptData.value
                  } else if (interruptData.type === 'tool_approval') {
                    interruptValue = interruptData
                  }
                }
              }
              
              if (interruptValue && interruptValue.type === 'tool_approval') {
                const tools = interruptValue.tools || []
                
                // Generate unique interrupt ID from tools to prevent duplicate processing
                const interruptId = JSON.stringify(tools.map((t: any) => t.tool_call_id || t.id).sort())
                
                // Deduplicate - prevent processing same interrupt twice
                if (processedInterruptsRef.current.has(interruptId)) {
                  console.log(`[HITL] [INTERRUPT] Ignoring duplicate interrupt: interruptId=${interruptId} session=${currentSession.id}`)
                  return
                }
                processedInterruptsRef.current.add(interruptId)
                
                console.log(`[HITL] [INTERRUPT] Received interrupt with ${tools.length} tools requiring approval:`, tools.map((t: any) => ({ tool: t.tool, tool_call_id: t.tool_call_id })))
                
                // Mark message as ready to show tool calls (even though stream isn't complete)
                // This ensures the approval UI is visible immediately
                setStreamComplete(prev => new Set(prev).add(assistantMessageId))
                
                // Ensure assistant message exists - create it if it doesn't
                set((state: { messages: Message[] }) => {
                  let currentMessage = state.messages.find((msg: Message) => msg.id === assistantMessageId)
                  
                  // Create assistant message if it doesn't exist
                  if (!currentMessage) {
                    console.log(`[HITL] [INTERRUPT] Creating assistant message for interrupt: session=${currentSession.id}`)
                    const newMessage: Message = {
                      id: assistantMessageId,
                      role: 'assistant',
                      content: '',
                      tokens_used: 0,
                      created_at: new Date().toISOString(),
                      metadata: {
                        agent_name: 'assistant',
                        tool_calls: []
                      }
                    }
                    return {
                      messages: [...state.messages, newMessage]
                    }
                  }
                  
                  // Update existing message with tool calls requiring approval
                  const existingToolCalls = currentMessage.metadata?.tool_calls || []
                  const updatedToolCalls = [...existingToolCalls]
                  
                  // Add or update tool calls from interrupt
                  for (const toolInfo of tools) {
                    const existingIndex = updatedToolCalls.findIndex((tc: any) => 
                      tc.id === toolInfo.tool_call_id || 
                      (tc.name === toolInfo.tool || tc.tool === toolInfo.tool)
                    )
                    
                    const toolCallData = {
                      id: toolInfo.tool_call_id,
                      name: toolInfo.tool,
                      tool: toolInfo.tool,
                      args: toolInfo.args || {},
                      status: 'pending' as const,
                      requires_approval: true
                    }
                    
                    if (existingIndex >= 0) {
                      updatedToolCalls[existingIndex] = { ...updatedToolCalls[existingIndex], ...toolCallData }
                    } else {
                      updatedToolCalls.push(toolCallData)
                    }
                  }
                  
                  return {
                    messages: state.messages.map((msg: Message) =>
                      msg.id === assistantMessageId
                        ? {
                            ...msg,
                            metadata: {
                              ...msg.metadata,
                              tool_calls: updatedToolCalls
                            }
                          }
                        : msg
                    ),
                  }
                })
              } else {
                console.warn(`[HITL] [INTERRUPT] Could not parse interrupt data:`, interruptData)
              }
              
              // Don't set sending=false here - we're waiting for resume
              // Connection stays open to receive final response after resume
            } else if (eventType === 'heartbeat') {
              // Heartbeat event to keep connection alive (scalability best practice)
              // Prevents idle connection timeouts
              // Log periodically to track connection health
              const elapsed = Date.now() - streamStartTime
              if (elapsed % 60000 < 1000) { // Log roughly every minute
                console.log(`[FRONTEND] [HEARTBEAT] Connection alive session=${currentSession.id} elapsed=${Math.floor(elapsed / 1000)}s`)
              }
            } else if (eventType === 'final') {
              // Final event contains the complete response after approval
              const finalData = event.data || event.response || {}
              const duration = Date.now() - streamStartTime
              console.log(`[FRONTEND] [STREAM] Final event received session=${currentSession.id} duration=${duration}ms has_response=${!!finalData.reply} response_length=${finalData.reply?.length || 0}`)
              
              // Update message with final response if present
              if (finalData.reply && assistantMessageId) {
                set((state: { messages: Message[] }) => ({
                  messages: state.messages.map((msg: Message) =>
                    msg.id === assistantMessageId
                      ? { ...msg, content: finalData.reply }
                      : msg
                  ),
                }))
              }
            } else if (eventType === 'agent_start') {
              const agentData = event.data || {}
              console.log(`[FRONTEND] [STREAM] Agent started: agent=${agentData.agent_name || 'unknown'} session=${currentSession.id}`)
            } else {
              // Handle unknown event types gracefully
              console.debug(`[FRONTEND] Unknown event type received session=${currentSession.id} type=${eventType}`, event)
            }
          },
          (error: Error) => {
            const duration = Date.now() - streamStartTime
            console.error(`[FRONTEND] [STREAM_ERROR] Stream connection error session=${currentSession.id} duration=${duration}ms error=${error.message} event_counts=${JSON.stringify(eventTypeCounts)}`, error)
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
            setSending(false)
            setWaitingForResponse(false)
            setWaitingMessageId(null)
          }
        )

        streamRef.current = stream
      }
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, 'Failed to send message'))
      setSending(false)
    }
  }, [currentSession, sending, loadMessages])

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



  // ============================================================================
  // EVENT HANDLERS
  // ============================================================================
  
  // Session Management Handlers
  // Location: These handlers manage session CRUD operations
  // Note: Could be extracted to useSessionManagement hook in the future
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

  // Message Sending Handler
  // Location: Main message sending logic - calls handleSendWithMessage
  // Note: handleSendWithMessage contains the complex streaming logic (lines ~191-944)
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
    // Note: ChatHeader manages its own menu state, so no need to close it here
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

  // Load chat statistics
  // Location: Statistics loading logic - used by StatsDialog component
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

  }

  const handleRemoveFile = (index: number) => {
    setAttachedFiles((prev) => prev.filter((_, i) => i !== index))
  }

  // Remove selected option badge
  // Location: Removes badges from selected options (used by ChatInput component)
  const removeSelectedOption = (index: number) => {
    const option = selectedOptions[index]
    setSelectedOptions((prev) => prev.filter((_, i) => i !== index))
    
    // If it was a file option, also remove from attachedFiles
    if (option.type === 'files' && option.data) {
      setAttachedFiles((prev) => prev.filter((_, i) => !option.data.includes(i)))
    }
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

      {
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
                          ...(doneData.context_usage && { context_usage: doneData.context_usage }),
                          // Extract agent_name from done event (backend sends "agent" key)
                          ...(doneData.agent && {
                            metadata: {
                              ...msg.metadata,
                              agent_name: doneData.agent,
                            },
                          }),
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
      }
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, 'Failed to execute plan'))
      setSending(false)
      setExecutingPlanMessageId(null)
    }
  }, [currentSession, sending, loadMessages])

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

  // ============================================================================
  // CUSTOM HOOKS
  // ============================================================================
  // Tool Approval Hook
  // Location: frontend/src/hooks/useToolApproval.ts
  // Handles tool approval logic for human-in-the-loop workflows
  const { handleApproveTool, handleRejectTool, approvingToolCalls, setApprovingToolCalls } = useToolApproval({
    currentSession,
    updateMessages: (updater) => {
      set((state: { messages: Message[] }) => ({ messages: updater(state.messages) }))
    },
    loadMessages,
  })

  // ============================================================================
  // RENDER
  // ============================================================================
  // Component Structure:
  // 1. ChatSidebar - Left sidebar with session list (collapsible)
  // 2. Main Chat Area:
  //    a. ChatHeader - Top bar with model selection and menu
  //    b. MessageList - Scrollable messages area (or empty state with ChatInput)
  //    c. ChatInput - Bottom input area (only when messages exist)
  // 3. DeleteDialogs - Delete confirmation modals
  // 4. StatsDialog - Statistics modal with activity timeline
  return (
    <>
    <div className="flex h-[calc(100vh-120px)] sm:h-[calc(100vh-145px)] bg-background">
      {/* Sidebar Component - Handles session list, new chat, rename, delete */}
      {/* Location: frontend/src/components/chat/ChatSidebar.tsx */}
      <ChatSidebar
        sidebarOpen={sidebarOpen}
        sessions={sessions}
        currentSession={currentSession}
        loading={loading}
        chatsSectionOpen={chatsSectionOpen}
        onToggleChatsSection={() => setChatsSectionOpen(!chatsSectionOpen)}
        onNewChat={handleNewChat}
        onSelectSession={handleSelectSession}
        onRenameSession={handleRenameSession}
        onDeleteSession={handleDeleteSession}
        renameSessionId={renameSessionId}
        renameSessionTitle={renameSessionTitle}
        setRenameSessionTitle={setRenameSessionTitle}
        onSaveRename={handleSaveRename}
        onCancelRename={handleCancelRename}
        sessionMenuOpen={sessionMenuOpen}
        setSessionMenuOpen={setSessionMenuOpen}
        onClose={() => setSidebarOpen(false)}
      />

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {!currentSession ? (
          // No session selected - show welcome screen
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
            {/* Header Component - Model selection and menu */}
            {/* Location: frontend/src/components/chat/ChatHeader.tsx */}
            <ChatHeader
              sidebarOpen={sidebarOpen}
              onToggleSidebar={() => setSidebarOpen(!sidebarOpen)}
              selectedModel={selectedModel}
              availableModels={availableModels}
              onModelChange={handleModelChange}
              onOpenStats={handleOpenStats}
              onDeleteChat={handleDeleteCurrentChat}
              hasCurrentSession={!!currentSession}
              messages={messages}
            />

            {/* Messages Area */}
            <div className="flex-1 overflow-y-auto">
              {messages.length === 0 ? (
                // Empty state - show centered input with welcome message
                <ChatInput
                  input={input}
                  setInput={setInput}
                  attachedFiles={attachedFiles}
                  onFileSelect={handleFileSelect}
                  selectedOptions={selectedOptions}
                  onRemoveOption={removeSelectedOption}
                  onSend={handleSend}
                  sending={sending}
                  inputFocused={inputFocused}
                  setInputFocused={setInputFocused}
                  error={error}
                  isEmptyState={true}
                />
              ) : (
                // Messages List Component - Renders all messages
                // Location: frontend/src/components/chat/MessageList.tsx
                <MessageList
                  messages={messages}
                  streamComplete={streamComplete}
                  expandedToolCalls={expandedToolCalls}
                  onToggleToolCall={(toolCallId) => {
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
                  onApproveTool={async (messageId, toolCall, toolCallId, toolName) => {
                    await handleApproveTool(messageId, toolCall, toolCallId, toolName)
                  }}
                  onRejectTool={async (messageId, toolCall, toolCallId, toolName) => {
                    await handleRejectTool(messageId, toolCall, toolCallId, toolName)
                  }}
                  approvingToolCalls={approvingToolCalls}
                  currentSession={currentSession}
                  onPlanApproval={handlePlanApproval}
                  onPlanRejection={handlePlanRejection}
                  executingPlanMessageId={executingPlanMessageId}
                  userEmail={user?.email}
                />
              )}
            </div>

            {/* Input Area - Only show when messages exist */}
            {/* Location: frontend/src/components/chat/ChatInput.tsx */}
            {messages.length > 0 && (
              <ChatInput
                input={input}
                setInput={setInput}
                attachedFiles={attachedFiles}
                onFileSelect={handleFileSelect}
                selectedOptions={selectedOptions}
                onRemoveOption={removeSelectedOption}
                onSend={handleSend}
                sending={sending}
                inputFocused={inputFocused}
                setInputFocused={setInputFocused}
                error={error}
                isEmptyState={false}
              />
            )}
          </>
        )}
      </div>
    </div>

    {/* Delete Confirmation Dialogs */}
    {/* Location: frontend/src/components/chat/DeleteDialogs.tsx */}
    <DeleteDialogs
      deleteDialogOpen={deleteDialogOpen}
      deleteAllDialogOpen={deleteAllDialogOpen}
      sessionToDelete={sessionToDelete}
      sessionCount={sessions.length}
      onConfirmDelete={confirmDeleteSession}
      onCancelDelete={cancelDeleteSession}
      onConfirmDeleteAll={confirmDeleteAllSessions}
      onCancelDeleteAll={cancelDeleteAllSessions}
    />

    {/* Stats Dialog */}
    {/* Location: frontend/src/components/chat/StatsDialog.tsx */}
    <StatsDialog
      open={statsDialogOpen}
      onClose={() => setStatsDialogOpen(false)}
      stats={stats}
      loading={loadingStats}
      messages={messages}
      expandedChains={expandedChains}
      expandedActivities={expandedActivities}
      onToggleChain={(traceId) => {
        setExpandedChains((prev) => 
          prev.includes(traceId) 
            ? prev.filter(id => id !== traceId)
            : [...prev, traceId]
        )
      }}
      onToggleActivity={(activityKey) => {
        setExpandedActivities((prev) => 
          prev.includes(activityKey) 
            ? prev.filter(key => key !== activityKey)
            : [...prev, activityKey]
        )
      }}
    />
    </>
  )
}
