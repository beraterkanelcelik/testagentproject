/**
 * useToolApproval Hook
 * 
 * Manages tool approval logic for human-in-the-loop workflows.
 * 
 * Features:
 * - Handles tool approval API calls
 * - Updates tool call status in message store
 * - Manages approving state to prevent double-clicks
 * - Handles streaming mode (SSE)
 * - Syncs with database after approval
 * 
 * Location: frontend/src/hooks/useToolApproval.ts
 * 
 * This hook implements the LangGraph human-in-the-loop pattern:
 * - Reference: https://docs.langchain.com/oss/python/langgraph/use-functional-api#review-tool-calls
 * - When a tool requires approval, the workflow pauses (interrupt)
 * - User reviews and approves via this hook
 * - Workflow resumes with approved tool result (Command pattern)
 */

import { useState, useCallback } from 'react'
import { toast } from 'sonner'
import { agentAPI } from '@/lib/api'
import { getErrorMessage } from '@/lib/utils'
import type { Message } from '@/state/useChatStore'

interface UseToolApprovalProps {
  /** Current session */
  currentSession: { id: number } | null
  /** Function to update messages in store */
  updateMessages: (updater: (messages: Message[]) => Message[]) => void
  /** Function to load messages from database */
  loadMessages: (sessionId: number) => Promise<void>
}

/**
 * useToolApproval - Hook for managing tool approval workflow
 * 
 * Returns:
 * - handleApproveTool: Function to approve a tool call
 * - approvingToolCalls: Set of tool call IDs currently being approved
 * - setApprovingToolCalls: Function to manually update approving state
 * 
 * The approval process:
 * 1. Mark tool as approving (prevents double-clicks)
 * 2. Update tool status to 'approved' immediately (optimistic update)
 * 3. Send approval request to backend
 * 4. Update tool status to 'completed' with result
 * 5. Sync with database after delay
 */
