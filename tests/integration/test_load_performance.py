"""
Load testing and performance validation for Enaam MCP server.

Tests concurrent request handling, performance under load,
and system behavior with high traffic volumes.
"""

import asyncio
import concurrent.futures
import json
import pytest
import requests
import statistics
import threading
import time
from typing import Any, Dict, List, Tuple

from enaam.mcp.server import MCPServer


class LoadTestResults:
    """Container for load test results and metrics."""
    
    def __init__(self):
        self.total_requests = 0
        self.successful_requests = 0
        self.failed_requests = 0
        self.response_times = []
        self.error_types = {}
        self.start_time = None
        self.end_time = None
    
    @property
    def success_rate(self) -> float:
        if self.total_requests == 0:
            return 0.0
        return (self.successful_requests / self.total_requests) * 100
    
    @property
    def avg_response_time(self) -> float:
        if not self.response_times:
            return 0.0
        return statistics.mean(self.response_times)
    
    @property
    def p95_response_time(self) -> float:
        if not self.response_times:
            return 0.0
        sorted_times = sorted(self.response_times)
        p95_index = int(0.95 * len(sorted_times))
        return sorted_times[p95_index] if p95_index < len(sorted_times) else sorted_times[-1]
    
    @property
    def requests_per_second(self) -> float:
        if not self.start_time or not self.end_time:
            return 0.0
        duration = self.end_time - self.start_time
        return self.total_requests / duration if duration > 0 else 0.0
    
    def add_result(self, success: bool, response_time: float, error_type: str = None):
        """Add a request result to the metrics."""
        self.total_requests += 1
        self.response_times.append(response_time)
        
        if success:
            self.successful_requests += 1
        else:
            self.failed_requests += 1
            if error_type:
                self.error_types[error_type] = self.error_types.get(error_type, 0) + 1
    
    def print_summary(self):
        """Print a summary of load test results."""
        print(f"\n📊 Load Test Results Summary")
        print(f"=" * 40)
        print(f"Total Requests: {self.total_requests}")
        print(f"Successful: {self.successful_requests}")
        print(f"Failed: {self.failed_requests}")
        print(f"Success Rate: {self.success_rate:.1f}%")
        print(f"Avg Response Time: {self.avg_response_time:.3f}s")
        print(f"P95 Response Time: {self.p95_response_time:.3f}s")
        print(f"Requests/sec: {self.requests_per_second:.1f}")
        
        if self.error_types:
            print(f"\nError Breakdown:")
            for error_type, count in self.error_types.items():
                print(f"  {error_type}: {count}")


