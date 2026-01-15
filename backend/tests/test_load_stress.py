"""
Load and Stress Tests for Agent Playground.

Tests scalability, performance, and stress handling for:
- Temporal workflows (concurrent execution, throughput)
- Redis pub/sub (message throughput, latency, channel isolation)
- API endpoints (concurrent requests, rate limiting)
- Database operations (concurrent writes, session management)
"""
import asyncio
import json
import time
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional
from django.test import TransactionTestCase, override_settings
from django.contrib.auth import get_user_model
from django.core.cache import cache
from unittest.mock import patch, AsyncMock, MagicMock

from app.db.models.session import ChatSession
from app.db.models.message import Message
from app.services.chat_service import create_session, add_message
from app.core.redis import get_redis_client
from app.agents.temporal.workflow_manager import get_or_create_workflow, send_message_signal

User = get_user_model()


class MetricsCollector:
    """Collects and analyzes performance metrics."""
    
    def __init__(self):
        self.metrics: Dict[str, List[float]] = {}
        self.counts: Dict[str, int] = {}
        self.errors: List[Dict[str, Any]] = []
    
    def record(self, metric_name: str, value: float, count: int = 1):
        """Record a metric value."""
        if metric_name not in self.metrics:
            self.metrics[metric_name] = []
            self.counts[metric_name] = 0
        self.metrics[metric_name].append(value)
        self.counts[metric_name] += count
    
    def record_error(self, error_type: str, error_msg: str, context: Dict = None):
        """Record an error."""
        self.errors.append({
            'type': error_type,
            'message': error_msg,
            'context': context or {}
        })
    
    def get_stats(self, metric_name: str) -> Dict[str, float]:
        """Get statistics for a metric."""
        if metric_name not in self.metrics or not self.metrics[metric_name]:
            return {}
        
        values = self.metrics[metric_name]
        return {
            'count': len(values),
            'min': min(values),
            'max': max(values),
            'mean': statistics.mean(values),
            'median': statistics.median(values),
            'stdev': statistics.stdev(values) if len(values) > 1 else 0.0,
            'p50': statistics.median(values),
            'p95': self._percentile(values, 95),
            'p99': self._percentile(values, 99),
        }
    
    def _percentile(self, data: List[float], percentile: float) -> float:
        """Calculate percentile."""
        sorted_data = sorted(data)
        index = int(len(sorted_data) * percentile / 100)
        return sorted_data[min(index, len(sorted_data) - 1)]
    
    def print_report(self):
        """Print a formatted report of all metrics."""
        print("\n" + "="*80)
        print("PERFORMANCE BENCHMARK REPORT")
        print("="*80)
        
        for metric_name in sorted(self.metrics.keys()):
            stats = self.get_stats(metric_name)
            if stats:
                print(f"\n{metric_name}:")
                print(f"  Count: {stats['count']}")
                print(f"  Min: {stats['min']:.3f}s")
                print(f"  Max: {stats['max']:.3f}s")
                print(f"  Mean: {stats['mean']:.3f}s")
                print(f"  Median: {stats['median']:.3f}s")
                print(f"  P95: {stats['p95']:.3f}s")
                print(f"  P99: {stats['p99']:.3f}s")
                print(f"  StdDev: {stats['stdev']:.3f}s")
        
        if self.errors:
            print(f"\nErrors: {len(self.errors)}")
            error_types = {}
            for error in self.errors:
                error_type = error['type']
                error_types[error_type] = error_types.get(error_type, 0) + 1
            for error_type, count in error_types.items():
                print(f"  {error_type}: {count}")
        
        print("\n" + "="*80)


