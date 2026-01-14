"""
Workflow management service for chat sessions.
Handles workflow lifecycle: creation, signal sending, and cleanup.
"""
import os
import django
# Ensure Django is set up for imports
if not hasattr(django, 'apps') or not django.apps.apps.ready:
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'app.settings')
    django.setup()

from typing import Optional, Dict, Any
from datetime import timedelta
from temporalio.client import Client, WorkflowHandle
from temporalio.common import WorkflowIDReusePolicy
from app.core.temporal import get_temporal_client
from app.core.logging import get_logger
from app.agents.temporal.workflow import ChatWorkflow
from app.settings import TEMPORAL_TASK_QUEUE

logger = get_logger(__name__)


def get_workflow_id(user_id: int, session_id: int) -> str:
    """
    Generate consistent workflow ID for a chat session.
    
    Args:
        user_id: User ID
        session_id: Chat session ID
        
    Returns:
        Workflow ID string
    """
    return f"chat-{user_id}-{session_id}"


async def get_or_create_workflow(
    user_id: int,
    session_id: int,
    initial_state: Optional[Dict[str, Any]] = None
) -> WorkflowHandle:
    """
    Get existing workflow or create new one for a chat session.
    Uses signal_with_start pattern to handle both cases.
    Always uses streaming mode.
    
    Args:
        user_id: User ID
        session_id: Chat session ID
        initial_state: Optional initial state (for first message)
        
    Returns:
        WorkflowHandle for the session workflow
    """
    client = await get_temporal_client()
    workflow_id = get_workflow_id(user_id, session_id)
    
    # CRITICAL: Ensure initial_state always has user_id and tenant_id
    # This guarantees the activity can build the correct Redis channel
    if initial_state is None:
        initial_state = {}
    if "user_id" not in initial_state:
        initial_state["user_id"] = user_id
        logger.debug(f"[WORKFLOW_MANAGER] Added user_id={user_id} to initial_state for session {session_id}")
    if "tenant_id" not in initial_state:
        initial_state["tenant_id"] = str(user_id)  # Use user_id as tenant_id to match SSE subscription
        logger.debug(f"[WORKFLOW_MANAGER] Added tenant_id={user_id} to initial_state for session {session_id}")
    
    try:
        # Try to get existing workflow
        handle = client.get_workflow_handle(workflow_id)
        # Check if it's still running
        try:
            description = await handle.describe()
            if description.status.name == "RUNNING":
                logger.info(f"Found existing workflow {workflow_id} for session {session_id}")
                # CRITICAL: If workflow exists, we still need to send the signal
                # The caller expects get_or_create_workflow to handle signaling
                message = initial_state.get("message", "") if initial_state else ""
                plan_steps = initial_state.get("plan_steps") if initial_state else None
                flow = initial_state.get("flow", "main") if initial_state else "main"
                
                # Only send signal if there's an actual message to process
                # Don't send empty signals which would cause duplicate processing
                if message:
                    try:
                        # Send signal to existing workflow
                        # Temporal client operations should work across event loops
                        # Use asyncio.ensure_future to ensure it runs in current loop if needed
                        try:
                            # Extract correlation IDs from initial_state for stable dedupe
                            run_id = initial_state.get("run_id") if initial_state else None
                            parent_message_id = initial_state.get("parent_message_id") if initial_state else None
                            await handle.signal("new_message", args=(message, plan_steps, flow, run_id, parent_message_id))
                            logger.info(f"[SIGNAL_SEND] Sent message signal to existing workflow {workflow_id} session={session_id} run_id={run_id} message_preview={message[:50]}...")
                        except RuntimeError as loop_error:
                            error_str = str(loop_error)
                            if "different loop" in error_str or "attached to a different loop" in error_str or "Future" in error_str:
                                # Event loop mismatch - try to get a fresh client in current loop
                                logger.warning(
                                    f"[SIGNAL_ERROR] Event loop mismatch detected for workflow {workflow_id}. "
                                    f"Attempting to get fresh Temporal client in current event loop context."
                                )
                                # Get a fresh client (should work in current loop)
                                fresh_client = await get_temporal_client()
                                fresh_handle = fresh_client.get_workflow_handle(workflow_id)
                                run_id = initial_state.get("run_id") if initial_state else None
                                parent_message_id = initial_state.get("parent_message_id") if initial_state else None
                                await fresh_handle.signal("new_message", args=(message, plan_steps, flow, run_id, parent_message_id))
                                logger.info(f"[SIGNAL_SEND] Sent message signal via fresh client to workflow {workflow_id} session={session_id} run_id={run_id} message_preview={message[:50]}...")
                            else:
                                raise
                    except Exception as e:
                        error_str = str(e)
                        if "different loop" in error_str or "attached to a different loop" in error_str or "Future" in error_str:
                            logger.error(
                                f"[SIGNAL_ERROR] Event loop mismatch when sending signal to workflow {workflow_id}: {e}. "
                                f"This usually means Temporal client was created in a different event loop. "
                                f"Re-raising to trigger fallback."
                            )
                            # Re-raise to trigger fallback in caller
                            raise
                        else:
                            # Other errors - log and re-raise
                            logger.error(f"[SIGNAL_ERROR] Unexpected error sending signal to workflow {workflow_id}: {e}", exc_info=True)
                            raise
                else:
                    logger.debug(f"[SIGNAL_SKIP] Skipping signal for existing workflow {workflow_id} - no message to send")
                return handle
        except Exception as e:
            # Log the exception for debugging
            if "different loop" not in str(e) and "attached to a different loop" not in str(e):
                logger.debug(f"Workflow {workflow_id} doesn't exist or is not running: {e}")
            # Workflow doesn't exist or is not running, will create new one
            pass
        
        # Always use signal_with_start pattern to avoid race conditions
        # This ensures consistent behavior whether workflow exists or not
        message = initial_state.get("message", "") if initial_state else ""
        plan_steps = initial_state.get("plan_steps") if initial_state else None
        flow = initial_state.get("flow", "main") if initial_state else "main"
        
        # CRITICAL: Only create workflow if there's an actual message to process
        # Don't create workflows with empty signals - they cause duplicate processing
        if not message:
            logger.warning(f"[WORKFLOW_SKIP] Skipping workflow creation for session {session_id} - no message to process")
            raise ValueError(f"Cannot create workflow without a message for session {session_id}")
        
        logger.info(f"Creating new workflow {workflow_id} with signal_with_start for session {session_id}")
        try:
            # Extract correlation IDs from initial_state for stable dedupe
            run_id = initial_state.get("run_id") if initial_state else None
            parent_message_id = initial_state.get("parent_message_id") if initial_state else None
            handle = await client.start_workflow(
                ChatWorkflow.run,
                args=(session_id, initial_state or {}),
                id=workflow_id,
                task_queue=TEMPORAL_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.REJECT_DUPLICATE,
                execution_timeout=timedelta(hours=24),  # Max 24 hours for chat session
                memo={"user_id": str(user_id), "session_id": str(session_id)},
                # Note: search_attributes removed - would require Temporal namespace configuration
                # Use memo instead for workflow metadata
                start_signal="new_message",
                start_signal_args=(message, plan_steps, flow, run_id, parent_message_id),
            )
        except Exception as create_error:
            # Workflow might have been created between our check and start_workflow call
            # Try to get it and send signal
            logger.warning(f"Failed to create workflow {workflow_id} (might already exist): {create_error}")
            try:
                handle = client.get_workflow_handle(workflow_id)
                description = await handle.describe()
                if description.status.name == "RUNNING":
                    # Workflow exists, send signal
                    run_id = initial_state.get("run_id") if initial_state else None
                    parent_message_id = initial_state.get("parent_message_id") if initial_state else None
                    await handle.signal("new_message", args=(message, plan_steps, flow, run_id, parent_message_id))
                    logger.info(f"[SIGNAL_SEND] Sent message signal to existing workflow {workflow_id} session={session_id} run_id={run_id} message_preview={message[:50]}...")
                    return handle
            except Exception as get_error:
                logger.error(f"Failed to get existing workflow {workflow_id}: {get_error}", exc_info=True)
                raise create_error  # Re-raise original error
            raise create_error
        
        # Store workflow ID in session metadata (use sync_to_async for Django ORM in async context)
        try:
            from asgiref.sync import sync_to_async
            from app.db.models.session import ChatSession
            
            @sync_to_async
            def store_workflow_id():
                session = ChatSession.objects.get(id=session_id, user_id=user_id)
                if not session.metadata:
                    session.metadata = {}
                session.metadata["workflow_id"] = workflow_id
                session.save(update_fields=["metadata"])
                return True
            
            await store_workflow_id()
            logger.debug(f"Stored workflow_id {workflow_id} in session {session_id} metadata")
        except Exception as e:
            logger.warning(f"Failed to store workflow_id in session metadata: {e}")
        
        return handle
        
    except Exception as e:
        logger.error(f"Error getting/creating workflow for session {session_id}: {e}", exc_info=True)
        raise


