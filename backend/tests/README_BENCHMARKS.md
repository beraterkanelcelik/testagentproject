# Load, Stress, and Benchmark Tests

This document describes the load, stress, and benchmark tests for the Agent Playground application.

## Overview

The benchmark suite tests:
- **Temporal Workflows**: Concurrent execution, throughput, signal handling
- **Redis Pub/Sub**: Message throughput, latency, channel isolation
- **API Endpoints**: Concurrent requests, rate limiting
- **Database Operations**: Concurrent writes, session management
- **Stress Scenarios**: High concurrency, sustained load

## Test Files

### `test_load_stress.py`

Main test file containing:

1. **MetricsCollector**: Collects and analyzes performance metrics
   - Records timing data
   - Calculates statistics (mean, median, P95, P99)
   - Tracks errors
   - Generates formatted reports

2. **TestConcurrentUsers**: Tests concurrent user operations
   - `test_concurrent_session_creation`: Creates multiple sessions concurrently
   - `test_concurrent_messages`: Adds messages concurrently across sessions

3. **TestRedisPubSubPerformance**: Tests Redis pub/sub performance
   - `test_redis_publish_throughput`: Measures publish throughput (target: >1000 msg/s)
   - `test_redis_subscription_latency`: Measures subscription latency (target: P95 < 100ms)
   - `test_concurrent_channels`: Tests multiple concurrent channels

4. **TestTemporalWorkflowScalability**: Tests Temporal workflow performance
   - `test_concurrent_workflow_creation`: Creates workflows concurrently
   - `test_workflow_signal_throughput`: Tests signal sending throughput

5. **TestAPILoad**: Tests API endpoint load handling
   - `test_concurrent_api_requests`: Tests concurrent API requests

6. **TestStressScenarios**: Stress test scenarios
   - `test_high_concurrency_stress`: High concurrency stress test (100 users, 10 messages each)

### `benchmark_runner.py`

Standalone script to run benchmarks outside of Django test framework.

## Running Tests

### Run All Load/Stress Tests

```bash
docker-compose exec backend python manage.py test tests.test_load_stress
```

### Run Specific Test Class

```bash
docker-compose exec backend python manage.py test tests.test_load_stress.TestRedisPubSubPerformance
```

### Run Benchmark Script

```bash
docker-compose exec backend python tests/benchmark_runner.py
```

Or via Django shell:

```bash
docker-compose exec backend python manage.py shell < tests/benchmark_runner.py
```

## Benchmark Targets

### Redis Pub/Sub
- **Publish Throughput**: > 1,000 messages/second
- **Subscription Latency**: P95 < 100ms
- **Concurrent Channels**: Support 50+ concurrent channels

### Temporal Workflows
- **Workflow Creation**: > 10 workflows/second
- **Signal Throughput**: > 50 signals/second

### Database Operations
- **Session Creation**: P95 < 500ms for 50 concurrent sessions
- **Message Creation**: P95 < 100ms for 100 concurrent messages

### API Endpoints
- **Concurrent Requests**: Handle 50+ concurrent requests
- **Response Time**: P95 < 1s for message retrieval

## Metrics Collected

Each test collects:
- **Count**: Number of operations
- **Min/Max**: Minimum and maximum times
- **Mean/Median**: Average and median times
- **P50/P95/P99**: Percentile times
- **StdDev**: Standard deviation
- **Throughput**: Operations per second
- **Error Rate**: Percentage of failed operations

## Example Output

```
================================================================================
PERFORMANCE BENCHMARK REPORT
================================================================================

session_creation:
  Count: 50
  Min: 0.012s
  Max: 0.089s
  Mean: 0.034s
  Median: 0.031s
  P95: 0.067s
  P99: 0.082s
  StdDev: 0.015s

redis_publish_throughput:
  Count: 1000
  Min: 0.001s
  Max: 0.005s
  Mean: 0.002s
  Median: 0.002s
  P95: 0.004s
  P99: 0.005s
  StdDev: 0.001s
```

## Stress Test Scenarios

### High Concurrency Stress Test

- **Users**: 100 concurrent users
- **Messages per User**: 10 messages
- **Total Messages**: 1,000 messages
- **Expected Success Rate**: > 90%

This test simulates:
- Multiple users creating sessions simultaneously
- Concurrent message creation across sessions
- Database write contention
- Redis pub/sub channel isolation

## Performance Tuning

Based on benchmark results, consider:

1. **Database Connection Pooling**: Increase pool size if session creation is slow
2. **Redis Connection Pooling**: Adjust pool size for pub/sub throughput
3. **Temporal Worker Scaling**: Scale workers based on workflow throughput
4. **API Rate Limiting**: Adjust limits based on concurrent request handling
5. **Database Indexing**: Ensure proper indexes for session/message queries

## Continuous Benchmarking

For CI/CD integration:

```bash
# Run benchmarks and save results
docker-compose exec backend python manage.py test tests.test_load_stress --verbosity=2 > benchmark_results.txt

# Extract key metrics
grep -E "(Mean|P95|Throughput)" benchmark_results.txt
```

## Notes

- Tests use `TransactionTestCase` to ensure database isolation
- Async tests are wrapped in sync methods for Django compatibility
- Mock objects are used for Temporal client to avoid external dependencies
- Real Redis connections are used for pub/sub tests (requires Redis running)
- Metrics are printed to console and can be redirected to files