class TestConcurrentUsers(TransactionTestCase):
    """Test concurrent user load."""
    
    def setUp(self):
        """Set up test data."""
        self.metrics = MetricsCollector()
        self.users: List[User] = []
        self.sessions: List[ChatSession] = []
    
    def test_concurrent_session_creation(self, num_users: int = 50):
        """Test creating sessions concurrently."""
        print(f"\nTesting concurrent session creation with {num_users} users...")
        
        def create_user_and_session(user_id: int):
            """Create a user and session."""
            start_time = time.time()
            try:
                user = User.objects.create_user(
                    email=f'load_test_{user_id}@example.com',
                    password='testpass123'
                )
                session = create_session(user.id, f"Load Test Session {user_id}")
                elapsed = time.time() - start_time
                self.metrics.record('session_creation', elapsed)
                return (user, session)
            except Exception as e:
                self.metrics.record_error('session_creation', str(e), {'user_id': user_id})
                return None
        
        # Execute concurrently
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = [executor.submit(create_user_and_session, i) for i in range(num_users)]
            results = [f.result() for f in as_completed(futures)]
        
        # Store results
        for result in results:
            if result:
                self.users.append(result[0])
                self.sessions.append(result[1])
        
        # Verify
        self.assertEqual(len(self.sessions), num_users)
        stats = self.metrics.get_stats('session_creation')
        print(f"Created {stats['count']} sessions")
        print(f"Mean time: {stats['mean']:.3f}s, P95: {stats['p95']:.3f}s")
        self.metrics.print_report()
    
    def test_concurrent_messages(self, num_messages: int = 100):
        """Test adding messages concurrently."""
        print(f"\nTesting concurrent message creation with {num_messages} messages...")
        
        # Create test sessions
        user = User.objects.create_user(
            email='concurrent_messages@example.com',
            password='testpass123'
        )
        sessions = [create_session(user.id, f"Session {i}") for i in range(10)]
        
        def add_test_message(session_id: int, message_num: int):
            """Add a message to a session."""
            start_time = time.time()
            try:
                msg = add_message(session_id, 'user', f'Message {message_num}')
                elapsed = time.time() - start_time
                self.metrics.record('message_creation', elapsed)
                return msg
            except Exception as e:
                self.metrics.record_error('message_creation', str(e), {
                    'session_id': session_id,
                    'message_num': message_num
                })
                return None
        
        # Distribute messages across sessions
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = []
            for i in range(num_messages):
                session = sessions[i % len(sessions)]
                futures.append(executor.submit(add_test_message, session.id, i))
            
            results = [f.result() for f in as_completed(futures)]
        
        # Verify
        successful = sum(1 for r in results if r is not None)
        self.assertGreater(successful, num_messages * 0.95, "At least 95% should succeed")
        
        stats = self.metrics.get_stats('message_creation')
        print(f"Created {successful}/{num_messages} messages")
        print(f"Mean time: {stats['mean']:.3f}s, P95: {stats['p95']:.3f}s")
        self.metrics.print_report()


