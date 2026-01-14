/**
 * MessageItem Component
 * 
 * Renders individual chat messages with support for:
 * - User messages
 * - Assistant messages with agent names
 * - Plan proposals
 * - Clarification requests
 * - Status messages (system messages with animation)
 * - Tool calls
 * - Raw tool outputs from plan execution
 * 
 * Features:
 * - Different styling for user vs assistant messages
 * - Agent name display for assistant messages
 * - Plan proposal approval/rejection
 * - Tool call display with approval UI
 * - Status message animations
 * 
 * Location: frontend/src/components/chat/MessageItem.tsx
 */

import React from 'react'
import type { Message } from '@/state/useChatStore'
import MarkdownMessage from '@/components/MarkdownMessage'
import PlanProposal, { type PlanProposalData } from '@/components/PlanProposal'
import JsonViewer from '@/components/JsonViewer'
import ToolCallItem, { type ToolCallItemProps } from './ToolCallItem'

export interface MessageItemProps {
  /** The message to render */
  message: Message
  /** All messages (for checking previous message type) */
  messages: Message[]
  /** Set of message IDs that have completed streaming */
  streamComplete: Set<number>
  /** Set of expanded tool call IDs */
  expandedToolCalls: Set<string>
  /** Callback to toggle tool call expansion */
  onToggleToolCall: (toolCallId: string) => void
  /** Callback when user approves a tool call */
  onApproveTool: (messageId: number, toolCall: any, toolCallId: string, toolName: string) => Promise<void>
  /** Callback when user rejects a tool call */
  onRejectTool?: (messageId: number, toolCall: any, toolCallId: string, toolName: string) => Promise<void>
  /** Set of tool call IDs currently being approved */
  approvingToolCalls: Set<string>
  /** Current session (required for tool approval) */
  currentSession: { id: number } | null
  /** Callback when user approves a plan */
  onPlanApproval: (messageId: number, plan: PlanProposalData) => Promise<void>
  /** Callback when user rejects a plan */
  onPlanRejection: (messageId: number) => void
  /** ID of message currently executing a plan */
  executingPlanMessageId: number | null
  /** User email (for user avatar) */
  userEmail?: string | null
}

/**
 * MessageItem - Individual message rendering component
 * 
 * This component handles different message types:
 * 1. Status messages (system) - animated dots, compact display
 * 2. User messages - right-aligned, primary color
 * 3. Assistant messages - left-aligned, with agent name and various content types:
 *    - Regular markdown content
 *    - Plan proposals (with approval UI)
 *    - Clarification requests
 *    - Tool calls (collapsible, with approval UI)
 *    - Raw tool outputs (from plan execution)
 */
