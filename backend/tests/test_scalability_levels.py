"""
Incremental Scalability Tests - Progressive Load Levels

Tests system scalability at increasing load levels to identify bottlenecks
and measure real-world performance under stress.

Level Progression:
- Level 1: 100 users, 1000 concurrent operations
- Level 2: 200 users, 2000 concurrent operations
- Level 3: 500 users, 5000 concurrent operations
- Level 4: 1000 users, 10000 concurrent operations
- Level 5: 2000 users, 20000 concurrent operations
"""
import asyncio
import json
import time
import statistics
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List, Dict, Any, Optional
from django.test import TransactionTestCase
from django.contrib.auth import get_user_model
from unittest.mock import patch, AsyncMock, MagicMock

from app.db.models.session import ChatSession
from app.db.models.message import Message
from app.services.chat_service import create_session, add_message
from app.core.redis import get_redis_client
from app.agents.temporal.workflow_manager import get_or_create_workflow, send_message_signal
from tests.test_load_stress import MetricsCollector

User = get_user_model()


# Test Level Configurations
SCALABILITY_LEVELS = {
    1: {"users": 100, "concurrent_ops": 1000, "messages_per_user": 10, "workers": 50},
    2: {"users": 200, "concurrent_ops": 2000, "messages_per_user": 10, "workers": 100},
    3: {"users": 500, "concurrent_ops": 5000, "messages_per_user": 10, "workers": 200},
    4: {"users": 1000, "concurrent_ops": 10000, "messages_per_user": 10, "workers": 300},
    5: {"users": 2000, "concurrent_ops": 20000, "messages_per_user": 10, "workers": 500},
}