async def send_message_signal(
    user_id: int,
    session_id: int,
    message: str,
    plan_steps: Optional[list] = None,
    flow: str = "main"
) -> bool:
    """
    Send a message signal to the session workflow.
    
    Args:
        user_id: User ID
        session_id: Chat session ID
        message: Message content
        plan_steps: Optional plan steps
        flow: Flow type
        
    Returns:
        True if signal sent successfully, False otherwise
    """
    try:
        client = await get_temporal_client()
        workflow_id = get_workflow_id(user_id, session_id)
        
        # Get workflow handle
        handle = client.get_workflow_handle(workflow_id)
        
        # Send signal using signal name as string with args parameter
        await handle.signal(
            "new_message",
            args=(message, plan_steps, flow)
        )
        
        logger.info(f"[SIGNAL_SEND] Sent message signal to workflow {workflow_id} session={session_id} message_preview={message[:50]}... flow={flow}")
        return True
        
    except Exception as e:
        logger.error(f"Error sending message signal to session {session_id}: {e}", exc_info=True)
        # If workflow doesn't exist, create it with signal_with_start
        try:
            await get_or_create_workflow(
                user_id,
                session_id,
                initial_state={
                    "user_id": user_id,
                    "session_id": session_id,
                    "message": message,
                    "plan_steps": plan_steps,
                    "flow": flow,
                }
            )
            return True
        except Exception as create_error:
            logger.error(f"Failed to create workflow for session {session_id}: {create_error}", exc_info=True)
            return False


