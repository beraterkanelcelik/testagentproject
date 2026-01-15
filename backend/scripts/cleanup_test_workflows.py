#!/usr/bin/env python
"""
Cleanup script to terminate test workflows created during scalability tests.

Run with: python manage.py shell < scripts/cleanup_test_workflows.py
Or: python manage.py runscript cleanup_test_workflows (if django-extensions installed)

This script identifies and terminates workflows created for test sessions.
"""
import os
import sys
import django
import asyncio

# Setup Django - ensure we're in the right directory
if not os.path.exists('manage.py'):
    # Try to find manage.py
    import pathlib
    script_dir = pathlib.Path(__file__).parent
    app_dir = script_dir.parent
    os.chdir(app_dir)
    sys.path.insert(0, str(app_dir))

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'app.settings')
django.setup()

from app.core.temporal import get_temporal_client
from app.agents.temporal.workflow_manager import get_workflow_id
from app.db.models.session import ChatSession
from app.core.logging import get_logger

logger = get_logger(__name__)


async def cleanup_test_workflows(dry_run: bool = False):
    """
    Cleanup test workflows.
    
    Args:
        dry_run: If True, only list workflows without terminating them
    """
    client = await get_temporal_client()
    
    # Find test sessions (sessions with "Scalability Test" or "scale_test" in title)
    test_sessions = ChatSession.objects.filter(
        title__icontains="Scalability Test"
    ) | ChatSession.objects.filter(
        title__icontains="scale_test"
    )
    
    test_session_ids = list(test_sessions.values_list('id', flat=True))
    logger.info(f"Found {len(test_session_ids)} test sessions")
    
    if not test_session_ids:
        logger.info("No test sessions found")
        return
    
    # Get user IDs for these sessions
    session_user_map = {
        s['id']: s['user_id'] 
        for s in ChatSession.objects.filter(id__in=test_session_ids).values('id', 'user_id')
    }
    
    terminated_count = 0
    not_found_count = 0
    error_count = 0
    
    for session_id in test_session_ids:
        user_id = session_user_map.get(session_id)
        if not user_id:
            continue
            
        workflow_id = get_workflow_id(user_id, session_id)
        
        try:
            handle = client.get_workflow_handle(workflow_id)
            description = await handle.describe()
            
            if description.status.name == "RUNNING":
                if dry_run:
                    logger.info(f"[DRY RUN] Would terminate workflow {workflow_id} for session {session_id}")
                    terminated_count += 1
                else:
                    try:
                        await handle.cancel()
                        logger.info(f"Terminated workflow {workflow_id} for session {session_id}")
                        terminated_count += 1
                    except Exception as e:
                        logger.error(f"Error terminating workflow {workflow_id}: {e}")
                        error_count += 1
            else:
                logger.debug(f"Workflow {workflow_id} is not running (status: {description.status.name})")
        except Exception as e:
            if "not found" in str(e).lower() or "does not exist" in str(e).lower():
                not_found_count += 1
                logger.debug(f"Workflow {workflow_id} not found (may have already closed)")
            else:
                logger.error(f"Error checking workflow {workflow_id}: {e}")
                error_count += 1
    
    logger.info(f"\n{'[DRY RUN] ' if dry_run else ''}Cleanup Summary:")
    logger.info(f"  Test sessions found: {len(test_session_ids)}")
    logger.info(f"  Workflows {'would be ' if dry_run else ''}terminated: {terminated_count}")
    logger.info(f"  Workflows not found: {not_found_count}")
    logger.info(f"  Errors: {error_count}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Cleanup test workflows")
    parser.add_argument("--dry-run", action="store_true", help="Only list workflows without terminating")
    args = parser.parse_args()
    
    asyncio.run(cleanup_test_workflows(dry_run=args.dry_run))
