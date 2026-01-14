/**
 * ChatInput Component
 * 
 * Input area for chat messages with file attachments and options.
 * 
 * Features:
 * - Auto-resizing textarea
 * - File attachment support
 * - Plus menu (file selection)
 * - Selected options badges
 * - Send button
 * - Empty state variant (centered with welcome message)
 * 
 * Location: frontend/src/components/chat/ChatInput.tsx
 */

import React, { useRef, useState } from 'react'

interface SelectedOption {
  type: string
  label: string
  icon?: React.ReactNode
  data?: any
}

interface ChatInputProps {
  /** Input value */
  input: string
  /** Callback when input changes */
  setInput: (value: string) => void
  /** Attached files */
  attachedFiles: File[]
  /** Callback when files are selected */
  onFileSelect: (e: React.ChangeEvent<HTMLInputElement>) => void
  /** Selected options (for badges) */
  selectedOptions: SelectedOption[]
  /** Callback to remove a selected option */
  onRemoveOption: (index: number) => void
  /** Callback when send is clicked */
  onSend: () => void
  /** Whether message is being sent */
  sending: boolean
  /** Whether input is focused */
  inputFocused: boolean
  /** Callback when input focus changes */
  setInputFocused: (value: boolean) => void
  /** Error message to display */
  error?: string | null
  /** Whether to show empty state (centered with welcome message) */
  isEmptyState?: boolean
}

/**
 * ChatInput - Input area for chat messages
 * 
 * This component provides:
 * 1. Auto-resizing textarea (up to 200px height)
 * 2. File input (hidden, triggered via plus menu)
 * 3. Plus menu with:
 *    - File selection option
 * 4. Selected options badges (removable)
 * 5. Send button (disabled when empty and no files)
 * 
 * Supports two variants:
 * - Empty state: Centered with "What can I help with?" message
 * - Normal state: Bottom-aligned input area
 */
export default function ChatInput({
  input,
  setInput,
  attachedFiles,
  onFileSelect,
  selectedOptions,
  onRemoveOption,
  onSend,
  sending,
  inputFocused,
  setInputFocused,
  error,
  isEmptyState = false,
}: ChatInputProps) {
  const [plusMenuOpen, setPlusMenuOpen] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  const handleFileSelectionFromPlus = () => {
    fileInputRef.current?.click()
    setPlusMenuOpen(false)
  }

  const handleTextareaChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    setInput(e.target.value)
    // Auto-resize textarea
    e.target.style.height = 'auto'
    e.target.style.height = `${Math.min(e.target.scrollHeight, 200)}px`
  }

  const handleKeyDown = (e: { key: string; shiftKey: boolean; preventDefault: () => void }) => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault()
      onSend()
    }
  }

  const inputContent = (
    <>
      {/* Error Message */}
      {error && (
        <div className="mb-3 p-3 bg-destructive/10 text-destructive text-sm rounded-lg">
          {error}
        </div>
      )}
      
      {/* Selected Options Badges */}
      {selectedOptions.length > 0 && (
        <div className={`mb-3 flex flex-wrap gap-2 ${isEmptyState ? 'justify-center' : ''}`}>
          {selectedOptions.map((option, idx) => (
            <div
              key={idx}
              className="inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full bg-primary/10 text-primary text-sm"
            >
              {option.icon}
              <span>{option.label}</span>
              <button
                onClick={() => onRemoveOption(idx)}
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
          onSend()
        }}
        className="relative"
      >
        <div className="relative flex flex-col bg-background border rounded-2xl shadow-sm">
          {/* Textarea Area */}
          <textarea
            value={input}
            onChange={handleTextareaChange}
            onFocus={() => setInputFocused(true)}
            onBlur={() => setInputFocused(false)}
            onKeyDown={handleKeyDown}
            placeholder={isEmptyState ? "Ask anything" : "Message..."}
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
              onChange={onFileSelect}
              className="hidden"
              disabled={sending}
            />

            {/* Send Button */}
            <button
              type="submit"
              onClick={onSend}
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
    </>
  )

  if (isEmptyState) {
    return (
      <div className="flex items-center justify-center min-h-[60vh]">
        <div className="w-full max-w-2xl px-4">
          <div className="text-center mb-8">
            <h2 className="text-4xl font-light text-foreground/80 mb-2">
              What can I help with?
            </h2>
          </div>
          <div className="relative">
            {inputContent}
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="bg-background/95 backdrop-blur supports-[backdrop-filter]:bg-background/60 animate-slide-up">
      <div className="max-w-3xl mx-auto px-4 pt-2 pb-1">
        {inputContent}
      </div>
    </div>
  )
}
