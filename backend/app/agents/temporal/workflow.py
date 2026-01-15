"""
Temporal workflow definitions for chat execution.
Long-running workflow per chat session using signals.
"""
import asyncio
import os
from dataclasses import dataclass
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy
from typing import Dict, Any, Optional
from collections import deque

# Import activity - sandbox restrictions configured in worker to allow this
from app.agents.temporal.activity import run_chat_activity


# Read timeout from environment variable directly (cannot import from app.settings due to sandbox restrictions)
# Workflows must be deterministic and cannot import Django settings which may have side effects
TEMPORAL_APPROVAL_TIMEOUT_MINUTES = int(os.getenv('TEMPORAL_APPROVAL_TIMEOUT_MINUTES', '10'))
TEMPORAL_ACTIVITY_TIMEOUT_MINUTES = int(os.getenv('TEMPORAL_ACTIVITY_TIMEOUT_MINUTES', '10'))


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
        # Track last activity result for query
        self.last_activity_result: Optional[Dict[str, Any]] = None
    
    @workflow.signal
    def new_message(self, message: str, plan_steps: Optional[list] = None, flow: str = "main", run_id: Optional[str] = None, parent_message_id: Optional[int] = None) -> None:
        """
        Signal handler for new messages.
        
        Args:
            message: Message content
            plan_steps: Optional plan steps
            flow: Flow type
            run_id: Optional correlation ID (ensures stable dedupe identity)
            parent_message_id: Optional parent user message ID for correlation
        """
        if self.is_closing:
            workflow.logger.warning("Workflow is closing, ignoring new message signal")
            return
        
        # Generate stable message hash for deduplication
        # Priority: run_id (most stable) > parent_message_id > content hash
        if run_id:
            message_hash = f"run:{run_id}"
        elif parent_message_id:
            message_hash = f"msg:{parent_message_id}"
        else:
            import hashlib
            content = f"{message}:{plan_steps}:{flow}"
            message_hash = hashlib.sha256(content.encode()).hexdigest()[:16]
            workflow.logger.warning(f"[DEDUPE] No run_id or parent_message_id provided, using content hash session={workflow.info().workflow_id}")
        
        # Check for duplicates atomically
        if message_hash in self.processed_messages:
            workflow.logger.warning(f"[DUPLICATE_SIGNAL] Ignoring duplicate signal - message already processed session={workflow.info().workflow_id} hash={message_hash}")
            return
        
        if any(msg.get("_hash") == message_hash for msg in self.pending_messages):
            workflow.logger.warning(f"[DUPLICATE_SIGNAL] Ignoring duplicate signal - message already in queue session={workflow.info().workflow_id} hash={message_hash}")
            return
        
        # Add message to queue
        signal_data = {
            "message": message,
            "plan_steps": plan_steps,
            "flow": flow,
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
        return await self._run_v2(chat_id, initial_state)

    async def _run_v2(
        self,
        chat_id: int,
        initial_state: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Workflow implementation with improved message processing and synchronization.
        """
        workflow.logger.info(f"[WORKFLOW_V2] Starting V2 workflow for session {chat_id}")
        
        # Store initial state
        self.initial_state = initial_state or {}
        self.last_activity_time = workflow.now().timestamp()
        
        inactivity_timeout = timedelta(minutes=5)
        
        while not self.is_closing:
            # Check for inactivity
            if self.last_activity_time:
                elapsed = timedelta(seconds=workflow.now().timestamp() - self.last_activity_time)
                if elapsed >= inactivity_timeout:
                    workflow.logger.info(f"Workflow inactive for {elapsed}, closing session {chat_id}")
                    self.is_closing = True
                    break
            
            # Wait for messages with proper synchronization
            await workflow.wait_condition(
                lambda: len(self.pending_messages) > 0 or self.resume_payload is not None or self.is_closing
            )
            
            if self.resume_payload is not None:
                # Handle resume
                payload = self.resume_payload
                self.resume_payload = None
                
                # Get state from last processed message or use default
                user_id = self.initial_state.get("user_id")
                tenant_id = self.initial_state.get("tenant_id") or user_id
                
                state_with_resume = {
                    "user_id": user_id,
                    "session_id": chat_id,
                    "resume_payload": payload,
                    "tenant_id": tenant_id,
                    "org_slug": self.initial_state.get("org_slug"),
                    "org_roles": self.initial_state.get("org_roles", []),
                    "app_roles": self.initial_state.get("app_roles", []),
                }
                
                result = await workflow.execute_activity(
                    run_chat_activity,
                    ChatActivityInput(chat_id=chat_id, state=state_with_resume),
                    start_to_close_timeout=timedelta(minutes=TEMPORAL_ACTIVITY_TIMEOUT_MINUTES),
                    heartbeat_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(
                        maximum_attempts=3,
                        initial_interval=timedelta(seconds=1),
                        maximum_interval=timedelta(seconds=10),
                        backoff_coefficient=2.0
                    )
                )
                
                if result.get("status") == "interrupted":
                    continue
                else:
                    self.last_activity_time = workflow.now().timestamp()
            
            elif self.pending_messages:
                # Process next message
                signal_data = self.pending_messages.popleft()
                message_hash = signal_data.get("_hash")
                
                # Check for duplicates
                if message_hash and message_hash in self.processed_messages:
                    continue
                
                if message_hash:
                    self.processed_messages.add(message_hash)
                    # Cleanup old hashes (keep last 100)
                    if len(self.processed_messages) > 100:
                        workflow.logger.debug(f"Clearing processed_messages set (size={len(self.processed_messages)})")
                        self.processed_messages = set(list(self.processed_messages)[-100:])
                
                # Prepare state
                user_id = self.initial_state.get("user_id")
                tenant_id = self.initial_state.get("tenant_id") or user_id
                
                state = {
                    "user_id": user_id,
                    "session_id": chat_id,
                    "message": signal_data.get("message", ""),
                    "plan_steps": signal_data.get("plan_steps"),
                    "flow": signal_data.get("flow", "main"),
                    "run_id": signal_data.get("run_id"),
                    "parent_message_id": signal_data.get("parent_message_id"),
                    "tenant_id": tenant_id,
                    "org_slug": self.initial_state.get("org_slug"),
                    "org_roles": self.initial_state.get("org_roles", []),
                    "app_roles": self.initial_state.get("app_roles", []),
                }
                
                # Execute activity
                result = await workflow.execute_activity(
                    run_chat_activity,
                    ChatActivityInput(chat_id=chat_id, state=state),
                    start_to_close_timeout=timedelta(minutes=TEMPORAL_ACTIVITY_TIMEOUT_MINUTES),
                    heartbeat_timeout=timedelta(seconds=30),
                    retry_policy=RetryPolicy(
                        maximum_attempts=3,
                        initial_interval=timedelta(seconds=1),
                        maximum_interval=timedelta(seconds=10),
                        backoff_coefficient=2.0
                    )
                )
                
                if result.get("status") == "interrupted":
                    # Wait for resume
                    await workflow.wait_condition(
                        lambda: self.resume_payload is not None,
                        timeout=timedelta(minutes=TEMPORAL_APPROVAL_TIMEOUT_MINUTES)
                    )
                    continue
                elif result.get("status") == "completed":
                    self.last_activity_time = workflow.now().timestamp()
                    continue
        
        workflow.logger.info(f"Chat workflow V2 closing for session {chat_id}")
        return {
            "status": "closed",
            "chat_id": chat_id,
            "reason": "inactivity_timeout" if self.is_closing else "normal",
            "version": "v2"
        }
