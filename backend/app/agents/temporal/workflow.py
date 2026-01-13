"""
Temporal workflow definitions for chat execution.
Long-running workflow per chat session using signals.
"""
import asyncio
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
        # Track resume payload for interrupt resume (human-in-the-loop)
        self.resume_payload: Optional[Any] = None
        # Store last activity result for query (non-stream mode)
        self.last_activity_result: Optional[Dict[str, Any]] = None
    
    @workflow.signal
    def new_message(self, message: str, plan_steps: Optional[list] = None, flow: str = "main", mode: str = "stream", run_id: Optional[str] = None, parent_message_id: Optional[int] = None) -> None:
        """
        Signal handler for new messages.
        
        Args:
            message: Message content
            plan_steps: Optional plan steps
            flow: Flow type
            mode: Execution mode - "stream" for streaming (SSE), "non_stream" for non-streaming (API)
            run_id: Optional correlation ID for /run polling (ensures stable dedupe identity)
            parent_message_id: Optional parent user message ID for correlation
        """
        if self.is_closing:
            workflow.logger.warning("Workflow is closing, ignoring new message signal")
            return
        
        # Create stable identity hash for deduplication (not content-based)
        # Use run_id if available (most stable), otherwise parent_message_id, otherwise fallback to UUID
        # This prevents collisions when same message text is sent via /stream then /run
        if run_id:
            message_hash = f"run:{run_id}"
        elif parent_message_id:
            message_hash = f"msg:{parent_message_id}"
        else:
            # Fallback: generate unique hash (shouldn't happen if API passes correlation IDs)
            # Use workflow.uuid4() for determinism (required for Temporal workflow replay)
            message_hash = f"fallback:{workflow.uuid4().hex[:16]}"
            workflow.logger.warning(f"[DEDUPE] No run_id or parent_message_id provided, using fallback hash session={workflow.info().workflow_id}")
        
        # Check if message is already in queue or already processed
        message_in_queue = any(
            m.get("_hash") == message_hash
            for m in self.pending_messages
        )
        
        if message_in_queue:
            workflow.logger.warning(f"[DUPLICATE_SIGNAL] Ignoring duplicate signal - message already in queue session={workflow.info().workflow_id} hash={message_hash} message_preview={message[:50]}...")
            return
        
        if message_hash in self.processed_messages:
            workflow.logger.warning(f"[DUPLICATE_SIGNAL] Ignoring duplicate signal - message already processed session={workflow.info().workflow_id} hash={message_hash} message_preview={message[:50]}...")
            return
        
        # Add message to queue
        signal_data = {
            "message": message,
            "plan_steps": plan_steps,
            "flow": flow,
            "mode": mode,  # Execution mode: "stream" or "non_stream"
            "run_id": run_id,  # Correlation ID
            "parent_message_id": parent_message_id,  # Parent message ID
            "_hash": message_hash,  # Store stable hash for deduplication
        }
        self.pending_messages.append(signal_data)
        # Update last activity time
        self.last_activity_time = workflow.now().timestamp()
        workflow.logger.info(f"[SIGNAL_RECEIVE] Received message signal session={workflow.info().workflow_id} hash={message_hash} message_preview={message[:50]}... queue_size={len(self.pending_messages)}")
    
    @workflow.signal
    def resume(self, resume_payload: Any) -> None:
        """
        Signal handler for resuming interrupted workflow (human-in-the-loop).
        
        Args:
            resume_payload: Resume payload containing approval decisions
                           Expected shape: {"approvals": {"tool_call_id": {"approved": bool, "args": {...}}}}
        """
        if self.is_closing:
            workflow.logger.warning("Workflow is closing, ignoring resume signal")
            return
        
        # Envelope resume_payload with session_id for workflow access
        # This ensures session_id is available when Command(resume=...) is processed
        chat_id = int(workflow.info().workflow_id.split("-")[-1])  # Extract from workflow_id format: "chat-1-{chat_id}"
        if isinstance(resume_payload, dict):
            # Add session_id to resume payload so workflow can access it
            enveloped_payload = {
                "session_id": chat_id,
                **resume_payload  # Preserve original payload structure
            }
        else:
            # If resume_payload is not a dict, wrap it
            enveloped_payload = {
                "session_id": chat_id,
                "approvals": resume_payload if isinstance(resume_payload, dict) else {}
            }
        
        self.resume_payload = enveloped_payload
        workflow.logger.info(f"[HITL] Received resume signal: session_id={chat_id}, resume_payload keys={list(enveloped_payload.keys())} session={workflow.info().workflow_id}")
        workflow.logger.info(f"[HITL] This signal will wake up wait_condition if workflow is waiting for resume session={workflow.info().workflow_id}")
    
    @workflow.query
    def get_last_result(self) -> Optional[Dict[str, Any]]:
        """
        Query handler to get last activity result without waiting for workflow completion.
        
        Returns:
            Dictionary with activity result including run_id, status, response, interrupt, error, timestamp
            Returns None if no result is available yet
        """
        # Returns None if not set yet (handled by API polling loop)
        return self.last_activity_result
    
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
        # CRITICAL: Use both logger and print for debugging - Temporal may suppress logger output
        print(f"[WORKFLOW_START] Starting long-running chat workflow for session {chat_id}")
        print(f"[WORKFLOW_START] Workflow ID: {workflow.info().workflow_id}, Run ID: {workflow.info().run_id}")
        workflow.logger.info(f"[WORKFLOW_START] Starting long-running chat workflow for session {chat_id}")
        workflow.logger.info(f"[WORKFLOW_START] Workflow ID: {workflow.info().workflow_id}, Run ID: {workflow.info().run_id}")
        
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
                    "mode": signal_data.get("mode", "stream"),  # Pass mode to activity
                    "run_id": signal_data.get("run_id"),  # Pass correlation ID to activity
                    "parent_message_id": signal_data.get("parent_message_id"),  # Pass parent message ID to activity
                    "tenant_id": tenant_id,  # Use user_id as fallback
                    "org_slug": self.initial_state.get("org_slug"),
                    "org_roles": self.initial_state.get("org_roles", []),
                    "app_roles": self.initial_state.get("app_roles", []),
                }
                workflow.logger.info(f"[WORKFLOW_STATE] Prepared state for activity: chat_id={chat_id}, message_preview={message_content[:50]}..., user_id={user_id}, tenant_id={tenant_id}")
                
                # Execute activity for this message
                try:
                    activity_input = ChatActivityInput(chat_id=chat_id, state=state)
                    
                    workflow.logger.info(f"[WORKFLOW] Executing activity for message: chat_id={chat_id} message_preview={message_content[:50]}... session={chat_id}")
                    print(f"[WORKFLOW] [BEFORE_ACTIVITY] About to call execute_activity, chat_id={chat_id}")
                    workflow.logger.info(f"[WORKFLOW] [BEFORE_ACTIVITY] About to call execute_activity, chat_id={chat_id}")
                    result = await workflow.execute_activity(
                        run_chat_activity,
                        activity_input,
                        # Total time allowed from scheduling to completion (includes all retries)
                        schedule_to_close_timeout=timedelta(minutes=30),
                        # Maximum time for a single attempt
                        start_to_close_timeout=timedelta(minutes=10),
                        # Heartbeat timeout - activity must heartbeat within this interval
                        heartbeat_timeout=timedelta(seconds=60),  # Increased from 30s for slow LLM responses
                        # Retry policy for transient failures
                        retry_policy=RetryPolicy(
                            maximum_attempts=3,
                            initial_interval=timedelta(seconds=1),
                            backoff_coefficient=2.0,
                            maximum_interval=timedelta(seconds=30),
                        ),
                    )
                    workflow.logger.info(f"[WORKFLOW] [AFTER_ACTIVITY] Activity returned, result type={type(result)}, chat_id={chat_id}")
                    
                    # Log activity result for debugging - CRITICAL: This must appear in worker logs
                    workflow.logger.info(f"[WORKFLOW] [CRITICAL] Activity execution completed, processing result: type={type(result)} session={chat_id}")
                    if isinstance(result, dict):
                        result_status = result.get("status")
                        result_keys = list(result.keys())
                        workflow.logger.info(f"[WORKFLOW] Activity result received: status={result_status} keys={result_keys} session={chat_id}")
                    else:
                        result_status = None
                        workflow.logger.warning(f"[WORKFLOW] Activity result is not a dict: type={type(result)} value={str(result)[:200]} session={chat_id}")
                    
                    # Check if activity was interrupted (human-in-the-loop)
                    if result_status == "interrupted":
                        print(f"[HITL] [WORKFLOW] Detected interrupted status - entering resume wait loop session={chat_id}")
                        workflow.logger.info(f"[HITL] [WORKFLOW] Detected interrupted status - entering resume wait loop session={chat_id}")
                        interrupt_data = result.get("interrupt")
                        workflow.logger.info(f"[HITL] Activity returned interrupted: interrupt_data={interrupt_data} session={chat_id}")
                        
                        # Wait for resume signal with resume_payload
                        try:
                            print(f"[HITL] Entering wait_condition - workflow will pause until resume_payload is set session={chat_id}")
                            workflow.logger.info(f"[HITL] Entering wait_condition - workflow will pause until resume_payload is set session={chat_id}")
                            await workflow.wait_condition(
                                lambda: self.resume_payload is not None,
                                timeout=timedelta(minutes=10)  # 10 minute timeout for approval
                            )
                            print(f"[HITL] wait_condition returned - resume_payload is now set session={chat_id}")
                            workflow.logger.info(f"[HITL] wait_condition returned - resume_payload is now set session={chat_id}")
                            
                            # Resume payload received, re-run activity with it
                            resume_payload_to_use = self.resume_payload
                            self.resume_payload = None  # Clear after use
                            
                            workflow.logger.info(f"[HITL] Resume received: resume_payload keys={list(resume_payload_to_use.keys()) if isinstance(resume_payload_to_use, dict) else 'N/A'} session={chat_id}")
                            
                            # Re-run activity with resume_payload
                            state_with_resume = state.copy()
                            state_with_resume["resume_payload"] = resume_payload_to_use
                            
                            # Re-run activity to continue execution with resume
                            workflow.logger.info(f"[HITL] Re-running activity with resume_payload session={chat_id}")
                            activity_input_continue = ChatActivityInput(chat_id=chat_id, state=state_with_resume)
                            result = await workflow.execute_activity(
                                run_chat_activity,
                                activity_input_continue,
                                schedule_to_close_timeout=timedelta(minutes=30),
                                start_to_close_timeout=timedelta(minutes=10),
                                heartbeat_timeout=timedelta(seconds=60),  # Increased from 30s for slow LLM responses
                                retry_policy=RetryPolicy(
                                    maximum_attempts=3,
                                    initial_interval=timedelta(seconds=1),
                                    backoff_coefficient=2.0,
                                    maximum_interval=timedelta(seconds=30),
                                ),
                            )
                            workflow.logger.info(f"[HITL] Activity re-run completed after resume: status={result.get('status')} has_response={result.get('has_response')} session={chat_id}")
                            workflow.logger.info(f"[HITL] Final response should be streaming to Redis channel chat:{tenant_id}:{chat_id} session={chat_id}")
                                
                        except TimeoutError:
                            workflow.logger.warning(f"[HITL] Timeout waiting for resume: timeout=10min session={chat_id}")
                            # Continue without resume - activity will handle gracefully
                    else:
                        print(f"[WORKFLOW] Activity did not return interrupted - status={result_status} - continuing normally session={chat_id}")
                        workflow.logger.info(f"[WORKFLOW] Activity did not return interrupted - status={result_status} - continuing normally session={chat_id}")
                    
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
                    
                    # Store activity result with run_id for correlation (non-stream mode uses query)
                    # This allows API to query workflow for result without waiting for completion
                    self.last_activity_result = {
                        "run_id": signal_data.get("run_id"),
                        "status": result.get("status") if isinstance(result, dict) else "unknown",
                        "response": result.get("response") if isinstance(result, dict) else None,
                        "interrupt": result.get("interrupt") if isinstance(result, dict) else None,
                        "error": result.get("error") if isinstance(result, dict) else None,
                        "timestamp": workflow.now().timestamp(),
                    }
                    workflow.logger.info(f"[WORKFLOW] Stored activity result for query: run_id={signal_data.get('run_id')}, status={self.last_activity_result['status']} session={chat_id}")
                    
                    # Update last activity time after successful processing
                    self.last_activity_time = workflow.now().timestamp()
                    result_status_for_log = result.get('status') if isinstance(result, dict) else 'unknown'
                    workflow.logger.info(f"[MESSAGE_PROCESS] Processed message session={chat_id} message_preview={signal_data.get('message', '')[:50]}... status={result_status_for_log} event_count={result.get('event_count', 'unknown') if isinstance(result, dict) else 'unknown'}")
                    
                except asyncio.CancelledError:
                    # Workflow was cancelled during activity execution
                    workflow.logger.info(f"Workflow cancelled during activity execution for session {chat_id}")
                    self.is_closing = True
                    raise  # Re-raise to allow Temporal to handle cancellation
                except Exception as e:
                    print(f"[WORKFLOW] [ERROR] Exception processing message for session {chat_id}: {e}")
                    print(f"[WORKFLOW] [ERROR] Exception type: {type(e).__name__}")
                    import traceback
                    print(f"[WORKFLOW] [ERROR] Traceback: {traceback.format_exc()}")
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
