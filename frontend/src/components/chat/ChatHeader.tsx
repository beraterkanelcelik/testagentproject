/**
 * ChatHeader Component
 * 
 * Header bar for the chat interface with model selection and menu.
 * 
 * Features:
 * - Sidebar toggle button
 * - Model selection dropdown
 * - More options menu (stats, delete chat)
 * 
 * Location: frontend/src/components/chat/ChatHeader.tsx
 */

import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import type { Message } from '@/state/useChatStore'

interface Model {
  id: string
  name: string
  description: string
}

interface ChatHeaderProps {
  /** Whether sidebar is open */
  sidebarOpen: boolean
  /** Callback to toggle sidebar */
  onToggleSidebar: () => void
  /** Currently selected model ID */
  selectedModel: string
  /** Available models */
  availableModels: Model[]
  /** Callback when model changes */
  onModelChange: (modelId: string) => Promise<void>
  /** Callback to open stats dialog */
  onOpenStats: () => void
  /** Callback to delete current chat */
  onDeleteChat: () => void
  /** Whether current session exists */
  hasCurrentSession: boolean
  /** Messages for context usage display */
  messages: Message[]
}

/**
 * ChatHeader - Header bar for chat interface
 * 
 * This component provides:
 * 1. Sidebar toggle button
 * 2. Model selection dropdown (shows current model, allows switching)
 * 3. More options menu (three dots) with:
 *    - Statistics option
 *    - Delete chat option (if session exists)
 */
export default function ChatHeader({
  sidebarOpen,
  onToggleSidebar,
  selectedModel,
  availableModels,
  onModelChange,
  onOpenStats,
  onDeleteChat,
  hasCurrentSession,
  messages,
}: ChatHeaderProps) {
  const [modelDropdownOpen, setModelDropdownOpen] = useState(false)
  const [headerMoreMenuOpen, setHeaderMoreMenuOpen] = useState(false)

  const selectedModelName = availableModels.find(m => m.id === selectedModel)?.name || selectedModel
  
  // Get context usage from latest assistant message
  const latestAssistantMessage = messages
    .filter(msg => msg.role === 'assistant')
    .slice(-1)[0]
  const contextUsage = latestAssistantMessage?.context_usage

  return (
    <div className="px-4 py-1 flex items-center justify-between bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="flex items-center gap-2">
        {/* Sidebar Toggle */}
        <button
          onClick={onToggleSidebar}
          className="p-1 hover:bg-muted rounded-md transition-colors"
          aria-label="Toggle sidebar"
        >
          <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 6h16M4 12h16M4 18h16" />
          </svg>
        </button>
        
        {/* Model Selection Dropdown */}
        <div className="relative flex items-center gap-2">
          <div className="flex flex-col">
            <button
              onClick={() => setModelDropdownOpen(!modelDropdownOpen)}
              className="flex items-center gap-1 px-2 py-0.5 hover:bg-muted rounded-md transition-colors text-sm"
            >
              <span className="font-medium">
                {selectedModelName}
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
            {/* Context Usage Display */}
            {contextUsage && (
              <div className="text-xs text-muted-foreground px-2">
                {contextUsage.total_tokens.toLocaleString()} / {contextUsage.context_window.toLocaleString()} tokens ({contextUsage.usage_percentage}%)
              </div>
            )}
          </div>
          
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
                    onClick={() => {
                      onModelChange(model.id)
                      setModelDropdownOpen(false)
                    }}
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
      
      {/* More Options Menu */}
      <div className="flex items-center gap-1">
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
                    onOpenStats()
                    setHeaderMoreMenuOpen(false)
                  }}
                  className="w-full flex items-center gap-2 px-3 py-2 hover:bg-muted rounded-md transition-colors text-left text-sm"
                >
                  <svg className="w-4 h-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
                  </svg>
                  <span>Statistics</span>
                </button>
                {hasCurrentSession && (
                  <button
                    onClick={() => {
                      onDeleteChat()
                      setHeaderMoreMenuOpen(false)
                    }}
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
  )
}
