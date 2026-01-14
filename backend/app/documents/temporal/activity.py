"""
Temporal activities for document processing.
Each step of the document indexing pipeline is a separate activity.
All activities are synchronous since they use Django ORM and file I/O.
"""
import os
import json
import asyncio
import threading
from temporalio import activity
from typing import Dict, Any, Optional
from pathlib import Path
from django.conf import settings
from app.db.models.document import Document, DocumentText
from app.db.models.chunk import DocumentChunk
from app.documents.services.extractor import extract_text
from app.documents.services.storage import storage_service
from app.rag.chunking import (
    RecursiveCharacterTextSplitter,
    SemanticTextSplitter,
    ChunkingConfig,
    count_tokens,
)
from app.rag.embeddings import OpenAIEmbeddingsClient, MockEmbeddingsClient
from app.rag.vectorstore import PgVectorStore
from app.core.logging import get_logger

logger = get_logger(__name__)


def _publish_document_status_update_async(
    user_id: int,
    document_id: int,
    status: str,
    chunks_count: Optional[int] = None,
    error_message: Optional[str] = None,
    tokens_estimate: Optional[int] = None
):
    """
    Publish document status update to Redis channel (fire-and-forget in background thread).
    
    Args:
        user_id: User ID (owner of document)
        document_id: Document ID
        status: Document status
        chunks_count: Optional chunks count
        error_message: Optional error message
        tokens_estimate: Optional token estimate
    """
    def _publish():
        """Publish in a separate async event loop."""
        loop = None
        try:
            import asyncio
            # Create new event loop for this thread
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            
            async def _do_publish():
                try:
                    from app.core.redis import get_redis_client
                    redis_client = await get_redis_client()
                    if not redis_client:
                        return
                    
                    channel = f"documents:{user_id}"
                    event = {
                        "type": "status_update",
                        "data": {
                            "document_id": document_id,
                            "status": status,
                        }
                    }
                    
                    # Add optional fields
                    if chunks_count is not None:
                        event["data"]["chunks_count"] = chunks_count
                    if error_message is not None:
                        event["data"]["error_message"] = error_message
                    if tokens_estimate is not None:
                        event["data"]["tokens_estimate"] = tokens_estimate
                    
                    event_json = json.dumps(event, default=str)
                    await redis_client.publish(channel, event_json.encode('utf-8'))
                    logger.info(f"[REDIS_PUBLISH] Published document status update: document_id={document_id} status={status} channel={channel}")
                except Exception as e:
                    logger.warning(f"Failed to publish document status update: {e}")
            
            # Run the async function and wait for completion
            loop.run_until_complete(_do_publish())
        except Exception as e:
            logger.warning(f"Failed to publish document status update: {e}")
        finally:
            # Clean up event loop after completion (must be after run_until_complete)
            if loop:
                try:
                    # Only close if not already closed
                    if not loop.is_closed():
                        loop.close()
                except Exception:
                    pass
    
    # Run in background thread (fire-and-forget)
    thread = threading.Thread(target=_publish, daemon=True)
    thread.start()


