"""
Temporal workflow definitions for chat execution.
Long-running workflow per chat session using signals.
"""
import asyncio
import hashlib
from dataclasses import dataclass
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy
from typing import Dict, Any, Optional
from collections import deque

# Import activity - sandbox restrictions configured in worker to allow this
from app.agents.temporal.activity import run_chat_activity


@dataclass
class ChatActivityInput:
    """Input for chat activity execution."""
    chat_id: int
    state: Dict[str, Any]


@dataclass
class MessageSignal:
    """Signal data for new messages."""
    message: str
    plan_steps: Optional[list] = None
    flow: str = "main"


@workflow.defn
class ChatWorkflow:
    """
    Long-running Temporal workflow per chat session.
    
    Features:
    - Waits for signals (new messages) instead of running once
    - Processes messages via activities when signals are received
    - Automatically closes after 5 minutes of inactivity
    - Uses signal_with_start pattern for initialization
    
    Follows Temporal best practices:
    - Signal-based message handling
    - Workflow timeouts for inactivity
    - Activity heartbeating for long-running operations
    """
    
    # Maximum number of processed messages to track before clearing
    # Prevents unbounded memory growth in long-running workflows
    MAX_PROCESSED_MESSAGES = 1000
    
    def __init__(self) -> None:
        """Initialize workflow state."""
        self.pending_messages: deque = deque()
        self.last_activity_time: Optional[float] = None
        self.is_closing = False
        self.initial_state: Dict[str, Any] = {}
        # Track processed messages to prevent duplicates (use content hash)
        self.processed_messages: set = set()
    
    @workflow.signal
    def new_message(self, message: str, plan_steps: Optional[list] = None, flow: str = "main") -> None:
        """
        Signal handler for new messages.
        
        Args:
            message: Message content
            plan_steps: Optional plan steps
            flow: Flow type
        """
        if self.is_closing:
            workflow.logger.warning("Workflow is closing, ignoring new message signal")
            return
        
        # Create message hash for deduplication (use message content + flow)
        message_hash = hashlib.md5(f"{message}:{flow}".encode()).hexdigest()
        
        # Check if message is already in queue or already processed
        message_in_queue = any(
            hashlib.md5(f"{m.get('message', '')}:{m.get('flow', 'main')}".encode()).hexdigest() == message_hash
            for m in self.pending_messages
        )
        
        if message_in_queue:
            workflow.logger.warning(f"[DUPLICATE_SIGNAL] Ignoring duplicate signal - message already in queue session={workflow.info().workflow_id} message_preview={message[:50]}...")
            return
        
        if message_hash in self.processed_messages:
            workflow.logger.warning(f"[DUPLICATE_SIGNAL] Ignoring duplicate signal - message already processed session={workflow.info().workflow_id} message_preview={message[:50]}...")
            return
        
        # Add message to queue
        signal_data = {
            "message": message,
            "plan_steps": plan_steps,
            "flow": flow,
            "_hash": message_hash,  # Store hash for later reference
        }
        self.pending_messages.append(signal_data)
        # Update last activity time
        self.last_activity_time = workflow.now().timestamp()
        workflow.logger.info(f"[SIGNAL_RECEIVE] Received message signal session={workflow.info().workflow_id} message_preview={message[:50]}... queue_size={len(self.pending_messages)}")
    
    @workflow.run
    async def run(
        self, 
        chat_id: int, 
        initial_state: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Long-running workflow that processes messages via signals.
        
        Args:
            chat_id: Chat session ID
            initial_state: Optional initial state (for signal_with_start)
                Contains: user_id, tenant_id, org_slug, org_roles, app_roles
            
        Returns:
            Dictionary with final status
        """
        workflow.logger.info(f"Starting long-running chat workflow for session {chat_id}")
        
        # Store initial state for use in activities
        self.initial_state = initial_state or {}
        
        # Log initial_state contents for debugging (especially user_id/tenant_id)
        workflow.logger.debug(
            f"[WORKFLOW_INIT] Stored initial_state for chat_id={chat_id}: "
            f"user_id={self.initial_state.get('user_id')}, "
            f"tenant_id={self.initial_state.get('tenant_id')}, "
            f"keys={list(self.initial_state.keys())}"
        )
        
        # Initialize last activity time
        self.last_activity_time = workflow.now().timestamp()
        
        # Process initial message if provided (signal_with_start)
        # Note: The signal will be received automatically via signal_with_start
        # So we don't need to manually add it here
        
        # Inactivity timeout: 5 minutes
        inactivity_timeout = timedelta(minutes=5)
        
        while not self.is_closing:
            # Check for inactivity
            if self.last_activity_time:
                elapsed = timedelta(seconds=workflow.now().timestamp() - self.last_activity_time)
                if elapsed >= inactivity_timeout:
                    workflow.logger.info(f"Workflow inactive for {elapsed}, closing session {chat_id}")
                    self.is_closing = True
                    break
            
            # Process pending messages
            if self.pending_messages:
                signal_data = self.pending_messages.popleft()
                message_content = signal_data.get("message", "")
                
                workflow.logger.info(f"[WORKFLOW_PROCESS] Processing message from queue: chat_id={chat_id}, message_preview={message_content[:50]}..., queue_remaining={len(self.pending_messages)}")
                
                # Prepare state for activity
                # CRITICAL: Ensure user_id and tenant_id are always present for correct Redis channel
                user_id = self.initial_state.get("user_id")
                if not user_id:
                    workflow.logger.error(f"[WORKFLOW_STATE] Missing user_id in initial_state for chat_id={chat_id}. initial_state_keys={list(self.initial_state.keys())}")
                    # This should never happen if workflow_manager is correct, but log error for debugging
                
                # Ensure tenant_id is set - use user_id as fallback if tenant_id is missing
                tenant_id = self.initial_state.get("tenant_id") or user_id
                if not tenant_id:
                    workflow.logger.error(f"[WORKFLOW_STATE] Missing both tenant_id and user_id in initial_state for chat_id={chat_id}")
                
                state = {
                    "user_id": user_id,
                    "session_id": chat_id,
                    "message": message_content,
                    "plan_steps": signal_data.get("plan_steps"),
                    "flow": signal_data.get("flow", "main"),
                    "tenant_id": tenant_id,  # Use user_id as fallback
                    "org_slug": self.initial_state.get("org_slug"),
                    "org_roles": self.initial_state.get("org_roles", []),
                    "app_roles": self.initial_state.get("app_roles", []),
                }
                workflow.logger.info(f"[WORKFLOW_STATE] Prepared state for activity: chat_id={chat_id}, message_preview={message_content[:50]}..., user_id={user_id}, tenant_id={tenant_id}")
                
                # Execute activity for this message
                try:
                    activity_input = ChatActivityInput(chat_id=chat_id, state=state)
                    
                    result = await workflow.execute_activity(
                        run_chat_activity,
                        activity_input,
                        # Total time allowed from scheduling to completion (includes all retries)
                        schedule_to_close_timeout=timedelta(minutes=30),
                        # Maximum time for a single attempt
                        start_to_close_timeout=timedelta(minutes=10),
                        # Heartbeat timeout - activity must heartbeat within this interval
                        heartbeat_timeout=timedelta(seconds=30),
                        # Retry policy for transient failures
                        retry_policy=RetryPolicy(
                            maximum_attempts=3,
                            initial_interval=timedelta(seconds=1),
                            backoff_coefficient=2.0,
                            maximum_interval=timedelta(seconds=30),
                        ),
                    )
                    
                    # Mark message as processed
                    message_hash = signal_data.get('_hash')
                    if message_hash:
                        self.processed_messages.add(message_hash)
                        
                        # Cap processed_messages to prevent unbounded memory growth
                        if len(self.processed_messages) > self.MAX_PROCESSED_MESSAGES:
                            workflow.logger.warning(
                                f"Clearing processed_messages set (size={len(self.processed_messages)}) "
                                f"to prevent unbounded growth for session {chat_id}"
                            )
                            self.processed_messages.clear()
                    
                    # Update last activity time after successful processing
                    self.last_activity_time = workflow.now().timestamp()
                    workflow.logger.info(f"[MESSAGE_PROCESS] Processed message session={chat_id} message_preview={signal_data.get('message', '')[:50]}... status={result.get('status')} event_count={result.get('event_count', 'unknown')}")
                    
                except asyncio.CancelledError:
                    # Workflow was cancelled during activity execution
                    workflow.logger.info(f"Workflow cancelled during activity execution for session {chat_id}")
                    self.is_closing = True
                    raise  # Re-raise to allow Temporal to handle cancellation
                except Exception as e:
                    workflow.logger.error(f"Error processing message for session {chat_id}: {e}", exc_info=True)
                    # Continue processing other messages even if one fails
                    self.last_activity_time = workflow.now().timestamp()
            
            # Wait for new signals or timeout
            # Use wait_condition to wait for either:
            # 1. New message signal (adds to pending_messages)
            # 2. Inactivity timeout (5 minutes)
            
            if not self.pending_messages:
                # Wait for signal or timeout
                try:
                    # Wait up to inactivity timeout for a signal
                    await workflow.wait_condition(
                        lambda: len(self.pending_messages) > 0 or self.is_closing,
                        timeout=inactivity_timeout
                    )
                except TimeoutError:
                    # Inactivity timeout reached
                    workflow.logger.info(f"Inactivity timeout reached for session {chat_id}")
                    self.is_closing = True
                    break
                except asyncio.CancelledError:
                    # Workflow was cancelled (e.g., session deleted)
                    workflow.logger.info(f"Workflow cancelled for session {chat_id}")
                    self.is_closing = True
                    raise  # Re-raise to allow Temporal to handle cancellation
            else:
                # Small delay to allow batching of signals
                try:
                    await workflow.sleep(timedelta(milliseconds=100))
                except asyncio.CancelledError:
                    # Workflow was cancelled during sleep
                    workflow.logger.info(f"Workflow cancelled during processing for session {chat_id}")
                    self.is_closing = True
                    raise  # Re-raise to allow Temporal to handle cancellation
        
        workflow.logger.info(f"Chat workflow closing for session {chat_id}")
        return {
            "status": "closed",
            "chat_id": chat_id,
            "reason": "inactivity_timeout" if self.is_closing else "normal"
        }
