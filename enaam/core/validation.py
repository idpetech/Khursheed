"""
Input Validation Module - Comprehensive security validation for external interfaces

Provides request size limits, parameter validation, rate limiting, and input sanitization
for all API endpoints and external interfaces.
"""

import json
import re
import time
from collections import defaultdict, deque
from threading import RLock
from typing import Any, Dict, List, Optional, Set, Union

from .constants import APIConstants, ValidationMessages, RegexPatterns
from .exceptions import ValidationError


class RateLimiter:
    """Thread-safe rate limiter for API endpoints"""
    
    def __init__(self, 
                 max_requests: int = APIConstants.MAX_REQUESTS_PER_MINUTE,
                 window_seconds: int = APIConstants.RATE_LIMIT_WINDOW,
                 burst_limit: int = APIConstants.RATE_LIMIT_BURST):
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self.burst_limit = burst_limit
        self._requests = defaultdict(deque)
        self._lock = RLock()
    
    def is_allowed(self, client_ip: str) -> bool:
        """Check if request from client IP is allowed"""
        current_time = time.time()
        
        with self._lock:
            requests = self._requests[client_ip]
            
            # Remove requests outside the window
            while requests and requests[0] <= current_time - self.window_seconds:
                requests.popleft()
            
            # Check rate limit
            if len(requests) >= self.max_requests:
                return False
            
            # Check burst limit (requests in last 10 seconds)
            recent_requests = sum(1 for req_time in requests 
                                if req_time > current_time - 10)
            if recent_requests >= self.burst_limit:
                return False
            
            # Record this request
            requests.append(current_time)
            return True
    
    def get_remaining(self, client_ip: str) -> int:
        """Get remaining requests for client IP"""
        current_time = time.time()
        
        with self._lock:
            requests = self._requests[client_ip]
            
            # Remove requests outside the window
            while requests and requests[0] <= current_time - self.window_seconds:
                requests.popleft()
            
            return max(0, self.max_requests - len(requests))
    
    def reset(self, client_ip: str = None) -> None:
        """Reset rate limits for specific IP or all IPs"""
        with self._lock:
            if client_ip:
                self._requests.pop(client_ip, None)
            else:
                self._requests.clear()


