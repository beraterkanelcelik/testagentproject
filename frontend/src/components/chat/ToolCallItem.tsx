/**
 * ToolCallItem Component
 * 
 * Displays a single tool call with collapsible details and approval UI.
 * 
 * Features:
 * - Collapsible tool call display
 * - Tool arguments, results, and status
 * - Document reference extraction and display
 * - Human-in-the-loop approval UI for pending tools
 * - Status badges (pending, executing, completed, error)
 * 
 * Location: frontend/src/components/chat/ToolCallItem.tsx
 */

import React from 'react'
import { useNavigate } from 'react-router-dom'
import { Button } from '@/components/ui/button'
import JsonViewer from '@/components/JsonViewer'

export interface ToolCallItemProps {
  /** Tool call data */
  toolCall: any
  /** Unique identifier for this tool call */
  toolCallId: string
  /** Whether the tool call is expanded */
  isExpanded: boolean
  /** Callback to toggle expansion */
  onToggle: () => void
  /** Callback when user approves the tool call */
  onApprove: () => Promise<void>
  /** Callback when user rejects the tool call */
  onReject?: () => Promise<void>
  /** Set of tool call IDs currently being approved */
  approvingToolCalls: Set<string>
  /** Current session (required for approval) */
  currentSession: { id: number } | null
  /** Whether there's a subsequent assistant message with content (tools were already executed) */
  hasSubsequentAnswer?: boolean
}

/**
 * ToolCallItem - Individual tool call display component
 * 
 * This component renders:
 * 1. Collapsible header with tool name and document count
 * 2. Expanded details showing:
 *    - Tool arguments
 *    - Document references (extracted from RAG results)
 *    - Tool result preview
 *    - Execution status
 *    - Approval UI (for pending tools requiring approval)
 *    - Raw output (for plan execution)
 * 
 * The approval UI follows LangGraph's human-in-the-loop pattern:
 * - Shows warning banner for tools requiring approval
 * - Provides "Approve & Execute" button
 * - Handles approval state management
 */
