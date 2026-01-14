"""
Workflow management service for document processing.
Handles the single document queue workflow lifecycle and signal sending.
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
from app.documents.temporal.workflow import DocumentQueueWorkflow

logger = get_logger(__name__)

# Task queue for document workflows
DOCUMENT_QUEUE_TASK_QUEUE = "document-queue"


def get_document_workflow_id(document_id: int) -> str:
    """
    Generate workflow ID for a document.
    
    Args:
        document_id: Document ID
        
    Returns:
        Workflow ID string
    """
    return f"document-{document_id}"


async def signal_add_document(document_id: int, user_id: int) -> None:
    """
    Start or signal a document workflow.
    
    Creates a new workflow for the document if none exists, or sends a signal
    to add the document to the existing workflow's queue for re-processing.
    
    Args:
        document_id: Document ID to process
        user_id: Owner user ID
    """
    client = await get_temporal_client()
    workflow_id = get_document_workflow_id(document_id)
    
    try:
        # Try to get existing workflow for this document
        handle = client.get_workflow_handle(workflow_id)
        try:
            description = await handle.describe()
            
            # If workflow is running, send signal to add document to queue (for re-processing)
            if description.status.name == "RUNNING":
                await handle.signal(
                    "add_document_signal",
                    args=(document_id, user_id)
                )
                logger.info(f"Sent re-processing signal to existing workflow: document_id={document_id}, user_id={user_id}, workflow_id={workflow_id}")
                return
            
            # If workflow is completed or failed, start new one
            logger.info(f"Workflow for document {document_id} is {description.status.name}, starting new instance")
        except Exception:
            # Workflow doesn't exist, start new one
            logger.info(f"Workflow not found for document {document_id}, starting new instance")
        
        # Start workflow with document_id and user_id as parameters
        # Use ALLOW_DUPLICATE to allow re-processing the same document
        try:
            handle = await client.start_workflow(
                DocumentQueueWorkflow.run,
                args=(document_id, user_id),  # Pass document_id and user_id as required parameters
                id=workflow_id,
                task_queue=DOCUMENT_QUEUE_TASK_QUEUE,
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE,
                execution_timeout=timedelta(hours=24),  # Max 24 hours for document processing
                memo={"user_id": str(user_id), "document_id": str(document_id)},
                # Note: search_attributes removed - DocumentID and UserID need to be registered in Temporal namespace first
                # Memo provides visibility without requiring search attribute registration
            )
            
            logger.info(f"Started workflow for document: document_id={document_id}, user_id={user_id}, run_id={handle.result_run_id}, workflow_id={workflow_id}")
            # Wait a moment and check workflow status to verify it started
            try:
                description = await handle.describe()
                logger.info(f"Workflow status after start: {description.status.name}, workflow_id={description.id}, run_id={description.run_id}")
            except Exception as desc_error:
                logger.warning(f"Failed to describe workflow after start: {desc_error}")
        except Exception as start_error:
            # Workflow might have been started between our check and start_workflow call
            # Try to send signal to existing workflow
            try:
                handle = client.get_workflow_handle(workflow_id)
                description = await handle.describe()
                if description.status.name == "RUNNING":
                    await handle.signal(
                        "add_document_signal",
                        args=(document_id, user_id)
                    )
                    logger.info(f"Workflow started concurrently, sent signal: document_id={document_id}, user_id={user_id}")
                    return
            except Exception as signal_error:
                logger.error(f"Failed to start workflow and send signal: start_error={start_error}, signal_error={signal_error}", exc_info=True)
                raise start_error
        
    except Exception as e:
        logger.error(f"Error starting/signaling workflow for document {document_id}: {e}", exc_info=True)
        raise


