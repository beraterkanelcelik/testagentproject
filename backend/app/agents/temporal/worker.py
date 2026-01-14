"""
Temporal worker that processes workflow tasks.
"""
import os
import sys
import django

# Configure Django settings before any Django imports
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'app.settings')
django.setup()

import asyncio
import signal
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from temporalio.client import Client
from temporalio.service import RetryConfig, KeepAliveConfig
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions
from app.agents.temporal.workflow import ChatWorkflow, DocumentProcessingWorkflow
from app.agents.temporal.activity import run_chat_activity
from app.documents.temporal.workflow import DocumentQueueWorkflow
from app.documents.temporal.activity import (
    extract_text_activity,
    chunk_text_activity,
    embed_chunks_activity,
    upsert_vectors_activity,
    update_document_status_activity,
    check_and_publish_queue_complete_activity,
)
from app.settings import TEMPORAL_ADDRESS, TEMPORAL_TASK_QUEUE
from app.core.logging import get_logger

logger = get_logger(__name__)

# Retry configuration for client connection
MAX_RETRY_ATTEMPTS = 60  # Try for up to 5 minutes
INITIAL_RETRY_DELAY = 5  # Start with 5 seconds
MAX_RETRY_DELAY = 30  # Max 30 seconds between retries


async def connect_with_retry():
    """
    Connect to Temporal with retry logic using SDK's built-in retry configuration.
    
    Returns:
        Client: Connected Temporal client
    """
    # Configure retry policy for client operations (in milliseconds)
    retry_config = RetryConfig(
        initial_interval_millis=1000,  # 1 second
        randomization_factor=0.2,
        multiplier=2.0,
        max_interval_millis=30000,  # 30 seconds
        max_elapsed_time_millis=300000,  # 5 minutes total
        max_retries=MAX_RETRY_ATTEMPTS,
    )
    
    # Configure keep-alive to maintain connection and detect drops (in milliseconds)
    keep_alive_config = KeepAliveConfig(
        interval_millis=30000,  # Check every 30 seconds
        timeout_millis=15000,  # Timeout after 15 seconds
    )
    
    attempt = 0
    while attempt < MAX_RETRY_ATTEMPTS:
        try:
            logger.info(f"Connecting to Temporal at {TEMPORAL_ADDRESS} (attempt {attempt + 1}/{MAX_RETRY_ATTEMPTS})")
            client = await Client.connect(
                TEMPORAL_ADDRESS,
                namespace="default",
                retry_config=retry_config,
                keep_alive_config=keep_alive_config,
            )
            logger.info("Successfully connected to Temporal")
            return client
        except Exception as e:
            attempt += 1
            if attempt >= MAX_RETRY_ATTEMPTS:
                logger.error(f"Failed to connect to Temporal after {MAX_RETRY_ATTEMPTS} attempts: {e}")
                raise
            
            # Exponential backoff: 5s, 5s, 10s, 15s, 20s, 25s, 30s, 30s, ...
            delay = min(INITIAL_RETRY_DELAY * (1 + (attempt - 1) // 2), MAX_RETRY_DELAY)
            logger.warning(f"Connection failed (attempt {attempt}/{MAX_RETRY_ATTEMPTS}): {e}. Retrying in {delay} seconds...")
            await asyncio.sleep(delay)
    
    # Should never reach here, but just in case
    raise RuntimeError(f"Failed to connect to Temporal after {MAX_RETRY_ATTEMPTS} attempts")


async def run_worker():
    """
    Run Temporal worker to process workflow tasks.
    
    Configured according to Temporal best practices:
    - Appropriate concurrency limits
    - Proper task queue isolation
    - Graceful shutdown handling
    """
    # LOW-1: Setup graceful shutdown with signal handlers
    shutdown_event = asyncio.Event()
    
    def handle_shutdown(signum, frame):
        logger.info(f"Received signal {signum}, initiating graceful shutdown...")
        shutdown_event.set()
    
    # Register signal handlers for graceful shutdown
    signal.signal(signal.SIGTERM, handle_shutdown)
    signal.signal(signal.SIGINT, handle_shutdown)
    
    chat_worker = None
    doc_worker = None
    activity_executor = None
    try:
        # Connect with retry logic
        client = await connect_with_retry()
        
        logger.info(f"Starting worker on task queue: {TEMPORAL_TASK_QUEUE}")
        
        # Configure sandbox restrictions to pass through Django and app modules
        # This allows workflows to import activities without triggering sandbox violations
        restrictions = SandboxRestrictions.default.with_passthrough_modules(
            "app.agents.temporal.activity",
            "app.documents.temporal.activity",
            "app.core.redis",
            "app.core.logging",
            "app.agents.functional.workflow",
            "app.agents.functional.models",
            "django",
            "django.db",
            "django.core",
        )
        
        # Create thread pool executor for synchronous activities
        # Document processing activities are synchronous (Django ORM, file I/O)
        # Chat activity is async (streaming, Redis pub/sub)
        # Reduced from 50 to 10 to save memory (each thread uses ~10-50MB)
        max_workers = 10
        activity_executor = ThreadPoolExecutor(
            max_workers=max_workers,
            thread_name_prefix="temporal-activity"
        )
        
        # Create chat worker (for chat workflows)
        # Include DocumentProcessingWorkflow for backward compatibility with old executions
        chat_worker = Worker(
            client,
            task_queue=TEMPORAL_TASK_QUEUE,
            workflows=[ChatWorkflow, DocumentProcessingWorkflow],
            activities=[run_chat_activity],
            # Configure worker concurrency (reduced to save memory)
            max_concurrent_workflow_tasks=5,
            max_concurrent_activities=max_workers,
            # Thread pool executor for synchronous activities
            activity_executor=activity_executor,
            # Use custom sandbox restrictions
            workflow_runner=SandboxedWorkflowRunner(restrictions=restrictions),
        )
        
        # Create document worker
        # Each document gets its own workflow instance for parallel processing
        doc_worker = Worker(
            client,
            task_queue="document-queue",
            workflows=[DocumentQueueWorkflow],
            activities=[
                extract_text_activity,
                chunk_text_activity,
                embed_chunks_activity,
                upsert_vectors_activity,
                update_document_status_activity,
                check_and_publish_queue_complete_activity,
            ],
            # Configure worker concurrency: allow multiple document workflows to run in parallel
            max_concurrent_workflow_tasks=2,  # Increased to handle multiple documents concurrently
            max_concurrent_activities=max_workers,  # Activities can run in parallel within a workflow
            # Thread pool executor for synchronous activities
            activity_executor=activity_executor,
            # Use custom sandbox restrictions
            workflow_runner=SandboxedWorkflowRunner(restrictions=restrictions),
        )
        
        logger.info(f"Workers started: chat queue={TEMPORAL_TASK_QUEUE}, document queue=document-queue")
        
        # Run all workers concurrently
        try:
            workers_to_run = [chat_worker.run(), doc_worker.run()]
            await asyncio.gather(
                *workers_to_run,
                shutdown_event.wait()
            )
        except asyncio.CancelledError:
            logger.info("Worker tasks cancelled")
            pass
    except KeyboardInterrupt:
        logger.info("Worker shutdown requested via KeyboardInterrupt")
    except Exception as e:
        logger.error(f"Fatal error running worker: {e}", exc_info=True)
        sys.exit(1)
    finally:
        # Graceful shutdown: wait for in-flight activities to complete
        if chat_worker:
            logger.info("Shutting down chat worker gracefully...")
            try:
                await chat_worker.shutdown()
                logger.info("Chat worker shutdown complete")
            except Exception as e:
                logger.error(f"Error during chat worker shutdown: {e}", exc_info=True)
        
        if doc_worker:
            logger.info("Shutting down document worker gracefully...")
            try:
                await doc_worker.shutdown()
                logger.info("Document worker shutdown complete")
            except Exception as e:
                logger.error(f"Error during document worker shutdown: {e}", exc_info=True)
        
        # Shutdown thread pool executor
        if activity_executor:
            logger.info("Shutting down activity executor...")
            activity_executor.shutdown(wait=True)
            logger.info("Activity executor shutdown complete")


if __name__ == "__main__":
    asyncio.run(run_worker())