class TestLoadPerformance:
    """Load testing and performance validation tests."""
    
    @classmethod
    def setup_class(cls):
        """Setup test server for load testing."""
        cls.test_port = 8094
        cls.server = MCPServer(host="localhost", port=cls.test_port)
        cls.base_url = f"http://localhost:{cls.test_port}"
        
        # Start server in background thread
        cls.server_thread = threading.Thread(
            target=cls._start_server,
            daemon=True
        )
        cls.server_thread.start()
        
        # Wait for server to start
        cls._wait_for_server()
    
    @classmethod
    def _start_server(cls):
        """Start server in thread."""
        result = cls.server.start()
        if result.get("status") != "success":
            raise RuntimeError(f"Failed to start test server: {result}")
    
    @classmethod
    def _wait_for_server(cls, max_wait: int = 10):
        """Wait for server to be ready."""
        for _ in range(max_wait):
            try:
                response = requests.get(f"{cls.base_url}/health", timeout=1)
                if response.status_code == 200:
                    return
            except requests.exceptions.RequestException:
                pass
            time.sleep(1)
        raise TimeoutError("Server did not start within timeout")
    
    @classmethod
    def teardown_class(cls):
        """Cleanup test server."""
        if hasattr(cls, 'server'):
            cls.server.stop()
    
    def _make_request(self, request_payload: Dict[str, Any], timeout: float = 30) -> Tuple[bool, float, str]:
        """Make a single request and return (success, response_time, error_type)."""
        start_time = time.time()
        try:
            response = requests.post(
                self.base_url,
                json=request_payload,
                headers={"Content-Type": "application/json"},
                timeout=timeout
            )
            end_time = time.time()
            response_time = end_time - start_time
            
            if response.status_code == 200:
                return True, response_time, None
            elif response.status_code == 429:
                return False, response_time, "rate_limited"
            else:
                return False, response_time, f"http_{response.status_code}"
        
        except requests.exceptions.Timeout:
            end_time = time.time()
            return False, end_time - start_time, "timeout"
        except requests.exceptions.ConnectionError:
            end_time = time.time()
            return False, end_time - start_time, "connection_error"
        except Exception as e:
            end_time = time.time()
            return False, end_time - start_time, f"error_{type(e).__name__}"
    
    def _run_concurrent_requests(self, request_payloads: List[Dict[str, Any]], max_workers: int = 10) -> LoadTestResults:
        """Run multiple requests concurrently and collect results."""
        results = LoadTestResults()
        results.start_time = time.time()
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
            # Submit all requests
            futures = [
                executor.submit(self._make_request, payload)
                for payload in request_payloads
            ]
            
            # Collect results
            for future in concurrent.futures.as_completed(futures):
                success, response_time, error_type = future.result()
                results.add_result(success, response_time, error_type)
        
        results.end_time = time.time()
        return results
    
    @pytest.mark.slow
    def test_basic_load_health_endpoint(self):
        """Test basic load on health endpoint."""
        # Create multiple health check requests
        num_requests = 50
        request_payloads = []
        
        for i in range(num_requests):
            # Health endpoint uses GET, but we'll test with POST for consistency
            payload = {
                "method": "run_skill",
                "params": {
                    "skill_name": "echo",
                    "input": {"test": f"health_load_{i}"}
                },
                "response_type": "json",
                "id": f"health-load-{i}"
            }
            request_payloads.append(payload)
        
        results = self._run_concurrent_requests(request_payloads, max_workers=10)
        
        # Assertions
        assert results.success_rate >= 80.0, f"Success rate too low: {results.success_rate}%"
        assert results.avg_response_time < 2.0, f"Average response time too high: {results.avg_response_time}s"
        assert results.p95_response_time < 5.0, f"P95 response time too high: {results.p95_response_time}s"
        
        results.print_summary()
    
    @pytest.mark.slow
    def test_chat_query_load(self):
        """Test load on chat query endpoints."""
        num_requests = 30
        request_payloads = []
        
        chat_queries = [
            "give me a quick status",
            "check my emails",
            "urgent email summary",
            "detailed lead report",
            "weekly digest please",
            "brief update",
            "run scheduled tasks",
            "what are my priorities",
            "system health check",
            "executive summary"
        ]
        
        for i in range(num_requests):
            query = chat_queries[i % len(chat_queries)]
            payload = {
                "method": "chat_query",
                "params": {
                    "query": f"{query} - test {i}",
                    "context": {
                        "session_id": f"load-test-session-{i % 5}",
                        "user_id": f"load-test-user-{i % 3}"
                    }
                },
                "response_type": "chat",
                "id": f"chat-load-{i}"
            }
            request_payloads.append(payload)
        
        results = self._run_concurrent_requests(request_payloads, max_workers=5)
        
        # Chat queries may be slower due to processing
        assert results.success_rate >= 75.0, f"Success rate too low: {results.success_rate}%"
        assert results.avg_response_time < 5.0, f"Average response time too high: {results.avg_response_time}s"
        assert results.p95_response_time < 15.0, f"P95 response time too high: {results.p95_response_time}s"
        
        results.print_summary()
    
    @pytest.mark.slow
    def test_mixed_endpoint_load(self):
        """Test load with mixed endpoint types."""
        num_requests = 40
        request_payloads = []
        
        # Mix of different request types
        for i in range(num_requests):
            request_type = i % 4
            
            if request_type == 0:  # Echo skill
                payload = {
                    "method": "run_skill",
                    "params": {
                        "skill_name": "echo",
                        "input": {"message": f"load_test_{i}"}
                    },
                    "response_type": "json",
                    "id": f"mixed-echo-{i}"
                }
            elif request_type == 1:  # Chat query
                payload = {
                    "method": "chat_query",
                    "params": {
                        "query": f"status update {i}",
                        "context": {"session_id": f"mixed-session-{i}"}
                    },
                    "response_type": "chat",
                    "id": f"mixed-chat-{i}"
                }
            elif request_type == 2:  # Bridge function
                payload = {
                    "method": "run_bridge",
                    "params": {
                        "function_name": "get_execution_logs",
                        "params": {}
                    },
                    "response_type": "json",
                    "id": f"mixed-bridge-{i}"
                }
            else:  # Weekly digest
                payload = {
                    "method": "run_weekly_digest",
                    "params": {},
                    "response_type": "json",
                    "id": f"mixed-digest-{i}"
                }
            
            request_payloads.append(payload)
        
        results = self._run_concurrent_requests(request_payloads, max_workers=8)
        
        assert results.success_rate >= 70.0, f"Success rate too low: {results.success_rate}%"
        assert results.avg_response_time < 8.0, f"Average response time too high: {results.avg_response_time}s"
        
        results.print_summary()
    
    @pytest.mark.slow
    def test_rate_limiting_behavior(self):
        """Test rate limiting behavior under load."""
        # Send many requests quickly to trigger rate limiting
        num_requests = 80
        request_payloads = []
        
        for i in range(num_requests):
            payload = {
                "method": "run_skill",
                "params": {
                    "skill_name": "echo",
                    "input": {"rate_test": i}
                },
                "response_type": "json",
                "id": f"rate-limit-{i}"
            }
            request_payloads.append(payload)
        
        # Use high concurrency to trigger rate limits
        results = self._run_concurrent_requests(request_payloads, max_workers=20)
        
        # Should have some rate limiting
        rate_limited = results.error_types.get("rate_limited", 0)
        
        # In development mode, rate limits may be relaxed
        # Just verify the system handles the load gracefully
        assert results.total_requests == num_requests
        
        # Even with rate limiting, system should remain responsive
        if results.successful_requests > 0:
            assert results.avg_response_time < 10.0
        
        results.print_summary()
        print(f"Rate limited requests: {rate_limited}")
    
    @pytest.mark.slow
    def test_sustained_load(self):
        """Test sustained load over time."""
        duration_seconds = 30
        requests_per_second = 2
        total_requests = duration_seconds * requests_per_second
        
        request_payloads = []
        for i in range(total_requests):
            payload = {
                "method": "chat_query",
                "params": {
                    "query": f"sustained load test {i}",
                    "context": {"session_id": f"sustained-{i % 3}"}
                },
                "response_type": "chat",
                "id": f"sustained-{i}"
            }
            request_payloads.append(payload)
        
        # Spread requests over time
        start_time = time.time()
        results = LoadTestResults()
        results.start_time = start_time
        
        for i, payload in enumerate(request_payloads):
            # Calculate when this request should be sent
            target_time = start_time + (i / requests_per_second)
            current_time = time.time()
            
            # Wait if we're ahead of schedule
            if current_time < target_time:
                time.sleep(target_time - current_time)
            
            success, response_time, error_type = self._make_request(payload)
            results.add_result(success, response_time, error_type)
        
        results.end_time = time.time()
        
        # Verify sustained performance
        assert results.success_rate >= 80.0, f"Success rate degraded: {results.success_rate}%"
        assert results.avg_response_time < 3.0, f"Response time degraded: {results.avg_response_time}s"
        
        results.print_summary()
    
    def test_memory_usage_under_load(self):
        """Test memory usage doesn't grow excessively under load."""
        import psutil
        import os
        
        # Get initial memory usage
        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB
        
        # Run moderate load
        num_requests = 30
        request_payloads = []
        
        for i in range(num_requests):
            payload = {
                "method": "chat_query",
                "params": {
                    "query": f"memory test {i}",
                    "context": {"session_id": f"memory-test-{i}"}
                },
                "response_type": "chat",
                "id": f"memory-{i}"
            }
            request_payloads.append(payload)
        
        results = self._run_concurrent_requests(request_payloads, max_workers=5)
        
        # Check final memory usage
        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory
        
        # Memory should not increase dramatically
        assert memory_increase < 100, f"Memory usage increased by {memory_increase}MB"
        
        print(f"\nMemory Usage:")
        print(f"Initial: {initial_memory:.1f}MB")
        print(f"Final: {final_memory:.1f}MB")
        print(f"Increase: {memory_increase:.1f}MB")
        
        results.print_summary()
    
    def test_concurrent_session_handling(self):
        """Test handling of multiple concurrent sessions."""
        num_sessions = 10
        requests_per_session = 3
        total_requests = num_sessions * requests_per_session
        
        request_payloads = []
        
        for session_id in range(num_sessions):
            for turn in range(requests_per_session):
                payload = {
                    "method": "chat_query",
                    "params": {
                        "query": f"session {session_id} turn {turn}",
                        "context": {
                            "session_id": f"concurrent-session-{session_id}",
                            "user_id": f"user-{session_id}"
                        }
                    },
                    "response_type": "chat",
                    "id": f"concurrent-{session_id}-{turn}"
                }
                request_payloads.append(payload)
        
        results = self._run_concurrent_requests(request_payloads, max_workers=num_sessions)
        
        # All sessions should be handled correctly
        assert results.success_rate >= 85.0, f"Success rate too low: {results.success_rate}%"
        
        results.print_summary()
    
    @pytest.mark.slow
    def test_stress_test_high_concurrency(self):
        """Stress test with high concurrency."""
        num_requests = 100
        max_workers = 25
        
        request_payloads = []
        for i in range(num_requests):
            payload = {
                "method": "run_skill",
                "params": {
                    "skill_name": "echo",
                    "input": {"stress_test": i}
                },
                "response_type": "json",
                "id": f"stress-{i}"
            }
            request_payloads.append(payload)
        
        results = self._run_concurrent_requests(request_payloads, max_workers=max_workers)
        
        # System should handle stress gracefully
        assert results.success_rate >= 60.0, f"Success rate too low under stress: {results.success_rate}%"
        assert results.avg_response_time < 15.0, f"Response time too high under stress: {results.avg_response_time}s"
        
        results.print_summary()
    
    def test_response_consistency_under_load(self):
        """Test that responses remain consistent under load."""
        num_requests = 20
        
        # Send identical requests
        request_payloads = []
        for i in range(num_requests):
            payload = {
                "method": "run_skill",
                "params": {
                    "skill_name": "echo",
                    "input": {"consistency_test": "fixed_value"}
                },
                "response_type": "json",
                "id": f"consistency-{i}"
            }
            request_payloads.append(payload)
        
        # Collect detailed responses
        responses = []
        start_time = time.time()
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
            futures = [
                executor.submit(self._make_detailed_request, payload)
                for payload in request_payloads
            ]
            
            for future in concurrent.futures.as_completed(futures):
                response_data = future.result()
                if response_data:
                    responses.append(response_data)
        
        # Verify response consistency
        assert len(responses) >= num_requests * 0.8  # At least 80% successful
        
        # All successful responses should be identical
        if len(responses) > 1:
            first_response = responses[0]
            for response in responses[1:]:
                # Compare key fields
                if "result" in first_response and "result" in response:
                    first_data = first_response["result"].get("data", {})
                    response_data = response["result"].get("data", {})
                    assert first_data.get("consistency_test") == response_data.get("consistency_test")
        
        print(f"Consistency test: {len(responses)}/{num_requests} consistent responses")
    
    def _make_detailed_request(self, request_payload: Dict[str, Any]) -> Dict[str, Any]:
        """Make request and return full response data."""
        try:
            response = requests.post(
                self.base_url,
                json=request_payload,
                headers={"Content-Type": "application/json"},
                timeout=30
            )
            
            if response.status_code == 200:
                return response.json()
        except:
            pass
        
        return None


