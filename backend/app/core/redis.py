"""
Redis integration for pub/sub streaming and Redis Streams.
CRITICAL: Redis clients and pools must be created per event loop to avoid "Future attached to different loop" errors.
Best practice: Use per-loop ConnectionPool and per-loop clients, with WeakKeyDictionary to prevent leaks.
"""
import asyncio
import weakref
import json
import time
from urllib.parse import urlparse, urlunparse
from typing import Optional, Dict, Any, List
from collections import deque

import redis.asyncio as redis
from app.settings import REDIS_URL, REDIS_PASSWORD
from app.core.logging import get_logger

logger = get_logger(__name__)

# Per-loop pools and clients (automatically cleaned up when loops are garbage collected)
_pools_by_loop: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, redis.ConnectionPool] = weakref.WeakKeyDictionary()
_clients_by_loop: weakref.WeakKeyDictionary[asyncio.AbstractEventLoop, redis.Redis] = weakref.WeakKeyDictionary()


def _url_with_password(url: str, password: Optional[str]) -> str:
    """
    Safely inject password into Redis URL using urllib.parse.
    
    Args:
        url: Redis URL (with or without scheme)
        password: Optional password to inject
        
    Returns:
        URL with password injected if password provided and not already present
    """
    if not password:
        return url

    # Parse URL, adding default scheme if missing
    parsed = urlparse(url if "://" in url else f"redis://{url}")
    
    # If auth already present, keep it as-is
    if parsed.password is not None or parsed.username is not None:
        return url

    # Inject password (username empty, password set)
    netloc = f":{password}@{parsed.hostname}"
    if parsed.port:
        netloc += f":{parsed.port}"

    return urlunparse(parsed._replace(netloc=netloc))


