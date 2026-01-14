# Redis Pub/Sub Robustness Plan

## Overview

This plan addresses known issues with the current Redis Pub/Sub implementation and provides a comprehensive strategy to make it production-ready, focusing on reliability, error handling, and operational excellence.

## Current Issues

### 1. Connection Management
- **Problem**: Connection pool per event loop, but no health checks
- **Impact**: Stale connections can cause message loss
- **Risk**: High

### 2. Message Loss on Disconnect
- **Problem**: No message buffer or catch-up mechanism
- **Impact**: Clients miss messages during brief disconnections
- **Risk**: Medium

### 3. Subscription Lifecycle
- **Problem**: Complex subscription/reconnection logic with potential race conditions
- **Impact**: Messages can be lost during reconnection window
- **Risk**: Medium

### 4. Publisher Failures
- **Problem**: No retry logic for failed publishes
- **Impact**: Messages silently lost if Redis is temporarily unavailable
- **Risk**: High

### 5. Memory Leaks
- **Problem**: Pub/Sub subscriptions not always cleaned up properly
- **Impact**: Memory growth over time
- **Risk**: Medium

### 6. No Observability
- **Problem**: Limited metrics and monitoring
- **Impact**: Hard to debug issues in production
- **Risk**: Medium

---

## Phase 1: Connection Robustness (Priority: CRITICAL)

### Task 1.1: Add Connection Health Checks

**Goal**: Detect and recover from stale connections automatically

**Implementation**:

```python
# backend/app/core/redis.py

class RobustRedisPubSub:
    """Wrapper for Redis Pub/Sub with health checks and auto-recovery."""

    def __init__(self, redis_client: redis.Redis, channel: str):
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
            confirm_msg = await self.pubsub.get_message(timeout=5.0)
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

    async def listen(self) -> AsyncIterator[dict]:
        """Listen for messages with automatic reconnection."""
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
```

**Files to Modify**:
- `backend/app/core/redis.py` - Add `RobustRedisPubSub` class
- `backend/app/api/agent.py` - Replace raw pubsub with `RobustRedisPubSub`
- `backend/app/api/documents.py` - Replace raw pubsub with `RobustRedisPubSub`

**Testing**:
- Test reconnection after Redis restart
- Test reconnection after network blip
- Test stale connection detection

---

## Phase 2: Publisher Reliability (Priority: HIGH)

### Task 2.1: Add Retry Logic to Publishers

**Goal**: Ensure messages are published even during transient failures

**Implementation**:

```python
# backend/app/core/redis.py

class RobustRedisPublisher:
    """Redis publisher with retry logic and circuit breaker."""

    def __init__(self, redis_client: redis.Redis):
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

            except redis.ConnectionError as e:
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
```

**Files to Modify**:
- `backend/app/core/redis.py` - Add `RobustRedisPublisher` class
- `backend/app/agents/temporal/activity.py` - Use `RobustRedisPublisher`

**Testing**:
- Test publish during Redis restart
- Test circuit breaker activation
- Test circuit breaker reset

---

## Phase 3: Message Buffering (Priority: MEDIUM)

### Task 3.1: Add Client-Side Message Buffer

**Goal**: Allow clients to catch up on missed messages after brief disconnections

**Implementation**:

```python
# backend/app/core/redis.py

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
```

**Files to Modify**:
- `backend/app/core/redis.py` - Add `MessageBuffer` class
- `backend/app/agents/temporal/activity.py` - Add messages to buffer when publishing
- `backend/app/api/agent.py` - Allow clients to request recent messages on connect

**API Enhancement**:
```python
# In agent.py SSE endpoint
@router.post("/agent/stream/")
async def event_stream(
    request: StreamAgentRequest,
    user: User = Depends(get_current_user)
):
    # ... existing code ...

    # If client provides last_seen_timestamp, send buffered messages first
    if request.last_seen_timestamp:
        message_buffer = await get_message_buffer()
        recent_messages = await message_buffer.get_recent(
            channel=channel,
            since_timestamp=request.last_seen_timestamp
        )

        for msg in recent_messages:
            yield f"data: {json.dumps(msg)}\n\n"

    # Then continue with live stream
    # ... rest of existing code ...
```

