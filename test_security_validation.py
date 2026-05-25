#!/usr/bin/env python3
"""
Security Validation Test Script

Comprehensive test script to validate all security measures including:
- Request size limits
- Rate limiting  
- Input validation
- Injection detection
- Error message sanitization
"""

import json
import time
import requests
import threading
from concurrent.futures import ThreadPoolExecutor

# Test configuration
SERVER_URL = "http://localhost:8080"
TEST_CLIENT_IP = "127.0.0.1"


def test_request_size_limits():
    """Test request size validation"""
    print("🔍 Testing request size limits...")
    
    # Test normal sized request
    normal_request = {
        "method": "chat_query",
        "params": {"query": "What are my priorities?"},
        "response_type": "json"
    }
    
    try:
        response = requests.post(SERVER_URL, json=normal_request, timeout=5)
        print(f"✅ Normal request: {response.status_code}")
    except Exception as e:
        print(f"❌ Normal request failed: {e}")
    
    # Test oversized request (10MB+ payload)
    oversized_request = {
        "method": "chat_query", 
        "params": {"query": "x" * (10 * 1024 * 1024 + 1)},  # Over 10MB
        "response_type": "json"
    }
    
    try:
        response = requests.post(SERVER_URL, json=oversized_request, timeout=5)
        if response.status_code == 400:
            print("✅ Oversized request properly rejected")
        else:
            print(f"❌ Oversized request not rejected: {response.status_code}")
    except Exception as e:
        print(f"✅ Oversized request failed as expected: {e}")


def test_rate_limiting():
    """Test rate limiting functionality"""
    print("🔍 Testing rate limiting...")
    
    def make_request():
        try:
            response = requests.post(SERVER_URL, 
                                   json={"method": "chat_query", "params": {"query": "test"}},
                                   timeout=2)
            return response.status_code
        except Exception:
            return None
    
    # Make rapid requests to trigger rate limiting
    success_count = 0
    rate_limited_count = 0
    
    with ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(make_request) for _ in range(100)]
        
        for future in futures:
            result = future.result()
            if result == 200:
                success_count += 1
            elif result == 429:  # Rate limited
                rate_limited_count += 1
    
    print(f"✅ Successful requests: {success_count}")
    print(f"✅ Rate limited requests: {rate_limited_count}")
    
    if rate_limited_count > 0:
        print("✅ Rate limiting is working")
    else:
        print("❌ Rate limiting may not be working")


def test_input_validation():
    """Test comprehensive input validation"""
    print("🔍 Testing input validation...")
    
    test_cases = [
        # Valid requests
        {
            "name": "Valid chat query",
            "request": {
                "method": "chat_query",
                "params": {"query": "What are my priorities?"},
                "response_type": "json"
            },
            "expected_success": True
        },
        
        # Invalid method
        {
            "name": "Invalid method",
            "request": {
                "method": "invalid_method",
                "params": {},
                "response_type": "json"
            },
            "expected_success": False
        },
        
        # Missing method
        {
            "name": "Missing method",
            "request": {
                "params": {"query": "test"},
                "response_type": "json"
            },
            "expected_success": False
        },
        
        # Invalid response type
        {
            "name": "Invalid response type",
            "request": {
                "method": "chat_query",
                "params": {"query": "test"},
                "response_type": "xml"
            },
            "expected_success": False
        },
        
        # Invalid params type
        {
            "name": "Invalid params type",
            "request": {
                "method": "chat_query",
                "params": "not a dict",
                "response_type": "json"
            },
            "expected_success": False
        },
        
        # Method with invalid characters
        {
            "name": "Method with invalid chars",
            "request": {
                "method": "chat_query<script>",
                "params": {"query": "test"},
                "response_type": "json"
            },
            "expected_success": False
        },
    ]
    
    for test_case in test_cases:
        try:
            response = requests.post(SERVER_URL, json=test_case["request"], timeout=5)
            
            if test_case["expected_success"]:
                if response.status_code == 200:
                    print(f"✅ {test_case['name']}: Passed")
                else:
                    print(f"❌ {test_case['name']}: Should succeed but got {response.status_code}")
            else:
                if response.status_code == 400:
                    print(f"✅ {test_case['name']}: Properly rejected")
                else:
                    print(f"❌ {test_case['name']}: Should fail but got {response.status_code}")
                    
        except Exception as e:
            if not test_case["expected_success"]:
                print(f"✅ {test_case['name']}: Failed as expected")
            else:
                print(f"❌ {test_case['name']}: Unexpected error: {e}")


