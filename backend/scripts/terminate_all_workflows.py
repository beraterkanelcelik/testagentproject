#!/usr/bin/env python
"""
Terminate all running Temporal workflows.

This script will cancel all running workflows in the default namespace.
Use with caution - this will terminate ALL workflows, not just test ones.
"""
import os
import sys
import django
import asyncio

# Setup Django
if not os.path.exists('manage.py'):
    import pathlib
    script_dir = pathlib.Path(__file__).parent
    app_dir = script_dir.parent
    os.chdir(app_dir)
    sys.path.insert(0, str(app_dir))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'app.settings')
django.setup()

from app.core.temporal import get_temporal_client
from app.agents.temporal.workflow_manager import get_workflow_id, terminate_workflow
from app.db.models.session import ChatSession
from app.core.logging import get_logger

logger = get_logger(__name__)


async def terminate_all_running_workflows():
    """Terminate all running workflows by finding all sessions and terminating their workflows."""
    client = await get_temporal_client()
    
    # Get all sessions with their user IDs
    sessions = ChatSession.objects.select_related('user').all()
    logger.info(f"Found {sessions.count()} total sessions")
    
    terminated_count = 0
    not_found_count = 0
    error_count = 0
    already_closed_count = 0
    
    for session in sessions:
        try:
            workflow_id = get_workflow_id(session.user.id, session.id)
            handle = client.get_workflow_handle(workflow_id)
            
            try:
                description = await handle.describe()
                if description.status.name == "RUNNING":
                    await handle.cancel()
                    logger.info(f"Terminated workflow {workflow_id} for session {session.id}")
                    terminated_count += 1
                else:
                    already_closed_count += 1
                    logger.debug(f"Workflow {workflow_id} already closed (status: {description.status.name})")
            except Exception as e:
                error_str = str(e).lower()
                if "not found" in error_str or "does not exist" in error_str:
                    not_found_count += 1
                else:
                    logger.error(f"Error checking workflow {workflow_id}: {e}")
                    error_count += 1
        except Exception as e:
            logger.error(f"Error processing session {session.id}: {e}")
            error_count += 1
        
        # Progress indicator every 100 sessions
        if (terminated_count + not_found_count + already_closed_count + error_count) % 100 == 0:
            logger.info(f"Progress: {terminated_count} terminated, {not_found_count} not found, {already_closed_count} already closed, {error_count} errors")
    
    logger.info(f"\nTermination Summary:")
    logger.info(f"  Total sessions checked: {sessions.count()}")
    logger.info(f"  Workflows terminated: {terminated_count}")
    logger.info(f"  Workflows not found: {not_found_count}")
    logger.info(f"  Workflows already closed: {already_closed_count}")
    logger.info(f"  Errors: {error_count}")


if __name__ == "__main__":
    print("⚠️  WARNING: This will terminate ALL running workflows!")
    print("Press Ctrl+C within 5 seconds to cancel...")
    try:
        import time
        time.sleep(5)
    except KeyboardInterrupt:
        print("\nCancelled.")
        sys.exit(0)
    
    print("\nStarting termination...")
    asyncio.run(terminate_all_running_workflows())
