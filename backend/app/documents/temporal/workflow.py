"""
Temporal workflow for document processing.
Single long-running workflow that processes documents sequentially from an internal queue.
"""
import os
from datetime import timedelta
from temporalio import workflow
from temporalio.common import RetryPolicy
from typing import Dict, Any, List, Optional

# Import activities - sandbox restrictions configured in worker
from app.documents.temporal.activity import (
    extract_text_activity,
    chunk_text_activity,
    embed_chunks_activity,
    upsert_vectors_activity,
    update_document_status_activity,
    check_and_publish_queue_complete_activity,
)

# Read timeout from environment variable directly (cannot import from app.settings due to sandbox restrictions)
TEMPORAL_ACTIVITY_TIMEOUT_MINUTES = int(os.getenv('TEMPORAL_DOCUMENT_ACTIVITY_TIMEOUT_MINUTES', '30'))


@workflow.defn
class DocumentQueueWorkflow:
    """
    Per-document workflow that processes a specific document.
    
    Each workflow instance handles one document (identified by document_id).
    Can accept additional processing requests via signals for re-processing the same document.
    
    Steps for each document:
    1. Extract text from document
    2. Chunk extracted text
    3. Generate embeddings for chunks
    4. Upsert vectors to vector store
    5. Update document status
    """
    
    def __init__(self):
        """Initialize workflow state."""
        self.queue: List[Dict[str, int]] = []
        self.processing: Optional[Dict[str, int]] = None
        # Track pending count for this document (for re-processing)
        self.pending_count: int = 0
    
    @workflow.signal
    def add_document_signal(self, document_id: int, user_id: int) -> None:
        """
        Add document to processing queue via signal (for re-processing).
        
        Args:
            document_id: Document ID to process
            user_id: Owner user ID
        """
        workflow.logger.info(f"[DOC_WORKFLOW] Adding document to queue for re-processing: document_id={document_id}, user_id={user_id}")
        self.queue.append({"document_id": document_id, "user_id": user_id})
        self.pending_count += 1
        workflow.logger.debug(f"[DOC_WORKFLOW] Document {document_id} added to queue, pending_count={self.pending_count}")
    
    async def _process_document(self, document_id: int, user_id: int) -> Dict[str, Any]:
        """
        Process a single document through the full indexing pipeline.
        
        Args:
            document_id: Document ID to process
            user_id: Owner user ID
            
        Returns:
            Dictionary with processing result
        """
        workflow.logger.info(f"[DOC_QUEUE] Starting document processing for document_id={document_id}, user_id={user_id}")
        
        try:
            # Publish status update that processing has started (before first activity)
            # This ensures frontend gets immediate feedback that workflow is running
            try:
                await workflow.execute_activity(
                    update_document_status_activity,
                    {
                        "document_id": document_id,
                        "user_id": user_id,
                        "status": "QUEUED",  # Keep as QUEUED until extraction starts
                    },
                    start_to_close_timeout=timedelta(seconds=10),
                    heartbeat_timeout=timedelta(seconds=5),
                    retry_policy=RetryPolicy(
                        maximum_attempts=1,  # Don't retry status updates
                        initial_interval=timedelta(seconds=1),
                    ),
                )
            except Exception as e:
                workflow.logger.warning(f"[DOC_QUEUE] Failed to publish initial status update: {e}")
            
            # Step 1: Extract text
            workflow.logger.info(f"[DOC_QUEUE] Step 1: Extracting text for document_id={document_id}")
            extract_result = await workflow.execute_activity(
                extract_text_activity,
                {"document_id": document_id, "user_id": user_id},
                start_to_close_timeout=timedelta(minutes=30),  # Large PDFs may take time
                heartbeat_timeout=timedelta(minutes=2),  # Faster failure detection
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(seconds=5),
                    backoff_coefficient=2.0,
                    maximum_interval=timedelta(seconds=60),
                ),
            )
            
            if not extract_result.get("success"):
                # Check if document was deleted
                if extract_result.get("document_deleted"):
                    workflow.logger.warning(f"[DOC_QUEUE] Document {document_id} was deleted, skipping processing")
                    return {
                        "success": False,
                        "document_id": document_id,
                        "skipped": True,
                        "reason": "document_deleted",
                    }
                raise Exception(f"Text extraction failed: {extract_result.get('error')}")
            
            # Step 2: Chunk text
            workflow.logger.info(f"[DOC_QUEUE] Step 2: Chunking text for document_id={document_id}")
            chunk_result = await workflow.execute_activity(
                chunk_text_activity,
                {"document_id": document_id, "user_id": user_id},
                start_to_close_timeout=timedelta(minutes=5),  # Chunking is typically fast
                heartbeat_timeout=timedelta(minutes=1),  # Faster failure detection
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(seconds=5),
                    backoff_coefficient=2.0,
                    maximum_interval=timedelta(seconds=60),
                ),
            )
            
            if not chunk_result.get("success"):
                raise Exception(f"Text chunking failed: {chunk_result.get('error')}")
            
            chunk_count = chunk_result.get("chunk_count", 0)
            workflow.logger.info(f"[DOC_QUEUE] Created {chunk_count} chunks for document_id={document_id}")
            
            # Step 3: Generate embeddings
            workflow.logger.info(f"[DOC_QUEUE] Step 3: Generating embeddings for document_id={document_id}")
            embed_result = await workflow.execute_activity(
                embed_chunks_activity,
                {"document_id": document_id, "user_id": user_id},
                start_to_close_timeout=timedelta(minutes=15),  # API calls may take time
                heartbeat_timeout=timedelta(minutes=2),  # Faster failure detection
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(seconds=5),
                    backoff_coefficient=2.0,
                    maximum_interval=timedelta(seconds=60),
                ),
            )
            
            if not embed_result.get("success"):
                raise Exception(f"Embedding generation failed: {embed_result.get('error')}")
            
            # Step 4: Upsert vectors
            workflow.logger.info(f"[DOC_QUEUE] Step 4: Upserting vectors for document_id={document_id}")
            upsert_result = await workflow.execute_activity(
                upsert_vectors_activity,
                {"document_id": document_id, "user_id": user_id},
                start_to_close_timeout=timedelta(minutes=10),  # Database operations
                heartbeat_timeout=timedelta(minutes=2),  # Faster failure detection
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(seconds=5),
                    backoff_coefficient=2.0,
                    maximum_interval=timedelta(seconds=60),
                ),
            )
            
            if not upsert_result.get("success"):
                raise Exception(f"Vector upsert failed: {upsert_result.get('error')}")
            
            # Step 5: Update document status to READY
            workflow.logger.info(f"[DOC_QUEUE] Step 5: Updating document status for document_id={document_id}")
            update_result = await workflow.execute_activity(
                update_document_status_activity,
                {
                    "document_id": document_id,
                    "user_id": user_id,
                    "status": "READY",
                    "chunks_count": chunk_count,
                },
                start_to_close_timeout=timedelta(minutes=5),
                heartbeat_timeout=timedelta(minutes=1),
                retry_policy=RetryPolicy(
                    maximum_attempts=3,
                    initial_interval=timedelta(seconds=1),
                    backoff_coefficient=2.0,
                    maximum_interval=timedelta(seconds=10),
                ),
            )
            
            workflow.logger.info(f"[DOC_QUEUE] Document processing completed successfully for document_id={document_id}")
            
            return {
                "success": True,
                "document_id": document_id,
                "chunks_count": chunk_count,
                "status": "READY",
            }
            
        except Exception as e:
            workflow.logger.error(f"[DOC_QUEUE] Document processing failed for document_id={document_id}: {e}", exc_info=True)
            
            # Update document status to FAILED
            try:
                await workflow.execute_activity(
                    update_document_status_activity,
                    {
                        "document_id": document_id,
                        "user_id": user_id,
                        "status": "FAILED",
                        "error_message": str(e),
                    },
                    start_to_close_timeout=timedelta(minutes=5),
                    heartbeat_timeout=timedelta(minutes=1),  # Keep current
                    retry_policy=RetryPolicy(
                        maximum_attempts=2,
                        initial_interval=timedelta(seconds=1),
                        backoff_coefficient=2.0,
                        maximum_interval=timedelta(seconds=10),
                    ),
                )
                
                # Check if all documents for this user are complete (including this failed one)
                try:
                    check_result = await workflow.execute_activity(
                        check_and_publish_queue_complete_activity,
                        user_id,
                        start_to_close_timeout=timedelta(seconds=30),
                        heartbeat_timeout=timedelta(seconds=10),
                        retry_policy=RetryPolicy(
                            maximum_attempts=2,
                            initial_interval=timedelta(seconds=1),
                            backoff_coefficient=2.0,
                            maximum_interval=timedelta(seconds=5),
                        ),
                    )
                    if check_result.get("published"):
                        workflow.logger.info(
                            f"[DOC_WORKFLOW] Published queue_complete for user {user_id} "
                            f"after document {document_id} failed ({check_result.get('complete_documents')}/{check_result.get('total_documents')} complete)"
                        )
                except Exception as check_error:
                    workflow.logger.warning(f"[DOC_WORKFLOW] Failed to check/publish queue_complete after failure: {check_error}")
                    
            except Exception as update_error:
                workflow.logger.error(f"[DOC_QUEUE] Failed to update document status to FAILED: {update_error}")
            
            raise
    
    @workflow.run
    async def run(self, document_id: int, user_id: int) -> Dict[str, Any]:
        """
        Process a document workflow.
        
        This workflow processes the initial document immediately, then waits for
        additional signals to re-process the same document if needed.
        
        Args:
            document_id: Document ID to process
            user_id: Owner user ID
        
        Returns:
            Dictionary with processing summary
        """
        workflow.logger.info(
            f"[DOC_WORKFLOW] Document workflow started for document_id={document_id}, user_id={user_id}. "
            f"Workflow ID: {workflow.info().workflow_id}, Run ID: {workflow.info().run_id}"
        )
        
        # Process the initial document immediately
        initial_document = {"document_id": document_id, "user_id": user_id}
        self.queue.append(initial_document)
        self.pending_count = 1
        
        processed_count = 0
        
        # Process documents from queue (initial document + any re-processing requests)
        while True:
            if not self.queue:
                # Queue is empty, wait for re-processing signals or complete
                workflow.logger.info(f"[DOC_WORKFLOW] Queue empty for document_id={document_id}, waiting for re-processing signals...")
                try:
                    # Wait for re-processing signals (shorter timeout since initial doc is done)
                    await workflow.wait_condition(lambda: len(self.queue) > 0, timeout=timedelta(minutes=1))
                    workflow.logger.info(f"[DOC_WORKFLOW] Re-processing signal received, queue_size={len(self.queue)}")
                except TimeoutError:
                    # No re-processing requested, complete workflow
                    workflow.logger.info(f"[DOC_WORKFLOW] No re-processing requested, completing workflow for document_id={document_id}. Processed {processed_count} times.")
                    
                    # Note: queue_complete is already published when document finishes processing above
                    # No need to publish again here
                    
                    return {
                        "success": True,
                        "document_id": document_id,
                        "processed_count": processed_count,
                        "status": "completed"
                    }
            
            # Process next document from queue
            if self.queue:
                document = self.queue.pop(0)
                self.processing = document
                
                doc_id = document["document_id"]
                doc_user_id = document["user_id"]
                
                # Verify this is the same document (safety check)
                if doc_id != document_id:
                    workflow.logger.warning(
                        f"[DOC_WORKFLOW] Mismatch: workflow for document_id={document_id} but queue has document_id={doc_id}. "
                        f"Processing {doc_id} anyway."
                    )
                
                workflow.logger.info(f"[DOC_WORKFLOW] Processing document: document_id={doc_id}, queue_size={len(self.queue)}")
                
                try:
                    result = await self._process_document(doc_id, doc_user_id)
                    # Only count as processed if not skipped
                    if not result.get("skipped"):
                        processed_count += 1
                        self.pending_count = max(0, self.pending_count - 1)
                        
                        # Check if all documents for this user are complete, and publish queue_complete if so
                        # This ensures the SSE connection closes only when ALL documents for the user are done
                        try:
                            check_result = await workflow.execute_activity(
                                check_and_publish_queue_complete_activity,
                                doc_user_id,
                                start_to_close_timeout=timedelta(seconds=30),
                                heartbeat_timeout=timedelta(seconds=10),
                                retry_policy=RetryPolicy(
                                    maximum_attempts=2,
                                    initial_interval=timedelta(seconds=1),
                                    backoff_coefficient=2.0,
                                    maximum_interval=timedelta(seconds=5),
                                ),
                            )
                            if check_result.get("published"):
                                workflow.logger.info(
                                    f"[DOC_WORKFLOW] Published queue_complete for user {doc_user_id} "
                                    f"after document {doc_id} finished ({check_result.get('complete_documents')}/{check_result.get('total_documents')} complete)"
                                )
                            else:
                                workflow.logger.debug(
                                    f"[DOC_WORKFLOW] Not all documents complete for user {doc_user_id} "
                                    f"({check_result.get('complete_documents')}/{check_result.get('total_documents')} complete)"
                                )
                        except Exception as e:
                            workflow.logger.warning(f"[DOC_WORKFLOW] Failed to check/publish queue_complete for user {doc_user_id}: {e}")
                        
                        workflow.logger.info(f"[DOC_WORKFLOW] Document {doc_id} finished processing for user {doc_user_id}")
                except Exception as e:
                    workflow.logger.error(f"[DOC_WORKFLOW] Error processing document {doc_id}: {e}", exc_info=True)
                    self.pending_count = max(0, self.pending_count - 1)
                finally:
                    self.processing = None
                    workflow.logger.info(f"[DOC_WORKFLOW] Finished processing document_id={doc_id}, queue_size={len(self.queue)}, processed_count={processed_count}")