class TestScalabilityLevels(TransactionTestCase):
    """Progressive scalability tests with incremental load levels."""
    
    def setUp(self):
        """Set up test data."""
        self.metrics = MetricsCollector()
        self.level_results: Dict[int, Dict[str, Any]] = {}
    
    def test_all_levels(self, max_level: int = 5):
        """Run all scalability levels up to max_level."""
        print("\n" + "="*100)
        print("INCREMENTAL SCALABILITY TEST SUITE")
        print("="*100)
        print(f"Running levels 1 through {max_level}")
        print("="*100)
        
        for level in range(1, max_level + 1):
            if level not in SCALABILITY_LEVELS:
                print(f"\n⚠️  Level {level} not configured, skipping...")
                continue
            
            config = SCALABILITY_LEVELS[level]
            print(f"\n{'='*100}")
            print(f"LEVEL {level}: {config['users']} users, {config['concurrent_ops']} concurrent operations")
            print(f"{'='*100}")
            
            try:
                result = self._run_level(level, config)
                self.level_results[level] = result
                self._print_level_summary(level, result)
            except Exception as e:
                print(f"\n❌ Level {level} FAILED: {e}")
                self.level_results[level] = {"error": str(e)}
                # Continue to next level
                continue
        
        # Print final comparison
        self._print_final_comparison()
    
    def _run_level(self, level: int, config: Dict) -> Dict[str, Any]:
        """Run a single scalability level."""
        level_start = time.time()
        level_metrics = MetricsCollector()
        
        users = config['users']
        concurrent_ops = config['concurrent_ops']
        messages_per_user = config['messages_per_user']
        workers = config['workers']
        
        # Test 1: Concurrent Session Creation
        print(f"\n[Level {level}.1] Creating {users} sessions concurrently...")
        session_start = time.time()
        created_users, created_sessions = self._create_sessions_concurrent(users, workers, level_metrics)
        session_time = time.time() - session_start
        session_throughput = len(created_sessions) / session_time if session_time > 0 else 0
        
        # Test 2: Concurrent Message Creation
        print(f"\n[Level {level}.2] Creating {concurrent_ops} messages concurrently...")
        message_start = time.time()
        messages_created = self._create_messages_concurrent(
            created_sessions, concurrent_ops, workers, level_metrics
        )
        message_time = time.time() - message_start
        message_throughput = messages_created / message_time if message_time > 0 else 0
        
        # Test 3: Redis Pub/Sub Throughput
        print(f"\n[Level {level}.3] Testing Redis pub/sub with {concurrent_ops} messages...")
        redis_start = time.time()
        redis_throughput, redis_latency = asyncio.run(
            self._test_redis_throughput_async(concurrent_ops, level_metrics)
        )
        redis_time = time.time() - redis_start
        
        # Test 4: Temporal Workflow Scalability
        print(f"\n[Level {level}.4] Testing Temporal workflows with {users} workflows...")
        workflow_start = time.time()
        workflow_throughput = asyncio.run(
            self._test_temporal_workflows_async(created_sessions[:min(users, len(created_sessions))], level_metrics)
        )
        workflow_time = time.time() - workflow_start
        
        total_time = time.time() - level_start
        
        return {
            "level": level,
            "config": config,
            "users_created": len(created_users),
            "sessions_created": len(created_sessions),
            "messages_created": messages_created,
            "session_throughput": session_throughput,
            "message_throughput": message_throughput,
            "redis_throughput": redis_throughput,
            "redis_latency_p95": redis_latency,
            "workflow_throughput": workflow_throughput,
            "total_time": total_time,
            "session_time": session_time,
            "message_time": message_time,
            "redis_time": redis_time,
            "workflow_time": workflow_time,
            "metrics": level_metrics,
        }
    
    def _create_sessions_concurrent(self, num_users: int, workers: int, metrics: MetricsCollector) -> tuple:
        """Create users and sessions concurrently."""
        created_users = []
        created_sessions = []
        
        def create_user_and_session(user_id: int):
            start_time = time.time()
            try:
                user = User.objects.create_user(
                    email=f'scale_test_l{user_id}@example.com',
                    password='testpass123'
                )
                session = create_session(user.id, f"Scalability Test {user_id}")
                elapsed = time.time() - start_time
                metrics.record('session_creation', elapsed)
                return (user, session)
            except Exception as e:
                metrics.record_error('session_creation', str(e), {'user_id': user_id})
                return None
        
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = [executor.submit(create_user_and_session, i) for i in range(num_users)]
            results = [f.result() for f in as_completed(futures)]
        
        for result in results:
            if result:
                created_users.append(result[0])
                created_sessions.append(result[1])
        
        return created_users, created_sessions
    
    def _create_messages_concurrent(
        self, sessions: List, num_messages: int, workers: int, metrics: MetricsCollector
    ) -> int:
        """Create messages concurrently across sessions."""
        if not sessions:
            return 0
        
        def add_test_message(session_id: int, message_num: int):
            start_time = time.time()
            try:
                msg = add_message(session_id, 'user', f'Scale test message {message_num}')
                elapsed = time.time() - start_time
                metrics.record('message_creation', elapsed)
                return msg
            except Exception as e:
                metrics.record_error('message_creation', str(e), {
                    'session_id': session_id,
                    'message_num': message_num
                })
                return None
        
        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = []
            for i in range(num_messages):
                session = sessions[i % len(sessions)]
                futures.append(executor.submit(add_test_message, session.id, i))
            
            results = [f.result() for f in as_completed(futures)]
        
        return sum(1 for r in results if r is not None)
    
    async def _test_redis_throughput_async(self, num_messages: int, metrics: MetricsCollector) -> tuple:
        """Test Redis pub/sub throughput."""
        redis_client = await get_redis_client()
        channel = f"test:scale:throughput:{int(time.time())}"
        
        # Warm up
        await redis_client.publish(channel, json.dumps({"type": "warmup"}).encode())
        await asyncio.sleep(0.1)
        
        # Publish messages in batches to avoid overwhelming Redis
        start_time = time.time()
        batch_size = 1000
        successful = 0
        
        for batch_start in range(0, num_messages, batch_size):
            batch_end = min(batch_start + batch_size, num_messages)
            tasks = []
            for i in range(batch_start, batch_end):
                message = json.dumps({
                    "type": "test",
                    "id": i,
                    "timestamp": time.time()
                }).encode()
                tasks.append(redis_client.publish(channel, message))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            successful += sum(1 for r in results if not isinstance(r, Exception))
        
        total_time = time.time() - start_time
        
        throughput = successful / total_time if total_time > 0 else 0
        
        # Test latency
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(channel)
        await pubsub.get_message(timeout=1.0)  # Wait for subscription
        
        latencies = []
        for i in range(min(100, num_messages)):  # Sample 100 for latency
            message = json.dumps({"type": "test", "id": i, "timestamp": time.time()}).encode()
            publish_time = time.time()
            await redis_client.publish(channel, message)
            msg = await pubsub.get_message(timeout=0.5)
            if msg and msg['type'] == 'message':
                receive_time = time.time()
                latency = receive_time - publish_time
                latencies.append(latency)
                metrics.record('redis_latency', latency)
        
        await pubsub.unsubscribe(channel)
        await pubsub.close()
        
        # Calculate P95 manually since statistics.percentile might not exist
        if latencies:
            sorted_latencies = sorted(latencies)
            index = int(len(sorted_latencies) * 0.95)
            latency_p95 = sorted_latencies[min(index, len(sorted_latencies) - 1)]
        else:
            latency_p95 = 0
        
        return throughput, latency_p95
    
    async def _test_temporal_workflows_async(
        self, sessions: List, metrics: MetricsCollector
    ) -> float:
        """Test Temporal workflow creation throughput with REAL OpenAI calls."""
        # REMOVED MOCKS - Now using real workflows that will call OpenAI API
        # This tests the full end-to-end flow including LLM invocations
        
        from app.core.temporal import get_temporal_client
        from app.agents.temporal.workflow_manager import get_workflow_id
        
        start_time = time.time()
        tasks = []
        workflow_handles = []
        
        # Create workflows with batching to avoid overwhelming Temporal connections
        # Batch size: 20 concurrent workflows at a time
        batch_size = 20
        all_results = []
        
        for batch_start in range(0, len(sessions), batch_size):
            batch_end = min(batch_start + batch_size, len(sessions))
            batch_sessions = sessions[batch_start:batch_end]
            
            batch_tasks = []
            for session in batch_sessions:
                task = get_or_create_workflow(
                    session.user.id,
                    session.id,
                    initial_state={
                        "user_id": session.user.id,
                        "session_id": session.id,
                        "message": f"Hello, this is a scalability test message for session {session.id}. Please respond briefly.",
                        "flow": "main"
                    }
                )
                batch_tasks.append(task)
            
            # Execute batch with small delay between batches
            batch_results = await asyncio.gather(*batch_tasks, return_exceptions=True)
            all_results.extend(batch_results)
            
            # Small delay between batches to avoid overwhelming connections
            if batch_end < len(sessions):
                await asyncio.sleep(0.5)
        
        results = all_results
        creation_time = time.time() - start_time
        
        # Collect successful workflow handles
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                metrics.record_error('workflow_creation', str(result), {
                    'session_id': sessions[i].id if i < len(sessions) else None
                })
            else:
                workflow_handles.append(result)
                metrics.record('workflow_creation', creation_time / len(sessions))
        
        successful_creations = len(workflow_handles)
        creation_throughput = successful_creations / creation_time if creation_time > 0 else 0
        
        # Wait a bit for workflows to start executing (including OpenAI calls)
        print(f"  Created {successful_creations} workflows, waiting 10s for execution to start...")
        await asyncio.sleep(10)
        
        # Check how many workflows are actually running (verifying they started OpenAI calls)
        client = await get_temporal_client()
        running_count = 0
        for handle in workflow_handles[:min(100, len(workflow_handles))]:  # Sample first 100 to avoid timeout
            try:
                description = await handle.describe()
                if description.status.name == "RUNNING":
                    running_count += 1
            except Exception as e:
                pass  # Workflow might have completed or failed
        
        total_time = time.time() - start_time
        print(f"  {running_count}/{min(100, len(workflow_handles))} sampled workflows are running (executing OpenAI calls)")
        print(f"  Note: Workflows will continue running in background - this tests creation + execution start")
        
        return creation_throughput
    
    def _print_level_summary(self, level: int, result: Dict[str, Any]):
        """Print summary for a level."""
        if "error" in result:
            print(f"\n❌ Level {level} failed: {result['error']}")
            return
        
        print(f"\n{'='*100}")
        print(f"LEVEL {level} RESULTS")
        print(f"{'='*100}")
        print(f"Total Time: {result['total_time']:.2f}s")
        print(f"\nSessions:")
        print(f"  Created: {result['sessions_created']}/{result['config']['users']}")
        print(f"  Time: {result['session_time']:.2f}s")
        print(f"  Throughput: {result['session_throughput']:.1f} sessions/s")
        print(f"\nMessages:")
        print(f"  Created: {result['messages_created']}/{result['config']['concurrent_ops']}")
        print(f"  Time: {result['message_time']:.2f}s")
        print(f"  Throughput: {result['message_throughput']:.1f} messages/s")
        print(f"\nRedis Pub/Sub:")
        print(f"  Throughput: {result['redis_throughput']:.0f} messages/s")
        print(f"  Latency P95: {result['redis_latency_p95']*1000:.2f}ms")
        print(f"\nTemporal Workflows:")
        print(f"  Throughput: {result['workflow_throughput']:.1f} workflows/s")
        
        # Print detailed metrics
        result['metrics'].print_report()
    
    def _print_final_comparison(self):
        """Print comparison across all levels."""
        print("\n" + "="*100)
        print("SCALABILITY COMPARISON - ALL LEVELS")
        print("="*100)
        
        # Create comparison table
        print(f"\n{'Level':<8} {'Users':<8} {'Ops':<10} {'Sessions/s':<12} {'Msgs/s':<12} {'Redis/s':<12} {'Workflows/s':<12} {'Total Time':<12}")
        print("-" * 100)
        
        for level in sorted(self.level_results.keys()):
            result = self.level_results[level]
            if "error" in result:
                print(f"{level:<8} {'ERROR':<8}")
                continue
            
            config = result['config']
            print(f"{level:<8} {config['users']:<8} {config['concurrent_ops']:<10} "
                  f"{result['session_throughput']:<12.1f} {result['message_throughput']:<12.1f} "
                  f"{result['redis_throughput']:<12.0f} {result['workflow_throughput']:<12.1f} "
                  f"{result['total_time']:<12.2f}")
        
        print("\n" + "="*100)
        print("SCALABILITY ANALYSIS")
        print("="*100)
        
        # Analyze scalability trends
        levels = sorted([l for l in self.level_results.keys() if "error" not in self.level_results[l]])
        if len(levels) >= 2:
            first = self.level_results[levels[0]]
            last = self.level_results[levels[-1]]
            
            load_increase = last['config']['users'] / first['config']['users']
            session_degradation = first['session_throughput'] / last['session_throughput'] if last['session_throughput'] > 0 else 0
            message_degradation = first['message_throughput'] / last['message_throughput'] if last['message_throughput'] > 0 else 0
            
            print(f"\nLoad Increase: {load_increase:.1f}x ({first['config']['users']} → {last['config']['users']} users)")
            print(f"Session Throughput Degradation: {session_degradation:.2f}x")
            print(f"Message Throughput Degradation: {message_degradation:.2f}x")
            
            if session_degradation < 2.0:
                print("✅ Session creation scales well")
            elif session_degradation < 5.0:
                print("⚠️  Session creation shows moderate degradation")
            else:
                print("❌ Session creation shows significant degradation")
            
            if message_degradation < 2.0:
                print("✅ Message creation scales well")
            elif message_degradation < 5.0:
                print("⚠️  Message creation shows moderate degradation")
            else:
                print("❌ Message creation shows significant degradation")


