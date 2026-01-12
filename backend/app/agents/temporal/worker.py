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
from datetime import timedelta
from temporalio.client import Client
from temporalio.service import RetryConfig, KeepAliveConfig
from temporalio.worker import Worker
from temporalio.worker.workflow_sandbox import SandboxedWorkflowRunner, SandboxRestrictions
from app.agents.temporal.workflow import ChatWorkflow
from app.agents.temporal.activity import run_chat_activity
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
    """
    try:
        # Connect with retry logic
        client = await connect_with_retry()
        
        logger.info(f"Starting worker on task queue: {TEMPORAL_TASK_QUEUE}")
        
        # Configure sandbox restrictions to pass through Django and app modules
        # This allows workflows to import activities without triggering sandbox violations
        restrictions = SandboxRestrictions.default.with_passthrough_modules(
            "app.agents.temporal.activity",
            "app.core.redis",
            "app.core.logging",
            "app.agents.functional.workflow",
            "app.agents.functional.models",
            "django",
            "django.db",
            "django.core",
        )
        
        worker = Worker(
            client,
            task_queue=TEMPORAL_TASK_QUEUE,
            workflows=[ChatWorkflow],
            activities=[run_chat_activity],
            # Configure worker concurrency (default is 100, adjust based on resources)
            max_concurrent_workflow_tasks=50,
            max_concurrent_activities=50,
            # Use custom sandbox restrictions
            workflow_runner=SandboxedWorkflowRunner(restrictions=restrictions),
        )
        
        logger.info("Worker started, waiting for tasks...")
        await worker.run()
    except KeyboardInterrupt:
        logger.info("Worker shutdown requested")
    except Exception as e:
        logger.error(f"Fatal error running worker: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(run_worker())