class TestRedisPubSubPerformance(TransactionTestCase):
    """Test Redis pub/sub performance and scalability."""
    
    def setUp(self):
        """Set up test data."""
        self.metrics = MetricsCollector()
    
    def test_redis_publish_throughput(self, num_messages: int = 1000):
        """Test Redis publish throughput (sync wrapper for async test)."""
        asyncio.run(self._test_redis_publish_throughput_async(num_messages))
    
    async def _test_redis_publish_throughput_async(self, num_messages: int = 1000):
        """Test Redis publish throughput."""
        print(f"\nTesting Redis publish throughput with {num_messages} messages...")
        
        redis_client = await get_redis_client()
        channel = "test:load:throughput"
        
        # Warm up
        await redis_client.publish(channel, json.dumps({"type": "warmup"}).encode())
        await asyncio.sleep(0.1)
        
        # Publish messages
        start_time = time.time()
        tasks = []
        for i in range(num_messages):
            message = json.dumps({
                "type": "test",
                "data": {"id": i, "content": f"Message {i}"}
            }).encode()
            tasks.append(redis_client.publish(channel, message))
        
        # Wait for all publishes
        results = await asyncio.gather(*tasks, return_exceptions=True)
        total_time = time.time() - start_time
        
        # Calculate metrics
        successful = sum(1 for r in results if not isinstance(r, Exception))
        throughput = successful / total_time if total_time > 0 else 0
        
        print(f"Published {successful}/{num_messages} messages in {total_time:.3f}s")
        print(f"Throughput: {throughput:.0f} messages/second")
        
        self.assertGreater(successful, num_messages * 0.99, "At least 99% should succeed")
        self.assertGreater(throughput, 1000, "Should handle at least 1000 msg/s")
    
    def test_redis_subscription_latency(self, num_messages: int = 100):
        """Test Redis subscription latency (sync wrapper for async test)."""
        asyncio.run(self._test_redis_subscription_latency_async(num_messages))
    
    async def _test_redis_subscription_latency_async(self, num_messages: int = 100):
        """Test Redis subscription latency."""
        print(f"\nTesting Redis subscription latency with {num_messages} messages...")
        
        redis_client = await get_redis_client()
        channel = "test:load:latency"
        
        # Subscribe
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(channel)
        
        # Wait for subscription confirmation
        confirm_msg = await pubsub.get_message(timeout=5.0)
        self.assertIsNotNone(confirm_msg)
        
        # Publish and measure latency
        latencies = []
        for i in range(num_messages):
            message = json.dumps({
                "type": "test",
                "id": i,
                "timestamp": time.time()
            }).encode()
            
            publish_time = time.time()
            await redis_client.publish(channel, message)
            
            # Receive message
            msg = await pubsub.get_message(timeout=1.0)
            if msg and msg['type'] == 'message':
                receive_time = time.time()
                latency = receive_time - publish_time
                latencies.append(latency)
                self.metrics.record('redis_subscription_latency', latency)
        
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        
        if latencies:
            stats = self.metrics.get_stats('redis_subscription_latency')
            print(f"Received {len(latencies)}/{num_messages} messages")
            print(f"Mean latency: {stats['mean']*1000:.2f}ms, P95: {stats['p95']*1000:.2f}ms")
            self.assertLess(stats['p95'], 0.1, "P95 latency should be < 100ms")
        
        self.metrics.print_report()
    
    def test_concurrent_channels(self, num_channels: int = 50):
        """Test concurrent Redis channels (sync wrapper for async test)."""
        asyncio.run(self._test_concurrent_channels_async(num_channels))
    
    async def _test_concurrent_channels_async(self, num_channels: int = 50):
        """Test concurrent Redis channels (simulating multiple sessions)."""
        print(f"\nTesting {num_channels} concurrent Redis channels...")
        
        redis_client = await get_redis_client()
        channels = [f"test:load:channel:{i}" for i in range(num_channels)]
        
        # Create subscriptions with connection reuse (limit concurrent connections)
        subscriptions = []
        # Use a single pubsub instance for all channels to reduce connections
        pubsub = redis_client.pubsub()
        for channel in channels:
            await pubsub.subscribe(channel)
            subscriptions.append(channel)
        
        # Wait for all subscription confirmations
        confirm_count = 0
        while confirm_count < num_channels:
            msg = await pubsub.get_message(timeout=2.0)
            if msg and msg['type'] == 'subscribe':
                confirm_count += 1
        
        # Publish to all channels concurrently (but batch to avoid connection exhaustion)
        start_time = time.time()
        batch_size = 10
        for i in range(0, len(channels), batch_size):
            batch_channels = channels[i:i+batch_size]
            publish_tasks = []
            for channel in batch_channels:
                message = json.dumps({"type": "test", "channel": channel}).encode()
                publish_tasks.append(redis_client.publish(channel, message))
            await asyncio.gather(*publish_tasks)
        
        # Receive from all channels
        received = 0
        timeout = time.time() + 5.0  # 5 second timeout
        while received < num_channels and time.time() < timeout:
            msg = await pubsub.get_message(timeout=1.0)
            if msg and msg['type'] == 'message':
                received += 1
        
        total_time = time.time() - start_time
        
        print(f"Successfully handled {received}/{num_channels} channels in {total_time:.3f}s")
        self.assertGreater(received, num_channels * 0.90, "At least 90% should succeed")
        
        # Cleanup
        for channel in subscriptions:
            await pubsub.unsubscribe(channel)
        await pubsub.close()