export default function MessageItem({
  message,
  messages,
  streamComplete,
  expandedToolCalls,
  onToggleToolCall,
  onApproveTool,
  onRejectTool,
  approvingToolCalls,
  currentSession,
  onPlanApproval,
  onPlanRejection,
  executingPlanMessageId,
  userEmail,
}: MessageItemProps) {
  // Helper functions
  const getAgentName = (msg: Message): string => {
    if (msg.role === 'user') return ''
    return msg.metadata?.agent_name || 'assistant'
  }

  const formatAgentName = (name: string): string => {
    return name.charAt(0).toUpperCase() + name.slice(1)
  }

  const agentName = getAgentName(message)
  const isPlanProposal = message.response_type === 'plan_proposal' && message.plan
  const isExecutingPlan = executingPlanMessageId === message.id
  const hasClarification = message.clarification
  const hasRawToolOutputs = message.raw_tool_outputs && message.raw_tool_outputs.length > 0
  const isStatusMessage = message.role === 'system' && message.metadata?.status_type === 'task_status'

  // Render status messages as system messages with animation (like Cursor chat)
  if (isStatusMessage) {
    const isCompleted = message.metadata?.is_completed === true
    // Check if previous message is also a status message to reduce gap
    const msgIndex = messages.indexOf(message)
    const prevMsg = msgIndex > 0 ? messages[msgIndex - 1] : null
    const isPrevStatus = prevMsg?.role === 'system' && prevMsg?.metadata?.status_type === 'task_status'
    
    return (
      <div
        key={message.id}
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
            {message.content}
          </div>
        </div>
      </div>
    )
  }

  // Regular user/assistant messages
  // Check if assistant message has content (tokens have arrived) before showing avatar/name
  const hasContent = message.content && message.content.trim().length > 0
  const hasToolCalls = message.metadata?.tool_calls && Array.isArray(message.metadata.tool_calls) && message.metadata.tool_calls.length > 0
  const hasPlan = message.plan && message.response_type === 'plan_proposal'
  const hasClarificationContent = message.clarification
  
  // Check if message only has tool calls awaiting approval (no content)
  // A message only has tool approvals if:
  // 1. It has tool calls
  // 2. ALL tool calls are awaiting approval
  // 3. There's no content, plan, or clarification
  const hasAwaitingApprovalTools = hasToolCalls && message.metadata.tool_calls.some((tc: any) => 
    (tc.status === 'awaiting_approval' || tc.status === 'pending') && 
    (tc.requires_approval === true || tc.status === 'awaiting_approval')
  )
  const allToolsAwaitingApproval = hasToolCalls && message.metadata.tool_calls.length > 0 && 
    message.metadata.tool_calls.every((tc: any) => 
      (tc.status === 'awaiting_approval' || tc.status === 'pending') && 
      (tc.requires_approval === true || tc.status === 'awaiting_approval')
    )
  const onlyHasToolApprovals = !hasContent && !hasPlan && !hasClarificationContent && allToolsAwaitingApproval
  
  // Show avatar/name only when agent has started writing (content exists) or has tool calls/plan/clarification
  // BUT hide avatar/name/bubble if message only has tool approvals (no content)
  // When only tool approvals exist, don't show agent info - tool approvals should stand alone
  const shouldShowAgentInfo = message.role === 'assistant' && 
    !onlyHasToolApprovals && 
    (hasContent || (hasToolCalls && !allToolsAwaitingApproval) || hasPlan || hasClarificationContent)
  
  return (
    <div
      key={message.id}
      className={`flex gap-3 items-start ${message.role === 'user' ? 'justify-end' : 'justify-start'}`}
    >
      {/* Assistant Avatar - only show when agent has started writing */}
      {shouldShowAgentInfo && (
        <div className="w-8 h-8 rounded-full bg-primary/10 flex items-center justify-center flex-shrink-0 mt-1">
          <svg className="w-5 h-5 text-primary" fill="none" stroke="currentColor" viewBox="0 0 24 24">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9.663 17h4.673M12 3v1m6.364 1.636l-.707.707M21 12h-1M4 12H3m3.343-5.657l-.707-.707m2.828 9.9a5 5 0 117.072 0l-.548.547A3.374 3.374 0 0014 18.469V19a2 2 0 11-4 0v-.531c0-.895-.356-1.754-.988-2.386l-.548-.547z" />
          </svg>
        </div>
      )}
      
      <div className="flex flex-col max-w-[85%]">
        {/* Agent Name - only show when agent has started writing */}
        {shouldShowAgentInfo && agentName && (
          <div className="text-xs text-muted-foreground mb-1.5 px-1">
            {formatAgentName(agentName)}
          </div>
        )}
        
        {/* Tool calls - appear where they occur in the stream, not always at the end */}
        {/* Tool calls appear in real-time as they're added during streaming, showing the execution flow in order */}
        {message.role === 'assistant' && 
         message.metadata?.tool_calls && 
         Array.isArray(message.metadata.tool_calls) && 
         message.metadata.tool_calls.length > 0 && (
          <div className={onlyHasToolApprovals ? "space-y-2" : "mb-3 px-1 space-y-2"}>
            {message.metadata.tool_calls.map((toolCall: any, idx: number) => {
              const toolCallId = `tool-${message.id}-${idx}`
              const isExpanded = expandedToolCalls.has(toolCallId)
              const toolName = toolCall.tool || toolCall.name || 'Tool'
              
              // Check if there's a subsequent assistant message with content after this message
              // If yes, it means the tools were already executed, so don't show approval UI
              const currentMessageIndex = messages.findIndex((m: Message) => m.id === message.id)
              const hasSubsequentAnswer = currentMessageIndex >= 0 && 
                messages.slice(currentMessageIndex + 1).some((m: Message) => 
                  m.role === 'assistant' && 
                  m.content && 
                  m.content.trim().length > 0 &&
                  m.id > message.id
                )
              
              return (
                <ToolCallItem
                  key={idx}
                  toolCall={toolCall}
                  toolCallId={toolCallId}
                  isExpanded={isExpanded}
                  onToggle={() => onToggleToolCall(toolCallId)}
                  onApprove={async () => {
                    await onApproveTool(message.id, toolCall, toolCallId, toolName)
                  }}
                  onReject={onRejectTool ? async () => {
                    await onRejectTool(message.id, toolCall, toolCallId, toolName)
                  } : undefined}
                  approvingToolCalls={approvingToolCalls}
                  currentSession={currentSession}
                  hasSubsequentAnswer={hasSubsequentAnswer}
                />
              )
            })}
          </div>
        )}
        
        {/* Message Content - only show bubble when there's actual content to display */}
        {/* For assistant messages, only show bubble if we have content, plan, or clarification */}
        {(message.role === 'user' || (shouldShowAgentInfo && (hasContent || hasPlan || hasClarificationContent))) && (
          <div
            className={`rounded-2xl px-4 py-3 inline-block ${
              message.role === 'user'
                ? 'bg-primary text-primary-foreground'
                : 'bg-muted text-foreground'
            }`}
          >
            {message.role === 'user' ? (
              <p className="text-[15px] leading-relaxed whitespace-pre-wrap break-words">
                {message.content}
              </p>
            ) : isPlanProposal && message.plan ? (
              // Plan proposal rendering
              <PlanProposal
                plan={message.plan}
                onApprove={() => onPlanApproval(message.id, message.plan!)}
                onReject={() => onPlanRejection(message.id)}
                isExecuting={isExecutingPlan}
              />
            ) : hasClarification ? (
              // Clarification request rendering
              <div className="space-y-3">
                <div className="text-sm text-muted-foreground italic">
                  {message.clarification}
                </div>
                <div className="text-sm">
                  Please provide clarification to continue.
                </div>
              </div>
            ) : hasContent ? (
              // Regular answer rendering - only show when content exists
              <MarkdownMessage content={message.content} />
            ) : null}
          </div>
        )}
        
        {/* Raw tool outputs from plan execution */}
        {hasRawToolOutputs && (
          <div className="mt-3 px-1 space-y-2">
            <div className="text-xs font-semibold text-muted-foreground mb-2">
              Plan Execution Results:
            </div>
            {message.raw_tool_outputs!.map((output, idx) => (
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
      </div>
      
      {/* User Avatar */}
      {message.role === 'user' && (
        <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center flex-shrink-0 mt-1">
          <span className="text-primary-foreground text-sm font-medium">
            {userEmail?.[0]?.toUpperCase() || 'U'}
          </span>
        </div>
      )}
    </div>
  )
}