**Testing**:
- Test catch-up after 5 second disconnect
- Test buffer overflow (more than 100 messages)
- Test TTL expiration

---

## Phase 4: Observability (Priority: MEDIUM)

### Task 4.1: Add Metrics and Monitoring

**Goal**: Track Redis Pub/Sub health and performance

**Implementation**:

```python
# backend/app/observability/metrics.py

from prometheus_client import Counter, Histogram, Gauge

# Redis Pub/Sub metrics
redis_pubsub_messages_published = Counter(
    'redis_pubsub_messages_published_total',
    'Total messages published to Redis Pub/Sub',
    ['channel', 'status']  # status: success, failure
)

redis_pubsub_messages_received = Counter(
    'redis_pubsub_messages_received_total',
    'Total messages received from Redis Pub/Sub',
    ['channel']
)

redis_pubsub_publish_duration = Histogram(
    'redis_pubsub_publish_duration_seconds',
    'Time to publish message to Redis',
    ['channel']
)

redis_pubsub_active_subscriptions = Gauge(
    'redis_pubsub_active_subscriptions',
    'Number of active Pub/Sub subscriptions',
    ['channel']
)

redis_pubsub_reconnections = Counter(
    'redis_pubsub_reconnections_total',
    'Total number of reconnections',
    ['channel', 'reason']
)

redis_pubsub_buffer_size = Gauge(
    'redis_pubsub_buffer_size',
    'Number of messages in buffer per channel',
    ['channel']
)


def record_publish(channel: str, duration: float, status: str):
    """Record message publish metrics."""
    redis_pubsub_messages_published.labels(channel=channel, status=status).inc()
    redis_pubsub_publish_duration.labels(channel=channel).observe(duration)


def record_receive(channel: str):
    """Record message receive metrics."""
    redis_pubsub_messages_received.labels(channel=channel).inc()


def record_reconnection(channel: str, reason: str):
    """Record reconnection event."""
    redis_pubsub_reconnections.labels(channel=channel, reason=reason).inc()
```

**Files to Modify**:
- `backend/app/observability/metrics.py` - Add metrics definitions
- `backend/app/core/redis.py` - Instrument `RobustRedisPubSub` and `RobustRedisPublisher`
- `backend/app/api/agent.py` - Track active subscriptions

**Grafana Dashboard**:
Create dashboard with:
- Messages published/received per second
- Publish latency (p50, p95, p99)
- Active subscriptions
- Reconnection rate
- Buffer size over time
- Circuit breaker state

**Testing**:
- Verify metrics are exposed at `/metrics` endpoint
- Test metric collection under load
- Create Grafana dashboard

---

## Phase 5: Testing & Validation (Priority: HIGH)

### Task 5.1: Comprehensive Integration Tests

**Goal**: Ensure robustness under failure conditions

**Test Scenarios**:

