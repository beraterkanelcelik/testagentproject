"""
Document management endpoints (upload, list, delete).
"""
import json
import hashlib
import asyncio
from django.http import JsonResponse, StreamingHttpResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.clickjacking import xframe_options_exempt
from django.core.paginator import Paginator
from django.conf import settings
from app.core.dependencies import get_current_user, get_current_user_async
from app.core.redis import get_redis_client
from app.db.models.document import Document
from app.documents.services.storage import storage_service
from app.rag.vectorstore import PgVectorStore
from app.documents.temporal.workflow_manager import signal_add_document
from app.core.logging import get_logger
from app.settings import TEMPORAL_ADDRESS, TEMPORAL_TASK_QUEUE, SSE_HEARTBEAT_SECONDS, STREAM_TIMEOUT_SECONDS

logger = get_logger(__name__)


@csrf_exempt
@require_http_methods(["GET", "POST"])
def documents(request):
    """List or upload documents."""
    user = get_current_user(request)
    if not user:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    if request.method == 'GET':
        # List user's documents
        status_filter = request.GET.get('status')
        documents_qs = Document.objects.filter(owner=user).order_by('-created_at')
        
        if status_filter:
            documents_qs = documents_qs.filter(status=status_filter)
        
        # Pagination
        page_number = request.GET.get('page', 1)
        paginator = Paginator(documents_qs, 20)  # 20 per page
        
        try:
            page = paginator.page(page_number)
        except:
            page = paginator.page(1)
        
        documents_data = []
        for doc in page.object_list:
            documents_data.append({
                'id': doc.id,
                'title': doc.title,
                'status': doc.status,
                'chunks_count': doc.chunks_count,
                'tokens_estimate': doc.tokens_estimate,
                'size_bytes': doc.size_bytes,
                'mime_type': doc.mime_type,
                'created_at': doc.created_at.isoformat(),
                'updated_at': doc.updated_at.isoformat(),
            })
        
        return JsonResponse({
            'results': documents_data,
            'count': paginator.count,
            'page': page.number,
            'num_pages': paginator.num_pages,
            'has_next': page.has_next(),
            'has_previous': page.has_previous(),
        })
    
    elif request.method == 'POST':
        # Upload document
        if 'file' not in request.FILES:
            return JsonResponse({'error': 'No file provided'}, status=400)
        
        file = request.FILES['file']
        
        # Validate file type (PDF for now, but structure supports others)
        allowed_mime_types = ['application/pdf']
        if file.content_type not in allowed_mime_types:
            return JsonResponse({
                'error': f'File type not supported. Allowed types: {", ".join(allowed_mime_types)}'
            }, status=400)
        
        # Validate file size
        max_size = getattr(settings, 'RAG_MAX_FILE_SIZE_MB', 50) * 1024 * 1024  # Convert MB to bytes
        if file.size > max_size:
            return JsonResponse({
                'error': f'File too large. Maximum size: {max_size / (1024*1024)}MB'
            }, status=400)
        
        try:
            # Read file content
            file_content = file.read()
            
            # Calculate checksum
            checksum = hashlib.sha256(file_content).hexdigest()
            
            # Check for duplicate (optional - you might want to allow duplicates)
            # existing = Document.objects.filter(owner=user, checksum=checksum).first()
            # if existing:
            #     return JsonResponse({'error': 'File already uploaded'}, status=400)
            
            # Create document record
            document = Document.objects.create(
                owner=user,
                title=file.name,
                source_type=Document.SourceType.UPLOAD,
                mime_type=file.content_type,
                size_bytes=file.size,
                checksum=checksum,
                status=Document.Status.UPLOADED
            )
            
            # Save file to storage
            relative_path = storage_service.save_file(
                user_id=user.id,
                document_id=document.id,
                filename=file.name,
                file_content=file_content
            )
            
            # Update document with file path
            # Store the relative path so we can retrieve it later
            document.file.name = relative_path
            document.save(update_fields=['file'])
            
            # Verify file was saved correctly
            file_path = storage_service.get_file_path(relative_path)
            if not file_path.exists():
                logger.error(f"File was not saved correctly: {file_path}")
            else:
                logger.debug(f"File saved successfully: {file_path}")
            
            # Update status to QUEUED (waiting in Temporal queue)
            document.status = Document.Status.QUEUED
            document.save(update_fields=['status'])
            
            # Send signal to document queue workflow to add document to processing queue
            try:
                # Run async signal in new event loop (sync Django view context)
                try:
                    loop = asyncio.get_event_loop()
                except RuntimeError:
                    loop = asyncio.new_event_loop()
                    asyncio.set_event_loop(loop)
                
                # Async function to publish status and send signal
                async def publish_and_signal():
                    # Publish initial QUEUED status
                    try:
                        from app.core.redis import get_redis_client
                        redis_client = await get_redis_client()
                        if redis_client:
                            channel = f"documents:{user.id}"
                            event = {
                                "type": "status_update",
                                "data": {
                                    "document_id": document.id,
                                    "status": "QUEUED",
                                }
                            }
                            await redis_client.publish(channel, json.dumps(event).encode('utf-8'))
                    except Exception as e:
                        logger.debug(f"Failed to publish QUEUED status: {e}")
                    
                    # Send signal to add document to queue
                    await signal_add_document(document.id, user.id)
                
                if loop.is_running():
                    # If loop is already running, use a thread to run the async function
                    import concurrent.futures
                    with concurrent.futures.ThreadPoolExecutor() as executor:
                        future = executor.submit(
                            lambda: asyncio.run(publish_and_signal())
                        )
                        future.result(timeout=10)  # 10 second timeout for sending signal
                else:
                    # Use existing loop
                    loop.run_until_complete(publish_and_signal())
                
                logger.info(f"Sent signal to add document {document.id} to processing queue")
            except Exception as e:
                logger.error(f"Failed to send signal for document {document.id}: {str(e)}", exc_info=True)
                # Document is created but signal failed - status will remain QUEUED
            
            # Refresh from DB to get updated status
            document.refresh_from_db()
            
            return JsonResponse({
                'id': document.id,
                'title': document.title,
                'status': document.status,
                'chunks_count': document.chunks_count,
                'created_at': document.created_at.isoformat(),
            }, status=201)
        
        except Exception as e:
            logger.error(f"Error uploading document: {str(e)}")
            return JsonResponse({'error': f'Upload failed: {str(e)}'}, status=500)


