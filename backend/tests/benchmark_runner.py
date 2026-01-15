"""
Benchmark runner script for load and stress tests.

Usage:
    python manage.py shell < benchmark_runner.py
    OR
    docker-compose exec backend python -c "exec(open('tests/benchmark_runner.py').read())"
"""
import asyncio
import os
import django

# Setup Django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'app.settings')
django.setup()

from tests.test_load_stress import (
    MetricsCollector,
    TestRedisPubSubPerformance,
    TestTemporalWorkflowScalability
)


async def run_redis_benchmarks():
    """Run Redis pub/sub benchmarks."""
    print("\n" + "="*80)
    print("REDIS PUB/SUB BENCHMARKS")
    print("="*80)
    
    test = TestRedisPubSubPerformance()
    test.setUp()
    
    # Test 1: Publish throughput
    print("\n[1/3] Testing publish throughput...")
    await test.test_redis_publish_throughput(num_messages=1000)
    
    # Test 2: Subscription latency
    print("\n[2/3] Testing subscription latency...")
    await test.test_redis_subscription_latency(num_messages=100)
    
    # Test 3: Concurrent channels
    print("\n[3/3] Testing concurrent channels...")
    await test.test_concurrent_channels(num_channels=50)
    
    test.metrics.print_report()


async def run_temporal_benchmarks():
    """Run Temporal workflow benchmarks."""
    print("\n" + "="*80)
    print("TEMPORAL WORKFLOW BENCHMARKS")
    print("="*80)
    
    test = TestTemporalWorkflowScalability()
    test.setUp()
    
    # Test 1: Concurrent workflow creation
    print("\n[1/2] Testing concurrent workflow creation...")
    await test.test_concurrent_workflow_creation(num_workflows=20)
    
    # Test 2: Signal throughput
    print("\n[2/2] Testing signal throughput...")
    await test.test_workflow_signal_throughput(num_signals=100)
    
    test.metrics.print_report()


def run_all_benchmarks():
    """Run all benchmarks."""
    print("\n" + "="*80)
    print("AGENT PLAYGROUND BENCHMARK SUITE")
    print("="*80)
    
    # Run async benchmarks
    asyncio.run(run_redis_benchmarks())
    asyncio.run(run_temporal_benchmarks())
    
    print("\n" + "="*80)
    print("BENCHMARKS COMPLETE")
    print("="*80)


if __name__ == "__main__":
    run_all_benchmarks()
