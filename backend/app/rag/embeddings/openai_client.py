"""
OpenAI embedding client implementation with async support.
"""
import os
import time
import asyncio
from typing import List
from django.conf import settings
from langchain_openai import OpenAIEmbeddings
from .client_base import EmbeddingsClientBase


class OpenAIEmbeddingsClient(EmbeddingsClientBase):
    """OpenAI embedding client using langchain-openai."""
    
    def __init__(self, model_name: str = None, api_key: str = None):
        """
        Initialize OpenAI embedding client.
        
        Args:
            model_name: Model name (defaults to RAG_EMBEDDING_MODEL setting)
            api_key: OpenAI API key (defaults to OPENAI_API_KEY env var)
        """
        self._model_name = model_name or getattr(settings, 'RAG_EMBEDDING_MODEL', 'text-embedding-3-small')
        self._api_key = api_key or os.getenv('OPENAI_API_KEY')
        
        if not self._api_key:
            raise ValueError("OPENAI_API_KEY environment variable is required")
        
        # Initialize LangChain embeddings
        self._embeddings = OpenAIEmbeddings(
            model=self._model_name,
            openai_api_key=self._api_key
        )
        
        # Get dimensions from model (common values)
        self._dimensions = getattr(settings, 'RAG_EMBEDDING_DIMENSIONS', 1536)
        
        # OpenAI batch limits
        self._max_batch_size = 2048  # OpenAI allows up to 2048 texts per request
        
        # Semaphore for async rate limiting
        self._semaphore = asyncio.Semaphore(5)  # Max 5 concurrent requests
    
    @property
    def model_name(self) -> str:
        return self._model_name
    
    @property
    def dimensions(self) -> int:
        return self._dimensions
    
    @property
    def max_batch_size(self) -> int:
        return self._max_batch_size
    
    def embed_texts(self, texts: List[str], user_id: int = None) -> List[List[float]]:
        """
        Embed multiple texts with batching and retry logic.
        
        Args:
            texts: List of texts to embed
            user_id: Optional user ID for token usage tracking
            
        Returns:
            List of embedding vectors
        """
        if not texts:
            return []
        
        all_embeddings = []
        total_tokens = 0
        
        # Process in batches
        for i in range(0, len(texts), self._max_batch_size):
            batch = texts[i:i + self._max_batch_size]
            
            # Retry logic with exponential backoff
            max_retries = 3
            for attempt in range(max_retries):
                try:
                    batch_embeddings = self._embeddings.embed_documents(batch)
                    all_embeddings.extend(batch_embeddings)
                    
                    # Estimate tokens: OpenAI embeddings charge ~1 token per 4 characters
                    # This is an approximation since OpenAI doesn't return exact token counts
                    batch_text = " ".join(batch)
                    estimated_tokens = len(batch_text) // 4
                    total_tokens += estimated_tokens
                    
                    break
                except Exception as e:
                    if attempt == max_retries - 1:
                        raise
                    wait_time = 2 ** attempt
                    time.sleep(wait_time)
        
        # Persist token usage if user_id provided
        # Note: This sync method may be called from async contexts
        # We'll use sync version here - callers in async contexts should handle it
        if user_id and total_tokens > 0:
            from app.account.utils import increment_user_token_usage
            # Use sync version - if called from async, wrap this call with sync_to_async
            increment_user_token_usage(user_id, total_tokens)
        
        return all_embeddings
    
    def embed_query(self, text: str, user_id: int = None) -> List[float]:
        """
        Embed a single query text.
        
        Args:
            text: Query text to embed
            user_id: Optional user ID for token usage tracking
            
        Returns:
            Embedding vector
        """
        embedding = self._embeddings.embed_query(text)
        
        # Estimate tokens: OpenAI embeddings charge ~1 token per 4 characters
        # This is an approximation since OpenAI doesn't return exact token counts
        if user_id:
            estimated_tokens = len(text) // 4
            if estimated_tokens > 0:
                from app.account.utils import increment_user_token_usage
                # Use sync version - if called from async, wrap this call with sync_to_async
                increment_user_token_usage(user_id, estimated_tokens)
        
        return embedding
    
    async def aembed_texts(
        self, 
        texts: List[str], 
        user_id: int = None
    ) -> List[List[float]]:
        """
        Embed texts with parallel batching using asyncio.gather.
        
        Args:
            texts: List of texts to embed
            user_id: Optional user ID for token usage tracking
            
        Returns:
            List of embedding vectors
        """
        if not texts:
            return []
        
        # Split into batches
        batches = [
            texts[i:i + self._max_batch_size]
            for i in range(0, len(texts), self._max_batch_size)
        ]
        
        async def embed_batch(batch: List[str]) -> List[List[float]]:
            """Embed a single batch with semaphore-based rate limiting."""
            async with self._semaphore:
                # Use LangChain's async method
                return await self._embeddings.aembed_documents(batch)
        
        # Execute batches in parallel
        results = await asyncio.gather(*[
            embed_batch(batch) for batch in batches
        ])
        
        # Flatten results
        all_embeddings = []
        for batch_embeddings in results:
            all_embeddings.extend(batch_embeddings)
        
        # Track token usage
        if user_id:
            total_tokens = sum(len(text) // 4 for text in texts)
            if total_tokens > 0:
                from app.account.utils import increment_user_token_usage
                from asgiref.sync import sync_to_async
                await sync_to_async(increment_user_token_usage)(user_id, total_tokens)
        
        return all_embeddings
    
    async def aembed_query(self, text: str, user_id: int = None) -> List[float]:
        """
        Embed single query asynchronously.
        
        Args:
            text: Query text to embed
            user_id: Optional user ID for token usage tracking
            
        Returns:
            Embedding vector
        """
        async with self._semaphore:
            embedding = await self._embeddings.aembed_query(text)
        
        # Track token usage
        if user_id:
            estimated_tokens = len(text) // 4
            if estimated_tokens > 0:
                from app.account.utils import increment_user_token_usage
                from asgiref.sync import sync_to_async
                await sync_to_async(increment_user_token_usage)(user_id, estimated_tokens)
        
        return embedding
