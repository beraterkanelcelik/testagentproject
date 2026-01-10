/**
 * Chat store using Zustand for managing chat state.
 */
import { create } from 'zustand'
import type { StateCreator } from 'zustand'
import { chatAPI } from '@/lib/api'
import { getErrorMessage } from '@/lib/utils'

export interface ChatSession {
  id: number
  title: string
  tokens_used: number
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
      set({ messages: response.data.messages })
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