class InputValidator:
    """Comprehensive input validator for API requests"""
    
    def __init__(self):
        self.max_request_size = APIConstants.MAX_REQUEST_SIZE
        self.max_json_depth = APIConstants.MAX_JSON_DEPTH
        self.max_string_length = APIConstants.MAX_STRING_LENGTH
        self.max_array_length = APIConstants.MAX_ARRAY_LENGTH
        self.max_params_count = APIConstants.MAX_PARAMS_COUNT
        
        # Compiled regex patterns for performance
        self._alphanumeric_pattern = re.compile(RegexPatterns.ALPHANUMERIC_PATTERN)
        self._method_pattern = re.compile(RegexPatterns.METHOD_NAME_PATTERN)
        self._skill_pattern = re.compile(RegexPatterns.SKILL_NAME_PATTERN)
        self._function_pattern = re.compile(RegexPatterns.FUNCTION_NAME_PATTERN)
        
        # Sensitive field patterns for sanitization
        self._sensitive_patterns = [
            (re.compile(RegexPatterns.PASSWORD_PATTERN, re.IGNORECASE), 
             RegexPatterns.PASSWORD_REPLACEMENT),
            (re.compile(RegexPatterns.TOKEN_PATTERN, re.IGNORECASE), 
             RegexPatterns.TOKEN_REPLACEMENT),
            (re.compile(RegexPatterns.KEY_PATTERN, re.IGNORECASE), 
             RegexPatterns.KEY_REPLACEMENT),
            (re.compile(RegexPatterns.SECRET_PATTERN, re.IGNORECASE), 
             RegexPatterns.SECRET_REPLACEMENT),
            (re.compile(RegexPatterns.AUTH_PATTERN, re.IGNORECASE), 
             RegexPatterns.AUTH_REPLACEMENT)
        ]
    
    def validate_request_size(self, content_length: int) -> None:
        """Validate request content length"""
        if content_length > self.max_request_size:
            raise ValidationError(ValidationMessages.REQUEST_TOO_LARGE)
    
    def validate_json_structure(self, data: Any, depth: int = 0) -> None:
        """Validate JSON structure depth and complexity"""
        if depth > self.max_json_depth:
            raise ValidationError(ValidationMessages.object_too_deep())
        
        if isinstance(data, dict):
            if len(data) > self.max_params_count:
                raise ValidationError(
                    f"Object exceeds maximum parameter count of {self.max_params_count}"
                )
            for value in data.values():
                self.validate_json_structure(value, depth + 1)
                
        elif isinstance(data, list):
            if len(data) > self.max_array_length:
                raise ValidationError(
                    ValidationMessages.array_too_long("array", self.max_array_length)
                )
            for item in data:
                self.validate_json_structure(item, depth + 1)
                
        elif isinstance(data, str):
            if len(data) > self.max_string_length:
                raise ValidationError(
                    ValidationMessages.field_too_long("string", self.max_string_length)
                )
    
    def validate_method_name(self, method: str, allowed_methods: Set[str]) -> None:
        """Validate MCP method name"""
        if not method:
            raise ValidationError("Method name is required")
        
        if not isinstance(method, str):
            raise ValidationError("Method name must be a string")
        
        if len(method) > 50:
            raise ValidationError("Method name too long")
        
        if not self._method_pattern.match(method):
            raise ValidationError("Method name contains invalid characters")
        
        if method not in allowed_methods:
            raise ValidationError(ValidationMessages.unsupported_method(method))
    
    def validate_skill_name(self, skill_name: str, allowed_skills: Set[str]) -> None:
        """Validate skill name"""
        if not skill_name:
            raise ValidationError("Skill name is required")
        
        if not isinstance(skill_name, str):
            raise ValidationError("Skill name must be a string")
        
        if len(skill_name) > 50:
            raise ValidationError("Skill name too long")
        
        if not self._skill_pattern.match(skill_name):
            raise ValidationError("Skill name contains invalid characters")
        
        if skill_name not in allowed_skills:
            raise ValidationError(
                ValidationMessages.unknown_skill(skill_name, list(allowed_skills))
            )
    
    def validate_function_name(self, function_name: str, allowed_functions: Set[str]) -> None:
        """Validate bridge function name"""
        if not function_name:
            raise ValidationError("Function name is required")
        
        if not isinstance(function_name, str):
            raise ValidationError("Function name must be a string")
        
        if len(function_name) > 50:
            raise ValidationError("Function name too long")
        
        if not self._function_pattern.match(function_name):
            raise ValidationError("Function name contains invalid characters")
        
        if function_name not in allowed_functions:
            raise ValidationError(
                ValidationMessages.unknown_bridge_function(function_name, list(allowed_functions))
            )
    
    def validate_response_type(self, response_type: str, allowed_types: Set[str]) -> None:
        """Validate response type"""
        if not response_type:
            # Default to json if not specified
            return
        
        if not isinstance(response_type, str):
            raise ValidationError("Response type must be a string")
        
        if len(response_type) > 20:
            raise ValidationError("Response type too long")
        
        if not self._alphanumeric_pattern.match(response_type):
            raise ValidationError("Response type contains invalid characters")
        
        if response_type not in allowed_types:
            raise ValidationError(
                ValidationMessages.unknown_response_type(response_type)
            )
    
    def validate_string_parameter(self, param_name: str, value: Any, 
                                  required: bool = False, max_length: int = None) -> None:
        """Validate string parameter"""
        if value is None:
            if required:
                raise ValidationError(f"Parameter '{param_name}' is required")
            return
        
        if not isinstance(value, str):
            raise ValidationError(f"Parameter '{param_name}' must be a string")
        
        max_len = max_length or self.max_string_length
        if len(value) > max_len:
            raise ValidationError(
                ValidationMessages.field_too_long(param_name, max_len)
            )
    
    def validate_dict_parameter(self, param_name: str, value: Any, 
                                required: bool = False) -> None:
        """Validate dictionary parameter"""
        if value is None:
            if required:
                raise ValidationError(f"Parameter '{param_name}' is required")
            return
        
        if not isinstance(value, dict):
            raise ValidationError(f"Parameter '{param_name}' must be an object")
        
        if len(value) > self.max_params_count:
            raise ValidationError(
                f"Parameter '{param_name}' exceeds maximum parameter count"
            )
        
        self.validate_json_structure(value)
    
    def sanitize_error_message(self, message: str) -> str:
        """Sanitize error messages to remove sensitive information"""
        if not isinstance(message, str):
            return ValidationMessages.INTERNAL_SERVER_ERROR
        
        # Apply sensitive pattern replacements
        sanitized = message
        for pattern, replacement in self._sensitive_patterns:
            sanitized = pattern.sub(replacement, sanitized)
        
        # Truncate very long messages
        if len(sanitized) > 500:
            sanitized = sanitized[:500] + "..."
        
        return sanitized
    
    def sanitize_log_data(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize data for logging by removing sensitive fields"""
        if not isinstance(data, dict):
            return {}
        
        sanitized = {}
        sensitive_keys = {'password', 'token', 'secret', 'key', 'auth', 'api_key', 
                         'access_token', 'refresh_token', 'authorization'}
        
        for key, value in data.items():
            if isinstance(key, str) and key.lower() in sensitive_keys:
                sanitized[key] = "<hidden>"
            elif isinstance(value, dict):
                sanitized[key] = self.sanitize_log_data(value)
            elif isinstance(value, str) and len(value) > 1000:
                sanitized[key] = value[:1000] + "...[truncated]"
            else:
                sanitized[key] = value
        
        return sanitized


class SecurityValidator:
    """Security-focused validator for detecting potential attacks"""
    
    def __init__(self):
        # Common injection patterns
        self.injection_patterns = [
            re.compile(r'<script[^>]*>', re.IGNORECASE),
            re.compile(r'javascript:', re.IGNORECASE),
            re.compile(r'vbscript:', re.IGNORECASE),
            re.compile(r'onload\s*=', re.IGNORECASE),
            re.compile(r'onerror\s*=', re.IGNORECASE),
            re.compile(r'eval\s*\(', re.IGNORECASE),
            re.compile(r'function\s*\(', re.IGNORECASE),
            re.compile(r'\bselect\b.*\bfrom\b', re.IGNORECASE),
            re.compile(r'\binsert\b.*\binto\b', re.IGNORECASE),
            re.compile(r'\bupdate\b.*\bset\b', re.IGNORECASE),
            re.compile(r'\bdelete\b.*\bfrom\b', re.IGNORECASE),
            re.compile(r'\bdrop\b.*\btable\b', re.IGNORECASE),
            re.compile(r'\bunion\b.*\bselect\b', re.IGNORECASE),
            re.compile(r'--\s*$', re.MULTILINE),
            re.compile(r'/\*.*?\*/', re.DOTALL),
        ]
    
    def detect_injection_attempt(self, value: str) -> bool:
        """Detect potential injection attempts in input"""
        if not isinstance(value, str):
            return False
        
        for pattern in self.injection_patterns:
            if pattern.search(value):
                return True
        
        return False
    
    def validate_safe_input(self, data: Dict[str, Any]) -> None:
        """Validate that input doesn't contain injection attempts"""
        def check_value(value: Any) -> None:
            if isinstance(value, str):
                if self.detect_injection_attempt(value):
                    raise ValidationError("Invalid input detected")
            elif isinstance(value, dict):
                for v in value.values():
                    check_value(v)
            elif isinstance(value, list):
                for item in value:
                    check_value(item)
        
        check_value(data)


# Factory functions for dependency injection
def create_rate_limiter() -> RateLimiter:
    """Create rate limiter instance"""
    return RateLimiter()


def create_input_validator() -> InputValidator:
    """Create input validator instance"""
    return InputValidator()


def create_security_validator() -> SecurityValidator:
    """Create security validator instance"""
    return SecurityValidator()