async def terminate_workflow(user_id: int, session_id: int) -> bool:
    """
    Terminate the workflow for a chat session.
    
    Args:
        user_id: User ID
        session_id: Chat session ID
        
    Returns:
        True if workflow was terminated, False if not found or already terminated
    """
    try:
        client = await get_temporal_client()
        workflow_id = get_workflow_id(user_id, session_id)
        
        # Get workflow handle
        handle = client.get_workflow_handle(workflow_id)
        
        # Check if workflow is running
        try:
            description = await handle.describe()
            if description.status.name == "RUNNING":
                # Cancel workflow gracefully (allows cleanup)
                await handle.cancel()
                logger.info(f"Cancelled workflow {workflow_id} for session {session_id}")
                return True
            else:
                logger.debug(f"Workflow {workflow_id} is not running (status: {description.status.name})")
                return False
        except Exception as e:
            # Workflow doesn't exist or can't be described
            logger.debug(f"Workflow {workflow_id} not found or cannot be described: {e}")
            return False
            
    except Exception as e:
        logger.warning(f"Error terminating workflow for session {session_id}: {e}")
        return False


async def terminate_all_workflows_for_user(user_id: int) -> int:
    """
    Terminate all workflows for a user.
    
    Args:
        user_id: User ID
        
    Returns:
        Number of workflows terminated
    """
    try:
        from asgiref.sync import sync_to_async
        from app.db.models.session import ChatSession
        
        # Get all sessions for user
        @sync_to_async
        def get_user_sessions():
            return list(ChatSession.objects.filter(user_id=user_id).values_list('id', flat=True))
        
        session_ids = await get_user_sessions()
        
        terminated_count = 0
        for session_id in session_ids:
            if await terminate_workflow(user_id, session_id):
                terminated_count += 1
        
        logger.info(f"Terminated {terminated_count} workflows for user {user_id}")
        return terminated_count
        
    except Exception as e:
        logger.error(f"Error terminating workflows for user {user_id}: {e}", exc_info=True)
        return 0