```python
# tests/integration/test_redis_pubsub_robustness.py

import pytest
import asyncio
from app.core.redis import RobustRedisPubSub, RobustRedisPublisher

class TestRedisPubSubRobustness:

    @pytest.mark.asyncio
    async def test_reconnect_after_redis_restart(self):
        """Test that subscriber reconnects after Redis restart."""
        # 1. Subscribe to channel
        # 2. Publish message, verify received
        # 3. Restart Redis
        # 4. Publish message, verify received (after reconnection)
        pass

    @pytest.mark.asyncio
    async def test_message_buffering(self):
        """Test that clients can catch up on missed messages."""
        # 1. Publish 10 messages
        # 2. Disconnect client
        # 3. Publish 5 more messages
        # 4. Reconnect client with last_seen_timestamp
        # 5. Verify client receives 5 buffered messages
        pass

    @pytest.mark.asyncio
    async def test_circuit_breaker_activation(self):
        """Test that circuit breaker opens after failures."""
        # 1. Simulate Redis connection failures
        # 2. Verify circuit breaker opens after 5 failures
        # 3. Wait for reset timeout
        # 4. Verify circuit breaker closes
        pass

    @pytest.mark.asyncio
    async def test_concurrent_subscribers(self):
        """Test multiple subscribers on same channel."""
        # 1. Create 10 subscribers to same channel
        # 2. Publish 100 messages
        # 3. Verify all subscribers receive all messages
        pass

    @pytest.mark.asyncio
    async def test_stale_connection_detection(self):
        """Test that stale connections are detected and replaced."""
        # 1. Subscribe to channel
        # 2. Simulate network partition (block Redis traffic)
        # 3. Wait for health check to fail
        # 4. Verify reconnection
        pass

    @pytest.mark.asyncio
    async def test_memory_leak_prevention(self):
        """Test that subscriptions are properly cleaned up."""
        # 1. Create and destroy 100 subscriptions
        # 2. Check memory usage
        # 3. Verify no leaks
        pass
```

**Files to Create**:
- `backend/tests/integration/test_redis_pubsub_robustness.py`
- `backend/tests/load/test_redis_pubsub_load.py`

---

## Phase 6: Documentation (Priority: LOW)

### Task 6.1: Document Redis Pub/Sub Architecture

**Files to Create**:
- `docs/architecture/redis-pubsub.md` - Architecture overview
- `docs/operations/redis-monitoring.md` - Monitoring and alerting
- `docs/operations/redis-troubleshooting.md` - Common issues and fixes

**Content**:
- Message flow diagram
- Reconnection strategy
- Buffer behavior
- Circuit breaker logic
- Metrics and alerts
- Troubleshooting guide

---

## Implementation Timeline

### Week 1: Critical Fixes
- ✅ Phase 1: Connection Robustness
- ✅ Phase 2: Publisher Reliability

### Week 2: Resilience
- ✅ Phase 3: Message Buffering
- ✅ Phase 5: Integration Tests

### Week 3: Operations
- ✅ Phase 4: Observability
- ✅ Phase 6: Documentation

---

## Success Criteria

1. **Zero Message Loss**: Messages are delivered or explicitly dropped (circuit breaker)
2. **Automatic Recovery**: System recovers from Redis failures within 30 seconds
3. **Observability**: All key metrics tracked and dashboarded
4. **Test Coverage**: 90%+ coverage for Redis code
5. **Documentation**: Complete runbook for operations

---

## Risks and Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Buffer memory growth | High | Implement TTL and max size limits |
| Reconnection storms | Medium | Exponential backoff with jitter |
| Message duplication | Low | Accept duplicates (Pub/Sub is at-most-once) |
| Circuit breaker false positives | Low | Tune thresholds based on production metrics |

---

## Alternative: Migrate to Redis Streams

If Pub/Sub proves insufficient after these improvements, consider migrating to Redis Streams:

**Advantages**:
- Native message persistence
- Consumer groups for load balancing
- Acknowledgment support
- Message history

**Migration Effort**: ~1 week

**Decision Point**: Revisit after Phase 5 testing

---

## Summary

This plan provides a comprehensive strategy to make Redis Pub/Sub production-ready without migrating to Redis Streams. The phased approach allows for incremental improvements while maintaining system stability.

**Key Improvements**:
1. ✅ Automatic reconnection with health checks
2. ✅ Publisher retry logic with circuit breaker
3. ✅ Client-side message buffering for catch-up
4. ✅ Comprehensive metrics and monitoring
5. ✅ Robust integration tests

**Estimated Effort**: 3 weeks (1 engineer)

**Status**: Ready for implementation