async def get_redis_client() -> redis.Redis:
    """
    Get or create Redis async client for the current event loop.
    Uses per-loop ConnectionPool and per-loop clients to ensure loop isolation.
    
    Returns:
        Redis async client instance for current event loop
        
    Raises:
        RuntimeError: If called without a running event loop
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        raise RuntimeError("get_redis_client() must be called from an async context with a running loop")

    # Check if we already have a client for this loop
    client = _clients_by_loop.get(loop)
    if client is not None:
        return client

    # Create per-loop pool if needed
    pool = _pools_by_loop.get(loop)
    if pool is None:
        url = _url_with_password(REDIS_URL, REDIS_PASSWORD)
        pool = redis.ConnectionPool.from_url(
            url,
            decode_responses=False,  # We'll decode in the caller
            socket_connect_timeout=5,
            socket_timeout=5,
            max_connections=50,  # Max connections per event loop (scalable via horizontal scaling)
            retry_on_timeout=True,
            # Health check to detect stale connections
            health_check_interval=30,  # Check connection health every 30 seconds
        )
        _pools_by_loop[loop] = pool
        logger.info("Redis connection pool created for loop %s", id(loop))

    # Create new client for this event loop using the per-loop pool
    client = redis.Redis(connection_pool=pool)
    _clients_by_loop[loop] = client
    logger.info("Redis client created for loop %s", id(loop))
    
    return client


async def close_redis_for_current_loop() -> None:
    """
    Close Redis client and pool for the current event loop.
    CRITICAL: Must be called from within the same loop that created the client/pool.
    
    This is useful for explicit cleanup, but WeakKeyDictionary will automatically
    clean up when loops are garbage collected.
    """
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        logger.warning("close_redis_for_current_loop() called without a running loop - skipping")
        return

    # Close client if it exists
    client = _clients_by_loop.pop(loop, None)
    if client is not None:
        try:
            # Try aclose() first (newer redis-py versions)
            if hasattr(client, 'aclose'):
                await client.aclose()
            else:
                await client.close()
            logger.info("Redis client closed for loop %s", id(loop))
        except Exception as e:
            logger.error(f"Error closing Redis client for loop {id(loop)}: {e}", exc_info=True)

    # Disconnect pool if it exists
    pool = _pools_by_loop.pop(loop, None)
    if pool is not None:
        try:
            # Try async disconnect first
            if hasattr(pool, 'disconnect') and asyncio.iscoroutinefunction(pool.disconnect):
                await pool.disconnect(inuse_connections=True)
            else:
                # Fallback for sync disconnect
                pool.disconnect(inuse_connections=True)
            logger.info("Redis pool disconnected for loop %s", id(loop))
        except Exception as e:
            logger.warning(f"Error disconnecting Redis pool for loop {id(loop)}: {e}")




class RobustRedisPubSub:
    """Wrapper for Redis Pub/Sub with health checks and auto-recovery."""

    def __init__(self, redis_client: redis.Redis, channel: str):
        """
        Initialize robust Redis Pub/Sub client.

        Args:
            redis_client: Redis async client
            channel: Channel to subscribe to
        """
        self.redis_client = redis_client
        self.channel = channel
        self.pubsub: Optional[redis.client.PubSub] = None
        self._last_message_time: float = 0
        self._health_check_interval: float = 30.0
        self._connected: bool = False

    async def connect(self) -> bool:
        """Connect and subscribe to channel with health check."""
        try:
            self.pubsub = self.redis_client.pubsub()
            await self.pubsub.subscribe(self.channel)

            # Wait for subscription confirmation
            confirm_msg = await asyncio.wait_for(
                self.pubsub.get_message(ignore_subscribe_messages=False),
                timeout=5.0
            )
            if confirm_msg and confirm_msg['type'] == 'subscribe':
                self._connected = True
                self._last_message_time = time.time()
                logger.info(f"Connected to channel: {self.channel}")
                return True

            logger.error(f"Failed to subscribe to {self.channel}")
            return False
        except Exception as e:
            logger.error(f"Connection error: {e}", exc_info=True)
            return False

    async def is_healthy(self) -> bool:
        """Check if connection is healthy."""
        if not self._connected or not self.pubsub:
            return False

        try:
            # Check if connection is alive via PING
            await self.redis_client.ping()

            # Check if we've received messages recently
            time_since_last_msg = time.time() - self._last_message_time
            if time_since_last_msg > self._health_check_interval:
                # Send a heartbeat message and expect to receive it
                test_msg = {"type": "ping", "timestamp": time.time()}
                await self.redis_client.publish(self.channel, json.dumps(test_msg))

            return True
        except Exception as e:
            logger.warning(f"Health check failed: {e}")
            return False

    async def listen(self):
        """
        Listen for messages with automatic reconnection.

        Yields:
            Dict with message data
        """
        reconnect_backoff = [1, 2, 5, 10, 30]  # seconds
        reconnect_attempt = 0

        while True:
            # Ensure we're connected
            if not self._connected:
                if reconnect_attempt < len(reconnect_backoff):
                    wait_time = reconnect_backoff[reconnect_attempt]
                    logger.info(f"Reconnecting in {wait_time}s (attempt {reconnect_attempt + 1})")
                    await asyncio.sleep(wait_time)
                    reconnect_attempt += 1
                else:
                    logger.error(f"Max reconnection attempts reached for {self.channel}")
                    raise ConnectionError(f"Failed to reconnect to {self.channel}")

                # Try to reconnect
                if not await self.connect():
                    continue

                # Reset backoff on successful reconnection
                reconnect_attempt = 0

            # Check health periodically
            if not await self.is_healthy():
                logger.warning(f"Connection unhealthy, reconnecting...")
                self._connected = False
                await self.disconnect()
                continue

            # Listen for messages
            try:
                message = await asyncio.wait_for(
                    self.pubsub.get_message(ignore_subscribe_messages=True),
                    timeout=5.0
                )

                if message and message['type'] == 'message':
                    self._last_message_time = time.time()
                    data = json.loads(message['data'].decode('utf-8'))

                    # Skip internal ping messages
                    if data.get('type') != 'ping':
                        yield data

            except asyncio.TimeoutError:
                # No message, continue (used for health checks)
                continue
            except Exception as e:
                logger.error(f"Error receiving message: {e}", exc_info=True)
                self._connected = False
                await self.disconnect()

    async def disconnect(self):
        """Gracefully disconnect from channel."""
        if self.pubsub:
            try:
                await self.pubsub.unsubscribe(self.channel)
                await self.pubsub.close()
            except Exception as e:
                logger.debug(f"Error during disconnect: {e}")
            finally:
                self.pubsub = None
                self._connected = False


class RobustRedisPublisher:
    """Redis publisher with retry logic and circuit breaker."""

    def __init__(self, redis_client: redis.Redis):
        """
        Initialize robust Redis publisher.

        Args:
            redis_client: Redis async client
        """
        self.redis_client = redis_client
        self._circuit_breaker_failures = 0
        self._circuit_breaker_threshold = 5
        self._circuit_breaker_reset_time = 60.0
        self._last_failure_time = 0

    async def publish(
        self,
        channel: str,
        message: dict,
        max_retries: int = 3,
        retry_backoff: float = 1.0
    ) -> bool:
        """
        Publish message with retry logic.

        Args:
            channel: Redis channel
            message: Message dict to publish
            max_retries: Maximum retry attempts
            retry_backoff: Initial backoff in seconds (exponential)

        Returns:
            True if published successfully, False otherwise
        """
        # Check circuit breaker
        if self._is_circuit_open():
            logger.warning(f"Circuit breaker open for Redis publish, dropping message")
            return False

        # Serialize message
        try:
            serialized = json.dumps(message, default=str)
        except Exception as e:
            logger.error(f"Failed to serialize message: {e}")
            return False

        # Try to publish with retries
        for attempt in range(max_retries):
            try:
                # Publish message
                num_subscribers = await self.redis_client.publish(channel, serialized)

                # Reset circuit breaker on success
                self._circuit_breaker_failures = 0

                # Log warning if no subscribers (not an error, but worth noting)
                if num_subscribers == 0:
                    logger.debug(f"Published to {channel} but no subscribers")
                else:
                    logger.debug(f"Published to {channel} ({num_subscribers} subscribers)")

                return True

            except (redis.ConnectionError, redis.TimeoutError) as e:
                logger.warning(f"Redis connection error on publish (attempt {attempt + 1}/{max_retries}): {e}")

                # Increment circuit breaker
                self._circuit_breaker_failures += 1
                self._last_failure_time = time.time()

                if attempt < max_retries - 1:
                    # Exponential backoff
                    wait_time = retry_backoff * (2 ** attempt)
                    await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Failed to publish after {max_retries} attempts")
                    return False

            except Exception as e:
                logger.error(f"Unexpected error publishing message: {e}", exc_info=True)
                return False

        return False

    def _is_circuit_open(self) -> bool:
        """Check if circuit breaker is open."""
        if self._circuit_breaker_failures >= self._circuit_breaker_threshold:
            # Check if we should reset
            time_since_failure = time.time() - self._last_failure_time
            if time_since_failure > self._circuit_breaker_reset_time:
                logger.info("Resetting circuit breaker")
                self._circuit_breaker_failures = 0
                return False
            return True
        return False


class MessageBuffer:
    """In-memory buffer for recent messages per channel."""

    def __init__(self, max_messages: int = 100, ttl_seconds: int = 300):
        """
        Initialize message buffer.

        Args:
            max_messages: Maximum messages to keep per channel
            ttl_seconds: Time-to-live for messages in seconds
        """
        self._buffers: Dict[str, deque] = {}
        self._max_messages = max_messages
        self._ttl_seconds = ttl_seconds
        self._lock = asyncio.Lock()

    async def add(self, channel: str, message: dict):
        """Add message to buffer."""
        async with self._lock:
            if channel not in self._buffers:
                self._buffers[channel] = deque(maxlen=self._max_messages)

            # Add timestamp if not present
            if 'timestamp' not in message:
                message['timestamp'] = time.time()

            self._buffers[channel].append(message)

    async def get_recent(
        self,
        channel: str,
        since_timestamp: Optional[float] = None,
        max_count: int = 50
    ) -> List[dict]:
        """
        Get recent messages from buffer.

        Args:
            channel: Channel name
            since_timestamp: Only return messages after this timestamp
            max_count: Maximum messages to return

        Returns:
            List of messages
        """
        async with self._lock:
            if channel not in self._buffers:
                return []

            now = time.time()
            messages = []

            for msg in self._buffers[channel]:
                # Skip expired messages
                msg_time = msg.get('timestamp', 0)
                if now - msg_time > self._ttl_seconds:
                    continue

                # Skip messages before cutoff
                if since_timestamp and msg_time <= since_timestamp:
                    continue

                messages.append(msg)

                if len(messages) >= max_count:
                    break

            return messages

    async def cleanup(self):
        """Remove expired messages from all channels."""
        async with self._lock:
            now = time.time()
            for channel, buffer in list(self._buffers.items()):
                # Remove expired messages
                while buffer and (now - buffer[0].get('timestamp', 0)) > self._ttl_seconds:
                    buffer.popleft()

                # Remove empty buffers
                if not buffer:
                    del self._buffers[channel]


# Global message buffer instance
_message_buffer = MessageBuffer(max_messages=100, ttl_seconds=300)


async def get_message_buffer() -> MessageBuffer:
    """Get global message buffer instance."""
    return _message_buffer


class RedisStreamManager:
    """Redis Streams manager for durable message delivery."""

    def __init__(self, client: redis.Redis):
        """
        Initialize Redis Streams manager.

        Args:
            client: Redis async client
        """
        self.client = client
    
    async def publish_event(
        self, 
        stream_key: str, 
        event: Dict[str, Any],
        max_len: int = 1000
    ) -> str:
        """
        Publish event to stream with automatic trimming.
        
        Args:
            stream_key: Stream key (e.g., "chat:{user_id}:{session_id}")
            event: Event dictionary to publish
            max_len: Maximum stream length (trims old messages)
            
        Returns:
            Message ID
        """
        # Serialize event
        event_data = {
            "data": json.dumps(event, default=str),
            "timestamp": str(time.time())
        }
        
        # Add to stream with max length
        message_id = await self.client.xadd(
            stream_key,
            event_data,
            maxlen=max_len,
            approximate=True
        )
        
        return message_id
    
    async def read_events(
        self,
        stream_key: str,
        last_id: str = "0",
        count: int = 100,
        block: int = 5000  # 5 second block
    ) -> List[Dict[str, Any]]:
        """
        Read events from stream.
        
        Args:
            stream_key: Stream key
            last_id: Last message ID read (use "0" for all messages)
            count: Maximum number of messages to read
            block: Block timeout in milliseconds (0 = non-blocking)
            
        Returns:
            List of events with id and event data
        """
        result = await self.client.xread(
            {stream_key: last_id},
            count=count,
            block=block
        )
        
        if not result:
            return []
        
        events = []
        for stream_name, messages in result:
            for message_id, fields in messages:
                event = json.loads(fields[b"data"].decode())
                events.append({
                    "id": message_id.decode() if isinstance(message_id, bytes) else message_id,
                    "event": event
                })
        
        return events
    
    async def create_consumer_group(
        self,
        stream_key: str,
        group_name: str,
        start_id: str = "0"
    ) -> bool:
        """
        Create consumer group for stream.
        
        Args:
            stream_key: Stream key
            group_name: Consumer group name
            start_id: Starting message ID
            
        Returns:
            True if created, False if already exists
        """
        try:
            await self.client.xgroup_create(
                stream_key,
                group_name,
                id=start_id,
                mkstream=True
            )
            return True
        except redis.ResponseError as e:
            if "BUSYGROUP" in str(e):
                # Group already exists
                return False
            raise
    
    async def read_group_events(
        self,
        stream_key: str,
        group_name: str,
        consumer_name: str,
        count: int = 100,
        block: int = 5000
    ) -> List[Dict[str, Any]]:
        """
        Read events from stream using consumer group.
        
        Args:
            stream_key: Stream key
            group_name: Consumer group name
            consumer_name: Consumer name
            count: Maximum number of messages to read
            block: Block timeout in milliseconds
            
        Returns:
            List of events with id and event data
        """
        result = await self.client.xreadgroup(
            group_name,
            consumer_name,
            {stream_key: ">"},
            count=count,
            block=block
        )
        
        if not result:
            return []
        
        events = []
        for stream_name, messages in result:
            for message_id, fields in messages:
                event = json.loads(fields[b"data"].decode())
                events.append({
                    "id": message_id.decode() if isinstance(message_id, bytes) else message_id,
                    "event": event
                })
        
        return events
    
    async def ack_event(
        self,
        stream_key: str,
        group_name: str,
        message_id: str
    ) -> int:
        """
        Acknowledge event processing.
        
        Args:
            stream_key: Stream key
            group_name: Consumer group name
            message_id: Message ID to acknowledge
            
        Returns:
            Number of acknowledged messages
        """
        return await self.client.xack(stream_key, group_name, message_id)
