/**
 * Chat store using Zustand for managing chat state.
 */
import { create } from 'zustand'
import type { StateCreator } from 'zustand'
import { chatAPI } from '@/lib/api'
import { getErrorMessage } from '@/lib/utils'
import { isRealMessageId } from '@/constants/messages'

export interface ChatSession {
  id: number
  title: string
  tokens_used: number
  model_used?: string | null
  created_at: string
  updated_at: string
}

export interface Message {
  id: number
  role: 'user' | 'assistant' | 'system'
  content: string
  tokens_used: number
  created_at: string
  metadata?: {
    agent_name?: string
    tool_calls?: Array<Record<string, unknown>>
    status_type?: string
    task?: string
    is_completed?: boolean
  }
  response_type?: 'answer' | 'plan_proposal'
  plan?: {
    type: string
    plan: Array<{
      action: string
      tool: string
      props: Record<string, any>
      agent: string
      query: string
    }>
    plan_index: number
    plan_total: number
  }
  clarification?: string
  raw_tool_outputs?: Array<Record<string, any>>
  status?: string  // Current task/status message (e.g., "Thinking...", "Searching documents...")
  context_usage?: {
    total_tokens: number
    context_window: number
    usage_percentage: number
    tokens_remaining: number
  }
}

interface ChatState {
  sessions: ChatSession[]
  currentSession: ChatSession | null
  messages: Message[]
  loading: boolean
  error: string | null
  
  // Actions
  loadSessions: () => Promise<void>
  createSession: (title?: string) => Promise<ChatSession | null>
  loadSession: (sessionId: number) => Promise<void>
  loadMessages: (sessionId: number) => Promise<void>
  sendMessage: (sessionId: number, content: string) => Promise<void>
  deleteSession: (sessionId: number) => Promise<void>
  deleteAllSessions: () => Promise<void>
  clearCurrentSession: () => void
  set: (state: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>)) => void
}

export const useChatStore = create<ChatState>((set: (partial: ChatState | Partial<ChatState> | ((state: ChatState) => ChatState | Partial<ChatState>)) => void, get: () => ChatState) => ({
  sessions: [],
  currentSession: null,
  messages: [],
  loading: false,
  error: null,

  loadSessions: async () => {
    set({ loading: true, error: null })
    try {
      const response = await chatAPI.getSessions()
      set({ sessions: response.data.sessions, loading: false })
    } catch (error: unknown) {
      set({ error: getErrorMessage(error, 'Failed to load sessions'), loading: false })
    }
  },

  createSession: async (title?: string) => {
    set({ loading: true, error: null })
    try {
      const response = await chatAPI.createSession({ title })
      const newSession = response.data
      set((state: ChatState) => ({
        sessions: [newSession, ...state.sessions],
        currentSession: newSession,
        loading: false,
      }))
      return newSession
    } catch (error: unknown) {
      set({ error: getErrorMessage(error, 'Failed to create session'), loading: false })
      return null
    }
  },

  loadSession: async (sessionId: number) => {
    set({ loading: true, error: null })
    try {
      const response = await chatAPI.getSession(sessionId)
      const session = response.data
      set({ currentSession: session, loading: false })
      await get().loadMessages(sessionId)
    } catch (error: unknown) {
      set({ error: getErrorMessage(error, 'Failed to load session'), loading: false })
    }
  },

  loadMessages: async (sessionId: number) => {
    try {
      const response = await chatAPI.getMessages(sessionId)
      // Map backend messages to frontend Message format, extracting ALL fields from metadata
      // This ensures all displayed data (agent_name, tool_calls, status, etc.) is restored
      const mappedMessages: Message[] = response.data.messages.map((msg: any) => {
        const metadata = msg.metadata || {}
        return {
          id: msg.id,
          role: msg.role,
          content: msg.content,
          tokens_used: msg.tokens_used,
          created_at: msg.created_at,
          metadata: {
            // Ensure agent_name is always in metadata for display
            agent_name: metadata.agent_name,
            // Ensure tool_calls array is preserved with all statuses
            tool_calls: metadata.tool_calls || [],
            // Preserve status message metadata
            status_type: metadata.status_type,
            task: metadata.task,
            is_completed: metadata.is_completed,
            // Preserve any other metadata fields
            ...metadata,
          },
          // Extract top-level fields from metadata for easier access
          response_type: metadata.response_type,
          plan: metadata.plan,
          clarification: metadata.clarification,
          raw_tool_outputs: metadata.raw_tool_outputs,
          // Note: status is transient (only during streaming), not persisted
          // Tool call statuses ARE persisted in metadata.tool_calls[].status
        }
      })
      // Filter out any temporary messages (those with negative IDs or very large IDs)
      // Real database IDs are positive and typically much smaller
      const realMessages = mappedMessages.filter((msg: Message) => isRealMessageId(msg.id))
      
      // Deduplicate messages by ID (in case backend returns duplicates)
      const seenIds = new Set<number>()
      const uniqueMessages = realMessages.filter((msg: Message) => {
        if (seenIds.has(msg.id)) {
          return false
        }
        seenIds.add(msg.id)
        return true
      })
      
      // When loading messages for a session, clear all temporary status messages
      // They are ephemeral and session-specific - should not persist across session switches
      set((state: ChatState) => {
        // Filter out any system status messages from DB (they shouldn't exist, but just in case)
        const dbMessagesWithoutStatus = uniqueMessages.filter(
          (msg: Message) => !(msg.role === 'system' && msg.metadata?.status_type === 'task_status')
        )
        
        // Don't preserve temporary status messages when loading a new session
        // They are ephemeral and should only exist during active streaming
        return { messages: dbMessagesWithoutStatus }
      })
    } catch (error: unknown) {
      set({ error: getErrorMessage(error, 'Failed to load messages') })
    }
  },

  sendMessage: async (sessionId: number, content: string) => {
    try {
      await chatAPI.sendMessage(sessionId, content)
      // Reload messages to get the new ones
      await get().loadMessages(sessionId)
    } catch (error: unknown) {
      set({ error: getErrorMessage(error, 'Failed to send message') })
      throw error
    }
  },

  deleteSession: async (sessionId: number) => {
    try {
      await chatAPI.deleteSession(sessionId)
      set((state: ChatState) => ({
        sessions: state.sessions.filter((s: ChatSession) => s.id !== sessionId),
        currentSession: state.currentSession?.id === sessionId ? null : state.currentSession,
        messages: state.currentSession?.id === sessionId ? [] : state.messages,
      }))
    } catch (error: unknown) {
      set({ error: getErrorMessage(error, 'Failed to delete session') })
    }
  },

  deleteAllSessions: async () => {
    try {
      await chatAPI.deleteAllSessions()
      set({
        sessions: [],
        currentSession: null,
        messages: [],
      })
    } catch (error: unknown) {
      set({ error: getErrorMessage(error, 'Failed to delete all sessions') })
      throw error
    }
  },

  clearCurrentSession: () => {
    set({ currentSession: null, messages: [] })
  },

  set: (updater: Partial<ChatState> | ((state: ChatState) => Partial<ChatState>)) => {
    if (typeof updater === 'function') {
      set(updater)
    } else {
      set(updater)
    }
  },
}))
