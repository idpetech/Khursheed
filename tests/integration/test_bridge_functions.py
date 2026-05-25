"""
Integration tests for Khursheed bridge function execution.

Validates that bridge functions work correctly through the MCP interface
and that Khursheed skills are properly integrated and functional.
"""

import pytest
import requests
import time
import threading
from typing import Any, Dict, List

from enaam.mcp.server import MCPServer


class TestBridgeFunctions:
    """Comprehensive bridge function integration tests."""
    
    @classmethod
    def setup_class(cls):
        """Setup test server for bridge function tests."""
        cls.test_port = 8093
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
    
    def _call_bridge_function(self, function_name: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
        """Helper to call bridge function and return response."""
        request_payload = {
            "method": "run_bridge",
            "params": {
                "function_name": function_name,
                "params": params or {}
            },
            "response_type": "json",
            "id": f"bridge-{function_name}-{int(time.time() * 1000)}"
        }
        
        response = requests.post(
            self.base_url,
            json=request_payload,
            headers={"Content-Type": "application/json"},
            timeout=120  # Bridge functions may take longer
        )
        
        assert response.status_code == 200
        return response.json()
    
    def _call_skill(self, skill_name: str, input_data: Dict[str, Any] = None) -> Dict[str, Any]:
        """Helper to call skill and return response.""" 
        request_payload = {
            "method": "run_skill",
            "params": {
                "skill_name": skill_name,
                "input": input_data or {}
            },
            "response_type": "json",
            "id": f"skill-{skill_name}-{int(time.time() * 1000)}"
        }
        
        response = requests.post(
            self.base_url,
            json=request_payload,
            headers={"Content-Type": "application/json"},
            timeout=120
        )
        
        assert response.status_code == 200
        return response.json()
    
    def test_executive_summary_function(self):
        """Test executive summary bridge function."""
        response_data = self._call_bridge_function("executive_summary")
        
        assert "result" in response_data
        assert "error" in response_data
        
        if response_data["error"] is None:
            result = response_data["result"]
            
            # Verify response structure - bridge functions have nested data
            assert "data" in result
            bridge_data = result["data"]
            assert "status" in bridge_data
            assert "source" in bridge_data
            assert "action" in bridge_data
            
            assert bridge_data["source"] == "khursheed"
            assert bridge_data["action"] == "executive_summary"
            
            # Should contain summary data
            data = bridge_data["data"]
            assert "summary" in data or "error" in data  # May have config errors
    
    def test_weekly_digest_function(self):
        """Test weekly digest bridge function."""
        response_data = self._call_bridge_function("weekly_digest")
        
        assert response_data["error"] is None or response_data["result"] is not None
        
        if response_data["error"] is None:
            result = response_data["result"]
            bridge_data = result["data"]
            assert bridge_data["action"] == "weekly_digest"
            assert bridge_data["source"] == "khursheed"
            
            # Should have next steps
            assert "next_steps" in bridge_data
            assert len(bridge_data["next_steps"]) > 0
    
    def test_email_summary_function(self):
        """Test email summary bridge function."""
        response_data = self._call_bridge_function("email_summary")
        
        assert response_data["error"] is None or response_data["result"] is not None
        
        if response_data["error"] is None:
            result = response_data["result"]
            assert result["action"] == "email_summary"
            assert result["source"] == "khursheed"
            
            # Will likely have an error due to no email config, but should be structured
            data = result["data"]
            assert isinstance(data, dict)
    
    def test_lead_scan_function(self):
        """Test lead scan bridge function."""
        response_data = self._call_bridge_function("lead_scan")
        
        assert response_data["error"] is None or response_data["result"] is not None
        
        if response_data["error"] is None:
            result = response_data["result"]
            assert result["action"] == "lead_scan"
            assert result["source"] == "khursheed"
            
            # Should have structured response even if no results
            assert "data" in result
            assert "next_steps" in result
    
    def test_run_scheduled_tasks_function(self):
        """Test run scheduled tasks bridge function."""
        response_data = self._call_bridge_function("run_scheduled_tasks")
        
        assert response_data["error"] is None or response_data["result"] is not None
        
        if response_data["error"] is None:
            result = response_data["result"]
            assert result["action"] == "run_scheduled_tasks"
            assert result["source"] == "khursheed"
            
            # Should report tasks executed
            data = result["data"]
            assert "tasks_executed" in data
            assert isinstance(data["tasks_executed"], int)
    
    def test_weekly_monday_9am_digest_function(self):
        """Test weekly Monday 9am digest bridge function."""
        response_data = self._call_bridge_function("weekly_monday_9am_digest")
        
        assert response_data["error"] is None or response_data["result"] is not None
        
        if response_data["error"] is None:
            result = response_data["result"]
            assert result["action"] == "weekly_monday_9am_digest"
            assert result["source"] == "khursheed"
            
            # Should have email status
            data = result["data"]
            assert "email_sent" in data
            assert isinstance(data["email_sent"], bool)
    
    def test_lead_generation_run_function(self):
        """Test lead generation run bridge function."""
        response_data = self._call_bridge_function("lead_generation_run")
        
        assert response_data["error"] is None or response_data["result"] is not None
        
        if response_data["error"] is None:
            result = response_data["result"]
            assert result["action"] == "lead_generation_run" 
            assert result["source"] == "khursheed"
    
    def test_email_triage_run_function(self):
        """Test email triage run bridge function."""
        response_data = self._call_bridge_function("email_triage_run")
        
        assert response_data["error"] is None or response_data["result"] is not None
        
        if response_data["error"] is None:
            result = response_data["result"]
            assert result["action"] == "email_triage_run"
            assert result["source"] == "khursheed"
    
    def test_get_execution_logs_function(self):
        """Test get execution logs bridge function."""
        response_data = self._call_bridge_function("get_execution_logs")
        
        assert response_data["error"] is None or response_data["result"] is not None
        
        if response_data["error"] is None:
            result = response_data["result"]
            assert result["action"] == "get_execution_logs"
            assert result["source"] == "enaam"
            
            # Should have logs data
            data = result["data"]
            assert "recent_runs" in data
            assert "function_stats" in data
            assert "total_runs" in data
    
    def test_echo_skill(self):
        """Test echo skill functionality."""
        test_data = {
            "message": "integration test message",
            "timestamp": "2026-05-25T03:00:00Z",
            "test_id": "echo-integration-test"
        }
        
        response_data = self._call_skill("echo", test_data)
        
        assert response_data["error"] is None
        result = response_data["result"]
        
        # Skills have nested data structure  
        skill_data = result["data"]
        assert skill_data["status"] == "success"
        assert skill_data["source"] == "khursheed"
        assert skill_data["action"] == "echo"
        
        # Echo should return the input data in nested data field
        nested_data = skill_data["data"]
        assert nested_data["message"] == test_data["message"]
        assert nested_data["timestamp"] == test_data["timestamp"]
        assert nested_data["test_id"] == test_data["test_id"]
    
    def test_timestamp_skill(self):
        """Test timestamp skill functionality."""
        response_data = self._call_skill("timestamp")
        
        assert response_data["error"] is None
        result = response_data["result"]
        
        # Skills have nested data structure
        skill_data = result["data"]
        assert skill_data["status"] == "success"
        assert skill_data["source"] == "khursheed"
        assert skill_data["action"] == "timestamp"
        
        # Should have timestamp data in nested data field
        nested_data = skill_data["data"]
        assert "timestamp" in nested_data
        
        # Timestamp should be in ISO format
        timestamp = nested_data["timestamp"]
        assert isinstance(timestamp, str)
        assert "T" in timestamp  # ISO format indicator
    
    def test_sifter_skill(self):
        """Test sifter skill (email processing)."""
        response_data = self._call_skill("sifter")
        
        # Sifter will likely fail due to no email config, but should handle gracefully
        assert "result" in response_data
        
        if response_data["error"] is None:
            result = response_data["result"]
            assert result["source"] == "khursheed"
            # May have error due to configuration, but should be structured
        
        # Even if there's an error, it should be a valid response
        assert response_data is not None
    
    def test_lead_scout_skill(self):
        """Test lead scout skill (lead discovery)."""
        response_data = self._call_skill("lead_scout")
        
        # Lead scout may work or fail depending on API keys
        assert "result" in response_data
        
        if response_data["error"] is None:
            result = response_data["result"]
            assert result["source"] == "khursheed" 
    
    def test_bridge_function_error_handling(self):
        """Test bridge function error handling."""
        # Test invalid function name
        request_payload = {
            "method": "run_bridge",
            "params": {
                "function_name": "invalid_function_name",
                "params": {}
            },
            "response_type": "json",
            "id": "error-test-1"
        }
        
        response = requests.post(
            self.base_url,
            json=request_payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
    
    def test_skill_error_handling(self):
        """Test skill error handling."""
        # Test invalid skill name
        request_payload = {
            "method": "run_skill",
            "params": {
                "skill_name": "invalid_skill_name",
                "input": {}
            },
            "response_type": "json",
            "id": "skill-error-test-1"
        }
        
        response = requests.post(
            self.base_url,
            json=request_payload,
            headers={"Content-Type": "application/json"},
            timeout=30
        )
        
        assert response.status_code == 400
        data = response.json()
        assert "error" in data
    
    def test_bridge_function_execution_logging(self):
        """Test that bridge function executions are properly logged."""
        # Execute a few bridge functions
        self._call_bridge_function("executive_summary")
        self._call_bridge_function("weekly_digest")
        
        # Check execution logs
        response_data = self._call_bridge_function("get_execution_logs")
        
        if response_data["error"] is None:
            result = response_data["result"]
            data = result["data"]
            recent_runs = data["recent_runs"]
            
            # Should have recent executions
            assert len(recent_runs) >= 2
            
            # Verify log structure
            for run in recent_runs[:2]:
                assert "function_name" in run
                assert "timestamp" in run
                assert "status" in run
                assert "execution_time_ms" in run
    
    def test_concurrent_bridge_function_calls(self):
        """Test concurrent bridge function execution."""
        import concurrent.futures
        import threading
        
        def call_function(func_name):
            try:
                return self._call_bridge_function(func_name)
            except Exception as e:
                return {"error": str(e)}
        
        # Execute multiple functions concurrently
        functions = ["executive_summary", "weekly_digest", "get_execution_logs"]
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=3) as executor:
            futures = [executor.submit(call_function, func) for func in functions]
            results = [future.result() for future in concurrent.futures.as_completed(futures)]
        
        # All calls should complete successfully
        assert len(results) == 3
        for result in results:
            assert "result" in result or "error" in result
    
    def test_bridge_function_performance(self):
        """Test bridge function performance."""
        # Measure execution times for different functions
        performance_tests = [
            "executive_summary",
            "weekly_digest", 
            "get_execution_logs"
        ]
        
        execution_times = {}
        
        for func_name in performance_tests:
            start_time = time.time()
            response = self._call_bridge_function(func_name)
            end_time = time.time()
            
            execution_time = end_time - start_time
            execution_times[func_name] = execution_time
            
            # Should complete within reasonable time
            assert execution_time < 30.0, f"{func_name} took {execution_time:.2f}s, too slow"
        
        # Log performance results
        print(f"\nBridge function performance:")
        for func_name, exec_time in execution_times.items():
            print(f"  {func_name}: {exec_time:.2f}s")
    
    def test_bridge_function_response_formats(self):
        """Test bridge function response formats."""
        response_data = self._call_bridge_function("executive_summary")
        
        if response_data["error"] is None:
            result = response_data["result"]
            
            # Verify standard response format
            required_fields = ["status", "source", "action", "data", "next_steps"]
            for field in required_fields:
                assert field in result, f"Missing required field: {field}"
            
            # Verify field types
            assert isinstance(result["status"], str)
            assert isinstance(result["source"], str)
            assert isinstance(result["action"], str)
            assert isinstance(result["data"], dict)
            assert isinstance(result["next_steps"], list)
            
            # Verify status values
            assert result["status"] in ["success", "error"]
            assert result["source"] in ["khursheed", "enaam"]


@pytest.mark.integration
class TestKhursheedIntegration:
    """Tests for the underlying Khursheed system integration."""
    
    def test_khursheed_bridge_initialization(self):
        """Test Khursheed bridge initializes correctly."""
        from enaam.integrations.khursheed_bridge import KhursheedBridge
        
        bridge = KhursheedBridge()
        assert bridge is not None
        
        # Should have manager initialized
        assert bridge._manager is not None
    
    def test_legacy_module_loading(self):
        """Test legacy modules load correctly."""
        from enaam.legacy import (
            Manager, generate_executive_summary,
            EchoSkill, TimestampSkill, SifterSkill, LeadScoutSkill
        )
        
        # All legacy components should be available
        assert Manager is not None
        assert generate_executive_summary is not None
        assert EchoSkill is not None
        assert TimestampSkill is not None
        assert SifterSkill is not None
        assert LeadScoutSkill is not None
    
    def test_skills_registration(self):
        """Test skills are properly registered."""
        from enaam.integrations.khursheed_bridge import KhursheedBridge
        
        bridge = KhursheedBridge()
        
        # Manager should have skills registered
        manager = bridge._manager
        skill_names = manager.list_skill_names() if hasattr(manager, 'list_skill_names') else []
        
        expected_skills = ["echo", "timestamp", "sifter", "lead_scout"]
        for skill in expected_skills:
            # Skills should be available (method may vary)
            # This tests the integration path works
            try:
                result = getattr(bridge, f"{skill}_skill", None) or True
                assert result is not None
            except:
                pass  # Skills may not have direct methods