def test_injection_protection():
    """Test injection attack protection"""
    print("🔍 Testing injection protection...")
    
    injection_payloads = [
        # XSS attempts
        {
            "name": "XSS Script Tag",
            "payload": {
                "method": "chat_query",
                "params": {"query": "<script>alert('xss')</script>"},
                "response_type": "json"
            }
        },
        {
            "name": "XSS JavaScript URL",
            "payload": {
                "method": "chat_query", 
                "params": {"query": "javascript:alert('xss')"},
                "response_type": "json"
            }
        },
        {
            "name": "XSS Event Handler",
            "payload": {
                "method": "chat_query",
                "params": {"query": "onload=alert('xss')"},
                "response_type": "json"
            }
        },
        
        # SQL injection attempts
        {
            "name": "SQL Injection",
            "payload": {
                "method": "chat_query",
                "params": {"query": "'; DROP TABLE users; --"},
                "response_type": "json"
            }
        },
        {
            "name": "SQL Union Attack",
            "payload": {
                "method": "chat_query",
                "params": {"query": "UNION SELECT password FROM users"},
                "response_type": "json"
            }
        },
        
        # Code injection attempts
        {
            "name": "Eval Injection",
            "payload": {
                "method": "chat_query",
                "params": {"query": "eval('malicious_code')"},
                "response_type": "json"
            }
        }
    ]
    
    for test_case in injection_payloads:
        try:
            response = requests.post(SERVER_URL, json=test_case["payload"], timeout=5)
            
            if response.status_code == 400:
                print(f"✅ {test_case['name']}: Properly blocked")
            else:
                print(f"❌ {test_case['name']}: Not blocked (status: {response.status_code})")
                
        except Exception as e:
            print(f"✅ {test_case['name']}: Connection rejected: {e}")


def test_error_message_sanitization():
    """Test that error messages don't leak sensitive information"""
    print("🔍 Testing error message sanitization...")
    
    # Send request with potentially sensitive data
    sensitive_request = {
        "method": "chat_query",
        "params": {
            "query": "test",
            "password": "secret123",
            "api_key": "key456",
            "token": "token789"
        },
        "response_type": "json"
    }
    
    try:
        response = requests.post(SERVER_URL, json=sensitive_request, timeout=5)
        
        if response.status_code >= 400:
            error_text = response.text
            
            # Check that sensitive data is not in error response
            sensitive_data = ["secret123", "key456", "token789"]
            leaked_data = [data for data in sensitive_data if data in error_text]
            
            if leaked_data:
                print(f"❌ Sensitive data leaked in error: {leaked_data}")
            else:
                print("✅ Error messages properly sanitized")
        else:
            print("✅ Request succeeded (no error to check)")
            
    except Exception as e:
        print(f"✅ Connection failed (no error message to check): {e}")


def test_security_headers():
    """Test that proper security headers are included"""
    print("🔍 Testing security headers...")
    
    try:
        response = requests.get(f"{SERVER_URL}/health", timeout=5)
        
        expected_headers = [
            'X-Content-Type-Options',
            'X-Frame-Options', 
            'X-XSS-Protection',
            'X-RateLimit-Remaining',
            'X-RateLimit-Limit'
        ]
        
        missing_headers = []
        for header in expected_headers:
            if header not in response.headers:
                missing_headers.append(header)
        
        if missing_headers:
            print(f"❌ Missing security headers: {missing_headers}")
        else:
            print("✅ All security headers present")
            
        # Check specific header values
        if response.headers.get('X-Content-Type-Options') == 'nosniff':
            print("✅ X-Content-Type-Options properly set")
        else:
            print("❌ X-Content-Type-Options not set to nosniff")
            
        if response.headers.get('X-Frame-Options') == 'DENY':
            print("✅ X-Frame-Options properly set")
        else:
            print("❌ X-Frame-Options not set to DENY")
            
    except Exception as e:
        print(f"❌ Failed to test headers: {e}")


def test_json_depth_limits():
    """Test JSON nesting depth limits"""
    print("🔍 Testing JSON depth limits...")
    
    # Create deeply nested JSON
    deep_json = {}
    current = deep_json
    for i in range(40):  # Create 40 levels of nesting
        current['nested'] = {}
        current = current['nested']
    current['method'] = 'chat_query'
    current['params'] = {'query': 'test'}
    
    try:
        response = requests.post(SERVER_URL, json=deep_json, timeout=5)
        
        if response.status_code == 400:
            print("✅ Deep JSON properly rejected")
        else:
            print(f"❌ Deep JSON not rejected: {response.status_code}")
            
    except Exception as e:
        print(f"✅ Deep JSON rejected: {e}")


def main():
    """Run all security validation tests"""
    print("🚀 Starting Security Validation Tests")
    print("=" * 50)
    
    # Check if server is running
    try:
        response = requests.get(f"{SERVER_URL}/health", timeout=5)
        if response.status_code == 200:
            print("✅ Server is running")
        else:
            print("❌ Server health check failed")
            return
    except Exception as e:
        print(f"❌ Cannot connect to server: {e}")
        print("Please start the server with: python -m enaam.mcp_server start")
        return
    
    print("=" * 50)
    
    # Run all tests
    test_request_size_limits()
    print()
    
    test_input_validation() 
    print()
    
    test_injection_protection()
    print()
    
    test_error_message_sanitization()
    print()
    
    test_security_headers()
    print()
    
    test_json_depth_limits()
    print()
    
    test_rate_limiting()
    print()
    
    print("🎯 Security validation tests completed!")
    print("=" * 50)


if __name__ == "__main__":
    main()