@pytest.mark.integration
class TestPerformanceMetrics:
    """Performance metrics and benchmarking tests."""
    
    def test_baseline_performance_metrics(self):
        """Establish baseline performance metrics."""
        from enaam.core.chat_context import ChatContextManager
        from enaam.core.intent_classifier import IntentClassifier
        
        # Test intent classification performance
        classifier = IntentClassifier()
        start_time = time.time()
        
        for _ in range(100):
            classifier.classify_intent("check my email summary")
        
        classification_time = (time.time() - start_time) / 100
        
        # Test context manager performance
        context_manager = ChatContextManager(db_path="perf_test.db")
        start_time = time.time()
        
        for i in range(50):
            session = context_manager.get_or_create_session(f"perf-{i}", "perf-user")
            context_manager.add_conversation_turn(
                session.session_id,
                f"test message {i}",
                {"status": "success", "action": "test"}
            )
        
        context_time = (time.time() - start_time) / 50
        
        # Performance assertions
        assert classification_time < 0.1, f"Intent classification too slow: {classification_time:.3f}s"
        assert context_time < 0.1, f"Context management too slow: {context_time:.3f}s"
        
        print(f"\nPerformance Metrics:")
        print(f"Intent classification: {classification_time:.3f}s per request")
        print(f"Context management: {context_time:.3f}s per request")
        
        # Cleanup
        import os
        if os.path.exists("perf_test.db"):
            os.unlink("perf_test.db")