class TestTemporalWorkflowScalability(TransactionTestCase):
    """Test Temporal workflow scalability."""
    
    def setUp(self):
        """Set up test data."""
        self.metrics = MetricsCollector()
        self.user = User.objects.create_user(
            email='temporal_load@example.com',
            password='testpass123'
        )
    
    def test_concurrent_workflow_creation(self, num_workflows: int = 20):
        """Test creating workflows concurrently (sync wrapper for async test)."""
        # Create sessions in sync context first
        sessions = [create_session(self.user.id, f"Workflow Test {i}") for i in range(num_workflows)]
        # Then run async test
        asyncio.run(self._test_concurrent_workflow_creation_async(sessions))
    
    async def _test_concurrent_workflow_creation_async(self, sessions: List):
        """Test creating workflows concurrently."""
        num_workflows = len(sessions)
        print(f"\nTesting concurrent workflow creation with {num_workflows} workflows...")
        
        # Mock Temporal client
        from unittest.mock import patch, AsyncMock, MagicMock
        with patch('app.agents.temporal.workflow_manager.get_temporal_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_workflow_handle = MagicMock()
            mock_workflow_handle.id = "test-workflow-id"
            mock_client.start_workflow.return_value = mock_workflow_handle
            mock_get_client.return_value = mock_client
            
            # Create workflows concurrently
            start_time = time.time()
            tasks = []
            for session in sessions:
                task = get_or_create_workflow(
                    self.user.id,
                    session.id,
                    initial_state={
                        "user_id": self.user.id,
                        "session_id": session.id,
                        "message": f"Test message for session {session.id}",
                        "flow": "main"
                    }
                )
                tasks.append(task)
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            total_time = time.time() - start_time
            
            successful = sum(1 for r in results if not isinstance(r, Exception))
            
            print(f"Created {successful}/{num_workflows} workflows in {total_time:.3f}s")
            print(f"Throughput: {successful/total_time:.1f} workflows/second")
            
            self.assertGreater(successful, num_workflows * 0.95, "At least 95% should succeed")
    
    def test_workflow_signal_throughput(self, num_signals: int = 100):
        """Test sending signals to workflows (sync wrapper for async test)."""
        # Create session in sync context first
        session = create_session(self.user.id, "Signal Test")
        # Then run async test
        asyncio.run(self._test_workflow_signal_throughput_async(session, num_signals))
    
    async def _test_workflow_signal_throughput_async(self, session, num_signals: int = 100):
        """Test sending signals to workflows."""
        print(f"\nTesting workflow signal throughput with {num_signals} signals...")
        
        # Mock Temporal client
        from unittest.mock import patch, AsyncMock, MagicMock
        with patch('app.agents.temporal.workflow_manager.get_temporal_client') as mock_get_client:
            mock_client = AsyncMock()
            mock_workflow_handle = MagicMock()
            mock_workflow_handle.signal.return_value = None
            mock_client.start_workflow.return_value = mock_workflow_handle
            mock_client.get_workflow_handle.return_value = mock_workflow_handle
            mock_get_client.return_value = mock_client
            
            # Send signals concurrently
            start_time = time.time()
            tasks = []
            for i in range(num_signals):
                task = send_message_signal(
                    self.user.id,
                    session.id,
                    f"Message {i}"
                )
                tasks.append(task)
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            total_time = time.time() - start_time
            
            successful = sum(1 for r in results if r is True)
            
            print(f"Sent {successful}/{num_signals} signals in {total_time:.3f}s")
            print(f"Throughput: {successful/total_time:.1f} signals/second")
            
            self.assertGreater(successful, num_signals * 0.95, "At least 95% should succeed")


class TestAPILoad(TransactionTestCase):
    """Test API endpoint load handling."""
    
    def setUp(self):
        """Set up test data."""
        self.metrics = MetricsCollector()
        self.client = None  # Will be set in test
        self.user = User.objects.create_user(
            email='api_load@example.com',
            password='testpass123'
        )
    
    def test_concurrent_api_requests(self, num_requests: int = 50):
        """Test handling concurrent API requests."""
        print(f"\nTesting concurrent API requests with {num_requests} requests...")
        
        from django.test import Client
        from app.account.api.auth import signup
        
        # Create sessions first
        sessions = [create_session(self.user.id, f"API Test {i}") for i in range(10)]
        
        def make_request(session_id: int, request_num: int):
            """Make an API request."""
            start_time = time.time()
            try:
                client = Client()
                # Simulate authenticated request (would need actual token in real test)
                response = client.get(f'/api/chats/{session_id}/messages/')
                elapsed = time.time() - start_time
                self.metrics.record('api_request', elapsed)
                return response.status_code
            except Exception as e:
                self.metrics.record_error('api_request', str(e), {
                    'session_id': session_id,
                    'request_num': request_num
                })
                return None
        
        # Execute concurrently
        with ThreadPoolExecutor(max_workers=20) as executor:
            futures = []
            for i in range(num_requests):
                session = sessions[i % len(sessions)]
                futures.append(executor.submit(make_request, session.id, i))
            
            results = [f.result() for f in as_completed(futures)]
        
        successful = sum(1 for r in results if r and r < 500)
        stats = self.metrics.get_stats('api_request')
        
        print(f"Completed {successful}/{num_requests} requests")
        print(f"Mean time: {stats['mean']:.3f}s, P95: {stats['p95']:.3f}s")
        self.metrics.print_report()


class TestStressScenarios(TransactionTestCase):
    """Stress test scenarios."""
    
    def setUp(self):
        """Set up test data."""
        self.metrics = MetricsCollector()
    
    def test_high_concurrency_stress(self):
        """Stress test with high concurrency."""
        print("\n" + "="*80)
        print("HIGH CONCURRENCY STRESS TEST")
        print("="*80)
        
        num_users = 100
        messages_per_user = 10
        
        users = []
        sessions = []
        
        # Create users and sessions
        print(f"Creating {num_users} users and sessions...")
        for i in range(num_users):
            user = User.objects.create_user(
                email=f'stress_{i}@example.com',
                password='testpass123'
            )
            session = create_session(user.id, f"Stress Test {i}")
            users.append(user)
            sessions.append(session)
        
        # Concurrent message creation
        print(f"Creating {num_users * messages_per_user} messages concurrently...")
        def add_messages(session_id: int, user_id: int):
            start_time = time.time()
            try:
                for j in range(messages_per_user):
                    add_message(session_id, 'user', f'Stress message {j}')
                elapsed = time.time() - start_time
                self.metrics.record('stress_message_batch', elapsed)
                return True
            except Exception as e:
                self.metrics.record_error('stress_message_batch', str(e), {
                    'session_id': session_id,
                    'user_id': user_id
                })
                return False
        
        with ThreadPoolExecutor(max_workers=50) as executor:
            futures = [executor.submit(add_messages, s.id, u.id) 
                      for u, s in zip(users, sessions)]
            results = [f.result() for f in as_completed(futures)]
        
        successful = sum(1 for r in results if r)
        print(f"Successfully processed {successful}/{num_users} user batches")
        
        # Verify database state
        total_messages = Message.objects.count()
        expected_messages = successful * messages_per_user
        print(f"Total messages in database: {total_messages} (expected: {expected_messages})")
        
        self.assertGreater(successful, num_users * 0.90, "At least 90% should succeed")
        self.metrics.print_report()