export default function ToolCallItem({
  toolCall,
  toolCallId,
  isExpanded,
  onToggle,
  onApprove,
  onReject,
  approvingToolCalls,
  currentSession,
  hasSubsequentAnswer = false,
}: ToolCallItemProps) {
  const navigate = useNavigate()
  const toolName = toolCall.tool || toolCall.name || 'Tool'
  
  // Extract document references from RAG tool results
  // Looks for patterns like [Document Title, page X] or [Document Title]
  const extractDocReferences = (result: string): Array<{ title: string; page?: number }> => {
    const docRefs: Array<{ title: string; page?: number }> = []
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
  const isApproving = approvingToolCalls.has(toolCall.id || toolCallId)
  
  // Determine if approval UI should be shown
  // With backend fix, status should always be properly set, but we check both status and results as safety net
  const isAwaitingApproval = toolCall.status === 'awaiting_approval' || toolCall.status === 'pending'
  const isAlreadyProcessed = toolCall.status === 'completed' || 
                             toolCall.status === 'executing' || 
                             toolCall.status === 'error' ||
                             toolCall.status === 'rejected' ||
                             toolCall.status === 'approved'
  const hasResult = !!(toolCall.result || toolCall.output)
  
  // Show approval UI only for tools that:
  // 1. Are awaiting approval (status="awaiting_approval" or "pending")
  // 2. Are not already processed (status check - primary)
  // 3. Don't have results yet (safety net - in case status isn't set but tool was executed)
  // 4. Don't have a subsequent answer (if there's a later message with content, tools were already executed)
  // 5. Require approval and have a valid session
  const shouldShowReview = isAwaitingApproval && 
                          !isAlreadyProcessed &&
                          !hasResult &&
                          !hasSubsequentAnswer &&
                          (toolCall.requires_approval === true || toolCall.status === 'awaiting_approval') && 
                          !!currentSession

  return (
    <div className="border rounded-lg bg-muted/30 overflow-hidden">
      {/* Header with approve/reject buttons for pending tools */}
      <div className="w-full px-3 py-2 flex items-center justify-between">
        <div className="flex items-center gap-2 flex-1">
          <svg className="w-4 h-4 text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M10.325 4.317c.426-1.756 2.924-1.756 3.35 0a1.724 1.724 0 002.573 1.066c1.543-.94 3.31.826 2.37 2.37a1.724 1.724 0 001.065 2.572c1.756.426 1.756 2.924 0 3.35a1.724 1.724 0 00-1.066 2.573c.94 1.543-.826 3.31-2.37 2.37a1.724 1.724 0 00-2.572 1.065c-.426 1.756-2.924 1.756-3.35 0a1.724 1.724 0 00-2.573-1.066c-1.543.94-3.31-.826-2.37-2.37a1.724 1.724 0 00-1.065-2.572c-1.756-.426-1.756-2.924 0-3.35a1.724 1.724 0 001.066-2.573c-.94-1.543.826-3.31 2.37-2.37.996.608 2.296.07 2.572-1.065z" />
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 12a3 3 0 11-6 0 3 3 0 016 0z" />
          </svg>
          <span className="text-sm font-medium">{toolName}</span>
          {toolCall.args && typeof toolCall.args === 'object' && Object.keys(toolCall.args).length > 0 && (
            <span className="text-xs text-muted-foreground">
              ({JSON.stringify(toolCall.args).substring(0, 50)}...)
            </span>
          )}
          {docReferences.length > 0 && (
            <span className="text-xs text-muted-foreground">
              ({docReferences.length} {docReferences.length === 1 ? 'document' : 'documents'})
            </span>
          )}
        </div>
        
        {/* Approve/Reject buttons - show directly in header for pending tools */}
        {shouldShowReview ? (
          <div className="flex items-center gap-1.5">
            <button
              onClick={(e) => {
                e.stopPropagation()
                onApprove()
              }}
              disabled={isApproving}
              className="h-7 px-3 rounded-md border border-green-200 dark:border-green-800 bg-green-50 dark:bg-green-950/30 text-green-700 dark:text-green-400 hover:bg-green-100 dark:hover:bg-green-950/50 flex items-center justify-center gap-1.5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed text-xs font-medium"
              aria-label="Approve"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
              </svg>
            </button>
            <button
              onClick={(e) => {
                e.stopPropagation()
                if (onReject) {
                  onReject()
                }
              }}
              disabled={isApproving}
              className="h-7 px-3 rounded-md border border-red-200 dark:border-red-800 bg-red-50 dark:bg-red-950/30 text-red-700 dark:text-red-400 hover:bg-red-100 dark:hover:bg-red-950/50 flex items-center justify-center gap-1.5 transition-colors disabled:opacity-50 disabled:cursor-not-allowed text-xs font-medium"
              aria-label="Reject"
            >
              <svg className="w-3.5 h-3.5" fill="none" stroke="currentColor" viewBox="0 0 24 24" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        ) : (
          <button
            onClick={onToggle}
            className="flex items-center justify-center"
          >
            <svg
              className={`w-4 h-4 text-muted-foreground transition-transform ${isExpanded ? 'rotate-180' : ''}`}
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
            >
              <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
            </svg>
          </button>
        )}
      </div>
      
      {/* Expanded Details */}
      {isExpanded && (
        <div className="px-3 py-2 border-t bg-muted/20 space-y-3">
          {/* Tool Arguments */}
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
          
          {/* Document References */}
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
          
          {/* Tool Result Preview */}
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
          
          {/* Tool Execution Status */}
          {toolCall.status && (
            <div>
              <div className="text-xs font-semibold text-muted-foreground mb-1">Status</div>
              <div className="flex items-center gap-2">
                <div className={`text-xs px-2 py-1 rounded inline-block ${
                  toolCall.status === 'completed' ? 'bg-green-100 text-green-800 dark:bg-green-900 dark:text-green-200' :
                  toolCall.status === 'executing' ? 'bg-blue-100 text-blue-800 dark:bg-blue-900 dark:text-blue-200' :
                  toolCall.status === 'error' ? 'bg-red-100 text-red-800 dark:bg-red-900 dark:text-red-200' :
                  toolCall.status === 'pending' ? 'bg-yellow-100 text-yellow-800 dark:bg-yellow-900 dark:text-yellow-200' :
                  'bg-muted text-muted-foreground'
                }`}>
                  {toolCall.status}
                </div>
                
              </div>
            </div>
          )}
          
          {/* Raw Tool Output (for plan execution) */}
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
}