@csrf_exempt
@require_http_methods(["GET", "DELETE"])
def document_detail(request, document_id):
    """Get or delete specific document."""
    user = get_current_user(request)
    if not user:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    try:
        document = Document.objects.get(id=document_id, owner=user)
    except Document.DoesNotExist:
        return JsonResponse({'error': 'Document not found'}, status=404)
    
    if request.method == 'GET':
        # Get document details
        from app.db.models.document import DocumentText
        
        response_data = {
            'id': document.id,
            'title': document.title,
            'status': document.status,
            'source_type': document.source_type,
            'mime_type': document.mime_type,
            'size_bytes': document.size_bytes,
            'chunks_count': document.chunks_count,
            'tokens_estimate': document.tokens_estimate,
            'error_message': document.error_message,
            'created_at': document.created_at.isoformat(),
            'updated_at': document.updated_at.isoformat(),
        }
        
        # Include extracted text if available
        try:
            extracted_text = DocumentText.objects.get(document=document)
            response_data['extracted_text'] = extracted_text.text
            response_data['page_map'] = extracted_text.page_map
            response_data['language'] = extracted_text.language
        except DocumentText.DoesNotExist:
            response_data['extracted_text'] = None
            response_data['page_map'] = {}
            response_data['language'] = None
        
        return JsonResponse(response_data)
    
    elif request.method == 'DELETE':
        # Delete document and all associated data
        try:
            # Delete file from storage
            if document.file:
                storage_service.delete_file(document.file.name)
            
            # Explicitly delete embeddings from vector store
            vector_store = PgVectorStore()
            vector_store.delete_by_document(document_id)
            
            # Delete document (cascades to chunks, embeddings, and extracted text)
            document.delete()
            
            return JsonResponse({'message': 'Document deleted successfully'}, status=200)
        
        except Exception as e:
            logger.error(f"Error deleting document {document_id}: {str(e)}")
            return JsonResponse({'error': f'Delete failed: {str(e)}'}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
def document_chunks(request, document_id):
    """Get chunks for a specific document."""
    user = get_current_user(request)
    if not user:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    try:
        document = Document.objects.get(id=document_id, owner=user)
    except Document.DoesNotExist:
        return JsonResponse({'error': 'Document not found'}, status=404)
    
    from app.db.models.chunk import DocumentChunk
    
    # Get all chunks for this document
    chunks = DocumentChunk.objects.filter(document=document).order_by('chunk_index')
    
    logger.debug(f"Found {chunks.count()} chunks for document {document_id}")
    
    chunks_data = []
    for chunk in chunks:
        chunk_data = {
            'id': chunk.id,
            'chunk_index': chunk.chunk_index,
            'content': chunk.content,
            'start_offset': chunk.start_offset,
            'end_offset': chunk.end_offset,
            'metadata': chunk.metadata,
            'created_at': chunk.created_at.isoformat(),
        }
        
        # Check if chunk has embedding
        try:
            embedding = chunk.embedding
            if embedding:
                chunk_data['has_embedding'] = True
                chunk_data['embedding_model'] = embedding.embedding_model
            else:
                chunk_data['has_embedding'] = False
        except:
            chunk_data['has_embedding'] = False
        
        chunks_data.append(chunk_data)
    
    return JsonResponse({
        'document_id': document.id,
        'document_title': document.title,
        'chunks': chunks_data,
        'total_chunks': len(chunks_data),
    })


@csrf_exempt
@require_http_methods(["GET"])
@xframe_options_exempt
def document_file(request, document_id):
    """Serve the original document file."""
    from django.http import FileResponse, Http404, JsonResponse
    from django.conf import settings
    from rest_framework_simplejwt.authentication import JWTAuthentication
    from rest_framework_simplejwt.exceptions import InvalidToken
    import os
    
    # Try to get user from JWT token (supports both header and query param for iframe access)
    user = None
    
    # First try standard JWT authentication from header
    jwt_auth = JWTAuthentication()
    try:
        validated_token = jwt_auth.get_validated_token(jwt_auth.get_raw_token(jwt_auth.get_header(request)))
        user = jwt_auth.get_user(validated_token)
    except (InvalidToken, AttributeError, TypeError):
        pass
    
    # If no user from header, try token from query parameter (for iframe access)
    if not user:
        token = request.GET.get('token')
        if token:
            try:
                # Use JWT authentication to validate token from query param
                from rest_framework_simplejwt.tokens import UntypedToken
                from rest_framework_simplejwt.exceptions import InvalidToken, TokenError
                
                try:
                    # Validate the token
                    UntypedToken(token)
                    # If valid, get user from token
                    validated_token = jwt_auth.get_validated_token(token)
                    user = jwt_auth.get_user(validated_token)
                except (InvalidToken, TokenError) as e:
                    logger.debug(f"Token validation from query param failed: {e}")
                    pass
            except Exception as e:
                logger.debug(f"Error validating token from query: {e}")
                pass
    
    # Fall back to session authentication
    if not user and hasattr(request, 'user') and request.user.is_authenticated:
        user = request.user
    
    if not user:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    try:
        document = Document.objects.get(id=document_id, owner=user)
    except Document.DoesNotExist:
        raise Http404('Document not found')
    
    # Get file path - try multiple approaches
    file_path = None
    
    if document.file and document.file.name:
        # Try the stored file path
        file_path = storage_service.get_file_path(document.file.name)
        logger.info(f"Trying stored file path: {file_path} (exists: {file_path.exists()})")
    
    # If file not found, try constructing path from document info
    if not file_path or not file_path.exists():
        # Try: documents/{user_id}/{document_id}/{filename}
        fallback_path = storage_service.get_file_path(f"documents/{user.id}/{document_id}/{document.title}")
        logger.info(f"Trying fallback path: {fallback_path} (exists: {fallback_path.exists()})")
        if fallback_path.exists():
            file_path = fallback_path
    
    # If still not found, try to find any file in the document directory
    if not file_path or not file_path.exists():
        doc_dir = storage_service.media_root / f"documents/{user.id}/{document_id}"
        if doc_dir.exists():
            files = list(doc_dir.glob("*"))
            if files:
                file_path = files[0]  # Use first file found
                logger.info(f"Found file in directory: {file_path}")
    
    if not file_path or not file_path.exists():
        logger.error(f"File not found for document {document_id}: tried {document.file.name if document.file else None}")
        return JsonResponse({
            'error': 'File not found on disk',
            'file_path': str(file_path) if file_path else 'unknown',
            'file_name': document.file.name if document.file else None,
            'document_id': document_id,
            'user_id': user.id
        }, status=404)
    
    try:
        # Serve file with appropriate content type
        # FileResponse will handle file closing automatically
        file_handle = open(file_path, 'rb')
        response = FileResponse(
            file_handle,
            content_type=document.mime_type,
            as_attachment=False  # Display inline, not as download
        )
        response['Content-Disposition'] = f'inline; filename="{document.title}"'
        # X-Frame-Options is exempted via decorator, so we can use CSP for better control
        response['Content-Security-Policy'] = "frame-ancestors 'self' http://localhost:3000 http://127.0.0.1:3000"
        
        # Add CORS headers for iframe access
        origin = request.META.get('HTTP_ORIGIN', '')
        referer = request.META.get('HTTP_REFERER', '')
        allowed_origins = ['http://localhost:3000', 'http://127.0.0.1:3000']
        
        # Set CORS headers if from allowed origin
        if any(allowed in origin or allowed in referer for allowed in allowed_origins):
            response['Access-Control-Allow-Origin'] = origin if origin else 'http://localhost:3000'
            response['Access-Control-Allow-Credentials'] = 'true'
        
        return response
    except Exception as e:
        logger.error(f"Error serving file {file_path}: {str(e)}", exc_info=True)
        return JsonResponse({'error': f'Error serving file: {str(e)}'}, status=500)


@csrf_exempt
@require_http_methods(["POST"])
def document_index(request, document_id):
    """Manually trigger re-indexing of a document via Temporal workflow."""
    user = get_current_user(request)
    if not user:
        return JsonResponse({'error': 'Authentication required'}, status=401)
    
    try:
        document = Document.objects.get(id=document_id, owner=user)
    except Document.DoesNotExist:
        return JsonResponse({'error': 'Document not found'}, status=404)
    
    try:
        # Reset document status to QUEUED and send signal to queue
        document.status = Document.Status.QUEUED
        document.save(update_fields=['status'])
        
        # Get event loop for async operations
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        # Publish initial QUEUED status and send signal
        async def publish_and_signal():
            # Publish status update
            try:
                redis_client = await get_redis_client()
                if redis_client:
                    channel = f"documents:{user.id}"
                    event = {
                        "type": "status_update",
                        "data": {
                            "document_id": document.id,
                            "status": "QUEUED",
                        }
                    }
                    await redis_client.publish(channel, json.dumps(event).encode('utf-8'))
            except Exception as e:
                logger.debug(f"Failed to publish QUEUED status: {e}")
            
            # Send signal to add document to queue
            await signal_add_document(document.id, user.id)
        
        if loop.is_running():
            import concurrent.futures
            with concurrent.futures.ThreadPoolExecutor() as executor:
                future = executor.submit(lambda: asyncio.run(publish_and_signal()))
                future.result(timeout=10)
        else:
            loop.run_until_complete(publish_and_signal())
        
        document.refresh_from_db()
        
        return JsonResponse({
            'id': document.id,
            'status': document.status,
            'chunks_count': document.chunks_count,
            'message': 'Re-indexing queued'
        })
    
    except Exception as e:
        logger.error(f"Error sending signal for re-indexing document {document_id}: {str(e)}", exc_info=True)
        return JsonResponse({'error': f'Failed to start re-indexing: {str(e)}'}, status=500)


@csrf_exempt
@require_http_methods(["GET"])
async def stream_document_status(request):
    """
    Stream document status updates using SSE (Server-Sent Events).
    
    Subscribes to Redis channel: documents:{user_id}
    Receives real-time status updates as documents are processed.
    
    Returns:
    SSE stream with events: status_update, heartbeat, error
    """
    user = await get_current_user_async(request)
    if not user:
        logger.warning("Unauthenticated request to stream_document_status endpoint")
        return JsonResponse(
            {'error': 'Authentication required'},
            status=401
        )
    
    def _format_sse_event(event: dict) -> str:
        """Format event dict as SSE data line."""
        event_json = json.dumps(event, default=str)
        event_type = event.get("type", "message")
        return f"event: {event_type}\ndata: {event_json}\n\n"
    
    async def event_stream():
        """
        Async generator for SSE events via Redis.
        
        Subscribes to channel: documents:{user_id}
        Receives status updates for all user documents.
        """
        pubsub = None
        channel = None
        try:
            # Try Redis streaming (if Temporal is configured)
            use_redis = TEMPORAL_ADDRESS and TEMPORAL_TASK_QUEUE
            
            if use_redis:
                try:
                    # Get Redis client
                    redis_client = await get_redis_client()
                    channel = f"documents:{user.id}"
                    
                    # Create pubsub instance
                    pubsub = redis_client.pubsub()
                    await pubsub.subscribe(channel)
                    
                    # Wait for subscription confirmation
                    confirm_msg = await pubsub.get_message(timeout=5.0)
                    if confirm_msg and confirm_msg['type'] == 'subscribe':
                        logger.info(f"Subscribed to Redis channel: {channel}")
                    else:
                        logger.warning(f"Unexpected subscription confirmation: {confirm_msg}")
                    
                    # Listen to Redis messages
                    # No timeout - connection stays open until queue_complete or client disconnect
                    loop = asyncio.get_running_loop()
                    last_heartbeat_time = loop.time()
                    heartbeat_interval = SSE_HEARTBEAT_SECONDS
                    
                    async for msg in pubsub.listen():
                        current_time = loop.time()
                        
                        # Send heartbeat to keep connection alive
                        if current_time - last_heartbeat_time >= heartbeat_interval:
                            try:
                                yield _format_sse_event({
                                    "type": "heartbeat",
                                    "data": {"timestamp": current_time}
                                })
                                last_heartbeat_time = current_time
                            except Exception as e:
                                logger.debug(f"Failed to send heartbeat: {e}")
                        
                        # Filter subscription confirmation messages
                        if msg['type'] == 'subscribe' or msg['type'] == 'psubscribe':
                            continue
                        
                        # Parse and forward message
                        if msg['type'] == 'message':
                            try:
                                event_data = json.loads(msg['data'].decode('utf-8'))
                                logger.info(f"[SSE] Received and forwarding event: type={event_data.get('type')} document_id={event_data.get('data', {}).get('document_id')}")
                                yield _format_sse_event(event_data)
                                
                                # Close connection when queue is complete
                                if event_data.get("type") == "queue_complete":
                                    logger.info(f"Queue complete for user {user.id}, closing SSE connection")
                                    break
                            except json.JSONDecodeError as e:
                                logger.warning(f"Failed to parse Redis message: {e}, raw_data={msg.get('data')}")
                                continue
                            except Exception as e:
                                logger.error(f"Error processing Redis message: {e}", exc_info=True)
                                continue
                
                except Exception as e:
                    logger.error(f"Error in document status stream for user {user.id}: {e}", exc_info=True)
                    yield _format_sse_event({
                        "type": "error",
                        "data": {"error": "Redis streaming unavailable", "retry": True}
                    })
                    return
            else:
                # Redis not available - send error
                yield _format_sse_event({
                    "type": "error",
                    "data": {"error": "Real-time updates unavailable", "retry": False}
                })
                return
                
        except Exception as e:
            logger.error(f"Error in document status stream for user {user.id}: {e}", exc_info=True)
            yield _format_sse_event({
                "type": "error",
                "data": {"error": str(e)}
            })
        finally:
            # Cleanup pubsub
            if pubsub:
                try:
                    loop = asyncio.get_running_loop()
                    if not loop.is_closed():
                        try:
                            await pubsub.unsubscribe()
                            await pubsub.punsubscribe()
                            await pubsub.close()
                            logger.debug(f"Cleaned up Redis pubsub for channel {channel or 'unknown'}")
                        except (RuntimeError, asyncio.CancelledError) as e:
                            logger.debug(f"Event loop closing, skipping pubsub cleanup: {e}")
                except Exception as e:
                    logger.debug(f"Error cleaning up Redis pubsub (non-critical): {e}")
    
    # Create SSE response
    response = StreamingHttpResponse(
        event_stream(),
        content_type='text/event-stream'
    )
    response['Cache-Control'] = 'no-cache'
    response['X-Accel-Buffering'] = 'no'
    response['Connection'] = 'keep-alive'
    
    return response