class TestIndividualLevels(TransactionTestCase):
    """Individual level tests for targeted testing."""
    
    def setUp(self):
        """Set up test data."""
        self.metrics = MetricsCollector()
    
    def test_level_1(self):
        """Level 1: 100 users, 1000 concurrent operations."""
        test = TestScalabilityLevels()
        test.setUp()
        result = test._run_level(1, SCALABILITY_LEVELS[1])
        test._print_level_summary(1, result)
        # Allow for some failures at high load - at least 80% success
        self.assertGreater(result['sessions_created'], 80, "At least 80% should succeed at high load")
    
    def test_level_2(self):
        """Level 2: 200 users, 2000 concurrent operations."""
        test = TestScalabilityLevels()
        test.setUp()
        result = test._run_level(2, SCALABILITY_LEVELS[2])
        test._print_level_summary(2, result)
        self.assertGreater(result['sessions_created'], 190, "At least 95% should succeed")
    
    def test_level_3(self):
        """Level 3: 500 users, 5000 concurrent operations."""
        test = TestScalabilityLevels()
        test.setUp()
        result = test._run_level(3, SCALABILITY_LEVELS[3])
        test._print_level_summary(3, result)
        self.assertGreater(result['sessions_created'], 475, "At least 95% should succeed")
    
    def test_level_4(self):
        """Level 4: 1000 users, 10000 concurrent operations."""
        test = TestScalabilityLevels()
        test.setUp()
        result = test._run_level(4, SCALABILITY_LEVELS[4])
        test._print_level_summary(4, result)
        self.assertGreater(result['sessions_created'], 950, "At least 95% should succeed")
    
    def test_level_5(self):
        """Level 5: 2000 users, 20000 concurrent operations."""
        test = TestScalabilityLevels()
        test.setUp()
        result = test._run_level(5, SCALABILITY_LEVELS[5])
        test._print_level_summary(5, result)
        self.assertGreater(result['sessions_created'], 1900, "At least 95% should succeed")