export function useToolApproval({
  currentSession,
  updateMessages,
  loadMessages,
}: UseToolApprovalProps) {
  const [approvingToolCalls, setApprovingToolCalls] = useState<Set<string>>(new Set())

  /**
   * Approves a tool call and executes it
   * 
   * @param messageId - ID of the message containing the tool call
   * @param toolCall - The tool call object to approve
   * @param toolCallId - Unique identifier for the tool call
   * @param toolName - Name of the tool
   */
  const handleApproveTool = useCallback(async (
    messageId: number,
    toolCall: any,
    toolCallId: string,
    toolName: string
  ) => {
    if (!currentSession) {
      toast.error('No active session')
      return
    }

    const toolCallIdKey = toolCall.id || toolCallId
    
    // Prevent double-click
    if (approvingToolCalls.has(toolCallIdKey)) {
      console.log(`[HITL] [REVIEW] Approval already in progress for tool_call_id=${toolCallIdKey}, ignoring duplicate click`)
      return
    }
    
    console.log(`[HITL] [REVIEW] User clicked Approve & Execute: tool=${toolName} tool_call_id=${toolCallIdKey} session=${currentSession.id}`)
    
    // Mark as approving immediately
    setApprovingToolCalls(prev => new Set(prev).add(toolCallIdKey))
    
    // Update tool status to 'approved' immediately (optimistic update)
    updateMessages((messages) => {
      return messages.map((m: Message) => {
        if (m.id === messageId) {
          const toolCalls = m.metadata?.tool_calls || []
          const updatedToolCalls = toolCalls.map((tc: any, idx: number) => {
            const tcActualId = tc.id || `tool-${m.id}-${idx}`
            const tcComputedId = `tool-${m.id}-${idx}`
            const actualToolCallId = toolCall.id || toolCallId
            const matches = (
              tcActualId === actualToolCallId ||
              tcComputedId === toolCallId ||
              (tc.id === toolCall.id && tc.name === toolName)
            )
            
            if (matches) {
              console.log(`[HITL] [REVIEW] Updating tool call status immediately: tool_call_id=${tcActualId} from ${tc.status} to approved session=${currentSession.id}`)
              return {
                ...tc,
                status: 'approved',
                requires_approval: false
              }
            }
            return tc
          })
          return {
            ...m,
            metadata: {
              ...m.metadata,
              tool_calls: updatedToolCalls
            }
          }
        }
        return m
      })
    })
    
    try {
      console.log(`[HITL] [REVIEW] Sending approval request: tool=${toolName} args=`, toolCall.args)
      
      // Build resume payload with approval decision
      const resumePayload = {
        approvals: {
          [toolCallIdKey]: {
            approved: true,
            args: toolCall.args || {}
          }
        }
      }
      
      const response = await agentAPI.approveTool({
        chat_session_id: currentSession.id,
        resume: resumePayload
      })
      
      console.log(`[HITL] [REVIEW] Approval response received: success=${response.data.success} status=${response.data.status} session=${currentSession.id}`)
      
      if (response.data.success) {
        // Backend now returns immediately after sending resume signal (non-blocking)
        // The tool call status should already be "approved" from the optimistic update
        // SSE stream will deliver the final response and update tool call to "completed"
        
        console.log(`[HITL] [REVIEW] Tool approval signal sent successfully: tool=${toolName} session=${currentSession.id}`)
        
        // Ensure tool call is marked as approved (optimistic update already did this, but ensure consistency)
        updateMessages((messages) => {
          return messages.map((m: Message) => {
            if (m.id === messageId) {
              const toolCalls = m.metadata?.tool_calls || []
              const updatedToolCalls = toolCalls.map((tc: any, idx: number) => {
                const tcActualId = tc.id || `tool-${m.id}-${idx}`
                const tcComputedId = `tool-${m.id}-${idx}`
                const actualToolCallId = toolCall.id || toolCallId
                const matches = (
                  tcActualId === actualToolCallId ||
                  tcComputedId === toolCallId ||
                  (tc.id === toolCall.id && tc.name === toolName)
                )
                
                if (matches && tc.status !== 'completed') {
                  // Keep as approved - SSE will update to completed when result arrives
                  console.log(`[HITL] [REVIEW] Tool call approved, waiting for execution: tool_call_id=${tcActualId} session=${currentSession.id}`)
                  return {
                    ...tc,
                    status: 'approved', // Will be updated to 'completed' by SSE stream
                    requires_approval: false
                  }
                }
                return tc
              })
              return {
                ...m,
                metadata: {
                  ...m.metadata,
                  tool_calls: updatedToolCalls
                }
              }
            }
            return m
          })
        })
        
        toast.success('Tool approved - executing...')
        
        // The existing SSE connection will receive the final/done events
        // The stream handlers already update messages, so we don't need to poll DB
        console.log(`[HITL] [REVIEW] Tool approved - waiting for SSE stream to deliver final response session=${currentSession.id}`)
        
        // Clear approving state - the stream will deliver the response
        setApprovingToolCalls(prev => {
          const next = new Set(prev)
          next.delete(toolCallIdKey)
          return next
        })
      } else {
        console.error(`[HITL] [REVIEW] Tool approval failed: error=${response.data.error} session=${currentSession?.id}`)
        toast.error(response.data.error || 'Tool execution failed')
        // Clear approving state on failure
        setApprovingToolCalls(prev => {
          const next = new Set(prev)
          next.delete(toolCallIdKey)
          return next
        })
      }
    } catch (error: any) {
      console.error(`[HITL] [REVIEW] Error approving tool:`, error, `session=${currentSession?.id}`)
      toast.error(getErrorMessage(error, 'Failed to approve tool'))
      // Clear approving state on error
      setApprovingToolCalls(prev => {
        const next = new Set(prev)
        next.delete(toolCallIdKey)
        return next
      })
    }
  }, [currentSession, updateMessages, loadMessages, approvingToolCalls])

  /**
   * Rejects a tool call
   * 
   * @param messageId - ID of the message containing the tool call
   * @param toolCall - The tool call object to reject
   * @param toolCallId - Unique identifier for the tool call
   * @param toolName - Name of the tool
   */
  const handleRejectTool = useCallback(async (
    messageId: number,
    toolCall: any,
    toolCallId: string,
    toolName: string
  ) => {
    if (!currentSession) {
      toast.error('No active session')
      return
    }

    const toolCallIdKey = toolCall.id || toolCallId
    
    // Prevent double-click
    if (approvingToolCalls.has(toolCallIdKey)) {
      return
    }
    
    console.log(`[HITL] [REVIEW] User rejected tool: tool=${toolName} tool_call_id=${toolCallIdKey} session=${currentSession.id}`)
    
    // Mark as approving immediately (to prevent double-clicks)
    setApprovingToolCalls(prev => new Set(prev).add(toolCallIdKey))
    
    // Update tool status to 'rejected' immediately (optimistic update)
    updateMessages((messages) => {
      return messages.map((m: Message) => {
        if (m.id === messageId) {
          const toolCalls = m.metadata?.tool_calls || []
          const updatedToolCalls = toolCalls.map((tc: any, idx: number) => {
            const tcActualId = tc.id || `tool-${m.id}-${idx}`
            const tcComputedId = `tool-${m.id}-${idx}`
            const actualToolCallId = toolCall.id || toolCallId
            const matches = (
              tcActualId === actualToolCallId ||
              tcComputedId === toolCallId ||
              (tc.id === toolCall.id && tc.name === toolName)
            )
            
            if (matches) {
              return {
                ...tc,
                status: 'rejected',
                requires_approval: false
              }
            }
            return tc
          })
          return {
            ...m,
            metadata: {
              ...m.metadata,
              tool_calls: updatedToolCalls
            }
          }
        }
        return m
      })
    })
    
    try {
      // Build resume payload with rejection decision
      const resumePayload = {
        approvals: {
          [toolCallIdKey]: {
            approved: false,
            args: toolCall.args || {}
          }
        }
      }
      
      const response = await agentAPI.approveTool({
        chat_session_id: currentSession.id,
        resume: resumePayload
      })
      
      if (response.data.success) {
        toast.info('Tool rejected')
      } else {
        toast.error(response.data.error || 'Failed to reject tool')
      }
    } catch (error: any) {
      console.error(`[HITL] [REVIEW] Error rejecting tool:`, error, `session=${currentSession?.id}`)
      toast.error(getErrorMessage(error, 'Failed to reject tool'))
    } finally {
      // Clear approving state
      setApprovingToolCalls(prev => {
        const next = new Set(prev)
        next.delete(toolCallIdKey)
        return next
      })
    }
  }, [currentSession, updateMessages, approvingToolCalls])

  return {
    handleApproveTool,
    handleRejectTool,
    approvingToolCalls,
    setApprovingToolCalls,
  }
}