@activity.defn
def extract_text_activity(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Activity to extract text from a document file.
    
    Args:
        input_data: Dictionary with document_id and user_id
        
    Returns:
        Dictionary with success status and result data
    """
    document_id = input_data.get("document_id")
    user_id = input_data.get("user_id")
    
    # Check for cancellation
    if activity.is_cancelled():
        logger.info(f"[DOC_ACTIVITY] Activity cancelled for document_id={document_id}")
        return {
            "success": False,
            "error": "Activity cancelled",
            "cancelled": True,
        }
    
    logger.info(f"[DOC_ACTIVITY] Extracting text for document_id={document_id}")
    activity.heartbeat({"step": "extract_text", "document_id": document_id})
    
    try:
        # Get document - handle case where document was deleted
        try:
            document = Document.objects.get(id=document_id, owner_id=user_id)
        except Document.DoesNotExist:
            logger.warning(f"[DOC_ACTIVITY] Document {document_id} does not exist (may have been deleted)")
            return {
                "success": False,
                "error": f"Document {document_id} does not exist",
                "document_deleted": True,
            }
        
        file_name = document.file.name if document.file else None
        
        if not file_name:
            raise ValueError(f"Document {document_id} has no file")
        
        # Update status to EXTRACTED (workflow started processing)
        document.status = Document.Status.EXTRACTED
        document.save(update_fields=['status'])
        
        # Publish status update (fire-and-forget)
        _publish_document_status_update_async(user_id, document_id, "EXTRACTED")
        
        # Extract text
        file_path = storage_service.get_file_path(file_name)
        text, page_map, metadata = extract_text(file_path, document.mime_type)
        
        # Store extracted text
        DocumentText.objects.update_or_create(
            document=document,
            defaults={
                'text': text,
                'page_map': page_map,
                'language': metadata.get('language', 'en')
            }
        )
        
        logger.info(f"[DOC_ACTIVITY] Text extraction completed for document_id={document_id}, text_length={len(text)}")
        
        return {
            "success": True,
            "text_length": len(text),
            "num_pages": metadata.get('num_pages', 1),
        }
        
    except Exception as e:
        logger.error(f"[DOC_ACTIVITY] Text extraction failed for document_id={document_id}: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
        }


@activity.defn
def chunk_text_activity(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Activity to chunk extracted text.
    
    Args:
        input_data: Dictionary with document_id and user_id
        
    Returns:
        Dictionary with success status and chunk count
    """
    document_id = input_data.get("document_id")
    user_id = input_data.get("user_id")
    
    # Check for cancellation
    if activity.is_cancelled():
        logger.info(f"[DOC_ACTIVITY] Activity cancelled for document_id={document_id}")
        return {
            "success": False,
            "error": "Activity cancelled",
            "cancelled": True,
        }
    
    logger.info(f"[DOC_ACTIVITY] Chunking text for document_id={document_id}")
    activity.heartbeat({"step": "chunk_text", "document_id": document_id})
    
    try:
        # Get document - handle case where document was deleted
        try:
            document = Document.objects.get(id=document_id, owner_id=user_id)
        except Document.DoesNotExist:
            logger.warning(f"[DOC_ACTIVITY] Document {document_id} does not exist (may have been deleted)")
            return {
                "success": False,
                "error": f"Document {document_id} does not exist",
                "document_deleted": True,
            }
        
        # Update status to INDEXING
        document.status = Document.Status.INDEXING
        document.save(update_fields=['status'])
        
        # Publish status update (fire-and-forget)
        _publish_document_status_update_async(user_id, document_id, "INDEXING")
        
        # Get extracted text
        extracted_text = DocumentText.objects.get(document=document)
        text = extracted_text.text
        page_map = extracted_text.page_map
        
        # Configure chunking
        chunking_config = ChunkingConfig()
        chunking_strategy = getattr(settings, 'RAG_CHUNKING_STRATEGY', 'recursive')
        
        if chunking_strategy == 'semantic':
            splitter = SemanticTextSplitter(config=chunking_config)
        else:
            splitter = RecursiveCharacterTextSplitter(config=chunking_config)
        
        # Chunk text
        chunks = splitter.split(text, metadata={
            'document_id': document_id,
            'extraction_method': 'temporal_workflow'
        })
        
        # Add page numbers to chunk metadata
        for chunk in chunks:
            if chunk.start_offset is not None:
                for page_num, page_info in page_map.items():
                    if (page_info['start_char'] <= chunk.start_offset < page_info['end_char']):
                        chunk.metadata['page'] = page_num
                        break
        
        # Delete existing chunks (for re-indexing)
        DocumentChunk.objects.filter(document=document).delete()
        
        # Create DocumentChunk records
        chunk_objects = []
        for chunk in chunks:
            chunk_obj = DocumentChunk.objects.create(
                document=document,
                chunk_index=chunk.chunk_index,
                content=chunk.content,
                start_offset=chunk.start_offset,
                end_offset=chunk.end_offset,
                metadata=chunk.metadata
            )
            chunk_objects.append(chunk_obj)
        
        logger.info(f"[DOC_ACTIVITY] Text chunking completed for document_id={document_id}, chunks={len(chunk_objects)}")
        
        # Publish status update with chunk count (fire-and-forget)
        _publish_document_status_update_async(
            user_id, document_id, "INDEXING", chunks_count=len(chunk_objects)
        )
        
        return {
            "success": True,
            "chunk_count": len(chunk_objects),
        }
        
    except Exception as e:
        logger.error(f"[DOC_ACTIVITY] Text chunking failed for document_id={document_id}: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
        }


@activity.defn
def embed_chunks_activity(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Activity to generate embeddings for document chunks.
    Note: This activity prepares chunks for embedding but doesn't store them yet.
    The actual embedding storage happens in upsert_vectors_activity.
    
    Args:
        input_data: Dictionary with document_id and user_id
        
    Returns:
        Dictionary with success status
    """
    document_id = input_data.get("document_id")
    user_id = input_data.get("user_id")
    
    # Check for cancellation
    if activity.is_cancelled():
        logger.info(f"[DOC_ACTIVITY] Activity cancelled for document_id={document_id}")
        return {
            "success": False,
            "error": "Activity cancelled",
            "cancelled": True,
        }
    
    logger.info(f"[DOC_ACTIVITY] Preparing embeddings for document_id={document_id}")
    activity.heartbeat({"step": "embed_chunks", "document_id": document_id})
    
    try:
        # Get document and chunks - handle case where document was deleted
        try:
            document = Document.objects.get(id=document_id, owner_id=user_id)
        except Document.DoesNotExist:
            logger.warning(f"[DOC_ACTIVITY] Document {document_id} does not exist (may have been deleted)")
            return {
                "success": False,
                "error": f"Document {document_id} does not exist",
                "document_deleted": True,
            }
        
        chunks = list(DocumentChunk.objects.filter(document=document).order_by('chunk_index'))
        
        if len(chunks) == 0:
            raise ValueError("No chunks found for document")
        
        # Determine embedding client
        if os.getenv('OPENAI_API_KEY'):
            embeddings_client = OpenAIEmbeddingsClient()
        else:
            embeddings_client = MockEmbeddingsClient()
        
        # Generate embeddings
        chunk_texts = [chunk.content for chunk in chunks]
        embeddings = embeddings_client.embed_texts(chunk_texts, user_id=user_id)
        
        logger.info(f"[DOC_ACTIVITY] Generated {len(embeddings)} embeddings for document_id={document_id}")
        
        return {
            "success": True,
            "embedding_count": len(embeddings),
            "embedding_model": embeddings_client.model_name,
        }
        
    except Exception as e:
        logger.error(f"[DOC_ACTIVITY] Embedding generation failed for document_id={document_id}: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
        }


@activity.defn
def upsert_vectors_activity(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Activity to upsert embeddings to vector store.
    
    Args:
        input_data: Dictionary with document_id and user_id
        
    Returns:
        Dictionary with success status
    """
    document_id = input_data.get("document_id")
    user_id = input_data.get("user_id")
    
    # Check for cancellation
    if activity.is_cancelled():
        logger.info(f"[DOC_ACTIVITY] Activity cancelled for document_id={document_id}")
        return {
            "success": False,
            "error": "Activity cancelled",
            "cancelled": True,
        }
    
    logger.info(f"[DOC_ACTIVITY] Upserting vectors for document_id={document_id}")
    activity.heartbeat({"step": "upsert_vectors", "document_id": document_id})
    
    try:
        # Get document and chunks - handle case where document was deleted
        try:
            document = Document.objects.get(id=document_id, owner_id=user_id)
        except Document.DoesNotExist:
            logger.warning(f"[DOC_ACTIVITY] Document {document_id} does not exist (may have been deleted)")
            return {
                "success": False,
                "error": f"Document {document_id} does not exist",
                "document_deleted": True,
            }
        
        chunks = list(DocumentChunk.objects.filter(document=document).order_by('chunk_index'))
        
        if len(chunks) == 0:
            raise ValueError("No chunks found for document")
        
        # Determine embedding client
        if os.getenv('OPENAI_API_KEY'):
            embeddings_client = OpenAIEmbeddingsClient()
        else:
            embeddings_client = MockEmbeddingsClient()
        
        # Generate embeddings (if not already done)
        chunk_texts = [chunk.content for chunk in chunks]
        embeddings = embeddings_client.embed_texts(chunk_texts, user_id=user_id)
        
        # Upsert to vector store
        vector_store = PgVectorStore()
        vector_store.upsert_embeddings(
            chunks=chunks,
            embeddings=embeddings,
            embedding_model=embeddings_client.model_name
        )
        
        logger.info(f"[DOC_ACTIVITY] Vector upsert completed for document_id={document_id}")
        
        return {
            "success": True,
        }
        
    except Exception as e:
        logger.error(f"[DOC_ACTIVITY] Vector upsert failed for document_id={document_id}: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
        }


@activity.defn
def update_document_status_activity(input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Activity to update document status and metadata.
    
    Args:
        input_data: Dictionary with document_id, user_id, status, and optional chunks_count, tokens_estimate, error_message
        
    Returns:
        Dictionary with success status
    """
    document_id = input_data.get("document_id")
    user_id = input_data.get("user_id")
    status = input_data.get("status")
    chunks_count = input_data.get("chunks_count")
    error_message = input_data.get("error_message")
    
    # Check for cancellation
    if activity.is_cancelled():
        logger.info(f"[DOC_ACTIVITY] Activity cancelled for document_id={document_id}")
        return {
            "success": False,
            "error": "Activity cancelled",
            "cancelled": True,
        }
    
    logger.info(f"[DOC_ACTIVITY] Updating document status for document_id={document_id} to {status}")
    
    try:
        # Get document - handle case where document was deleted
        try:
            document = Document.objects.get(id=document_id, owner_id=user_id)
        except Document.DoesNotExist:
            # Document was deleted - log and return success (nothing to update)
            logger.warning(f"[DOC_ACTIVITY] Document {document_id} does not exist (may have been deleted), skipping status update")
            return {
                "success": True,
                "skipped": True,
                "reason": "document_deleted",
            }
        
        # Update status
        document.status = status
        update_fields = ['status']
        
        # Update chunks_count if provided
        if chunks_count is not None:
            document.chunks_count = chunks_count
            update_fields.append('chunks_count')
        
        # Update tokens_estimate if status is READY
        if status == Document.Status.READY:
            try:
                extracted_text = DocumentText.objects.get(document=document)
                chunking_config = ChunkingConfig()
                document.tokens_estimate = count_tokens(extracted_text.text, chunking_config.tokenizer_model)
                update_fields.append('tokens_estimate')
            except DocumentText.DoesNotExist:
                logger.warning(f"[DOC_ACTIVITY] DocumentText not found for document_id={document_id}, skipping token count")
        
        # Update error_message if provided
        if error_message is not None:
            document.error_message = error_message
            update_fields.append('error_message')
        elif status == Document.Status.READY:
            # Clear error message on success
            document.error_message = None
            update_fields.append('error_message')
        
        # Save document
        document.save(update_fields=update_fields)
        
        logger.info(f"[DOC_ACTIVITY] Document status updated for document_id={document_id} to {status}")
        
        # Publish status update (fire-and-forget)
        _publish_document_status_update_async(
            user_id,
            document_id,
            status,
            chunks_count=chunks_count,
            error_message=error_message,
            tokens_estimate=document.tokens_estimate if status == Document.Status.READY else None
        )
        
        return {
            "success": True,
        }
        
    except Exception as e:
        logger.error(f"[DOC_ACTIVITY] Failed to update document status for document_id={document_id}: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
        }


@activity.defn
def check_and_publish_queue_complete_activity(user_id: int) -> Dict[str, Any]:
    """
    Check if all documents for a user are complete (READY or FAILED), and if so, publish queue_complete.
    
    This activity queries the database to check if all documents for the user are in terminal states.
    Only publishes queue_complete if ALL documents are complete.
    
    Args:
        user_id: User ID to check
        
    Returns:
        Dictionary with success status and whether queue_complete was published
    """
    logger.info(f"[DOC_ACTIVITY] Checking if all documents are complete for user_id={user_id}")
    
    try:
        # Query all documents for this user
        all_docs = Document.objects.filter(owner_id=user_id)
        total_count = all_docs.count()
        
        if total_count == 0:
            # No documents for this user, nothing to complete
            logger.debug(f"[DOC_ACTIVITY] No documents found for user_id={user_id}, skipping queue_complete check")
            return {
                "success": True,
                "published": False,
                "reason": "no_documents",
            }
        
        # Check how many are in terminal states (READY or FAILED)
        terminal_states = [Document.Status.READY, Document.Status.FAILED]
        complete_count = all_docs.filter(status__in=terminal_states).count()
        
        # Get counts by status for logging
        status_counts = {}
        for status in [Document.Status.UPLOADED, Document.Status.QUEUED, Document.Status.EXTRACTED, 
                       Document.Status.INDEXING, Document.Status.READY, Document.Status.FAILED]:
            status_counts[status] = all_docs.filter(status=status).count()
        
        logger.info(
            f"[DOC_ACTIVITY] Document status check for user_id={user_id}: "
            f"total={total_count}, complete={complete_count}, "
            f"statuses={status_counts}"
        )
        
        # If all documents are complete, publish queue_complete
        if complete_count == total_count:
            logger.info(f"[DOC_ACTIVITY] All {total_count} documents complete for user_id={user_id}, publishing queue_complete")
            
            # Publish queue_complete asynchronously (using same pattern as _publish_document_status_update_async)
            try:
                # Get or create event loop
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                async def _do_publish():
                    try:
                        from app.core.redis import get_redis_client
                        redis_client = await get_redis_client()
                        if not redis_client:
                            logger.warning(f"[DOC_ACTIVITY] Redis client unavailable, cannot publish queue_complete for user_id={user_id}")
                            return
                        
                        channel = f"documents:{user_id}"
                        event = {
                            "type": "queue_complete",
                            "data": {
                                "user_id": user_id,
                            }
                        }
                        
                        event_json = json.dumps(event, default=str)
                        await redis_client.publish(channel, event_json.encode('utf-8'))
                        logger.info(f"[DOC_ACTIVITY] Published queue_complete event for user_id={user_id} to channel {channel}")
                    except Exception as e:
                        logger.error(f"[DOC_ACTIVITY] Failed to publish queue_complete for user_id={user_id}: {e}", exc_info=True)
                
                # Run the async function and wait for completion
                loop.run_until_complete(_do_publish())
            except Exception as e:
                logger.warning(f"[DOC_ACTIVITY] Failed to publish queue_complete for user_id={user_id}: {e}")
            
            return {
                "success": True,
                "published": True,
                "total_documents": total_count,
                "complete_documents": complete_count,
            }
        else:
            # Not all documents are complete yet
            logger.debug(
                f"[DOC_ACTIVITY] Not all documents complete for user_id={user_id}: "
                f"{complete_count}/{total_count} complete"
            )
            return {
                "success": True,
                "published": False,
                "total_documents": total_count,
                "complete_documents": complete_count,
            }
        
    except Exception as e:
        logger.error(f"[DOC_ACTIVITY] Failed to check queue completion for user_id={user_id}: {e}", exc_info=True)
        return {
            "success": False,
            "error": str(e),
            "published": False,
        }
