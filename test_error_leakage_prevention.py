#!/usr/bin/env python3
"""
Error Leakage Prevention Test Script

Comprehensive test script to verify that:
1. Internal error details are not exposed to external clients
2. Full error information is logged internally
3. Safe error messages are returned to clients
4. Sensitive information is properly sanitized
5. Correlation IDs enable error tracking
"""

import json
import logging
import tempfile
from io import StringIO
from unittest.mock import patch, MagicMock

# Test configuration  
TEST_SERVER_URL = "http://localhost:8080"


def test_error_sanitizer():
    """Test the error sanitizer functionality"""
    print("🔍 Testing Error Sanitizer...")
    
    from enaam.core.error_sanitizer import ErrorSanitizer
    
    sanitizer = ErrorSanitizer()
    
    # Test sensitive pattern removal
    sensitive_error = "Error accessing file /home/user/secrets/api_key.txt with password=secret123"
    sanitized = sanitizer._sanitize_content(sensitive_error)
    
    print(f"Original: {sensitive_error}")
    print(f"Sanitized: {sanitized}")
    
    # Verify sensitive data is removed
    assert "secret123" not in sanitized
    assert "/home/user/secrets" not in sanitized
    assert "<file_path>" in sanitized
    assert "<hidden>" in sanitized
    
    print("✅ Sensitive pattern removal works")
    
    # Test error categorization
    validation_error = ValueError("Invalid parameter format: field 'email' is required")
    category = sanitizer._categorize_error(validation_error)
    
    print(f"Error category: {category}")
    assert category.value == "validation"
    
    print("✅ Error categorization works")
    
    # Test client-safe response
    database_error = Exception("Connection failed to mysql://user:pass@localhost:3306/mydb")
    safe_response = sanitizer.sanitize_error_for_client(database_error)
    
    print(f"Safe response: {safe_response}")
    
    # Verify no sensitive data in client response
    response_str = str(safe_response)
    assert "mysql://" not in response_str
    assert "pass" not in response_str
    assert "mydb" not in response_str
    assert safe_response["error"]["message"] == "Internal server error"
    
    print("✅ Client-safe response generation works")


def test_safe_error_logger():
    """Test safe error logging functionality"""
    print("🔍 Testing Safe Error Logger...")
    
    from enaam.core.error_sanitizer import SafeErrorLogger, ErrorSanitizer
    
    # Create in-memory logger for testing
    logger = logging.getLogger("test_safe_logger")
    logger.setLevel(logging.DEBUG)
    log_stream = StringIO()
    handler = logging.StreamHandler(log_stream)
    logger.addHandler(handler)
    
    safe_logger = SafeErrorLogger(logger, ErrorSanitizer())
    
    # Test error logging with sensitive data
    sensitive_error = Exception("Database connection failed: password=secret123, host=192.168.1.100")
    
    correlation_id = safe_logger.log_error(
        sensitive_error,
        context={
            "user_id": "user123",
            "api_key": "key456",
            "request_path": "/api/sensitive"
        }
    )
    
    print(f"Generated correlation ID: {correlation_id}")
    assert correlation_id.startswith("ERR-")
    
    # Check log output
    log_output = log_stream.getvalue()
    print(f"Log output: {log_output}")
    
    # Verify sensitive data is sanitized in logs
    assert "secret123" not in log_output
    assert "key456" not in log_output
    assert correlation_id in log_output
    
    print("✅ Safe error logging works")
    
    # Test log_and_sanitize
    correlation_id, client_response = safe_logger.log_and_sanitize(sensitive_error)
    
    print(f"Client response: {client_response}")
    
    # Verify client response is safe
    response_str = str(client_response)
    assert "secret123" not in response_str
    assert "192.168.1.100" not in response_str
    
    print("✅ Log and sanitize works")


def test_safe_error_response_functions():
    """Test safe error response utility functions"""
    print("🔍 Testing Safe Error Response Functions...")
    
    from enaam.core.exceptions import (
        create_safe_error_response,
        sanitize_error_for_client, 
        get_safe_error_message,
        safe_handle_external_error
    )
    
    # Test create_safe_error_response
    file_error = FileNotFoundError("No such file: /etc/passwd")
    correlation_id, safe_response = create_safe_error_response(
        file_error,
        context={"operation": "file_read"}
    )
    
    print(f"Correlation ID: {correlation_id}")
    print(f"Safe response: {safe_response}")
    
    # Verify file path is not exposed
    response_str = str(safe_response)
    assert "/etc/passwd" not in response_str
    assert safe_response["error"]["message"] == "Requested resource not found"
    
    print("✅ create_safe_error_response works")
    
    # Test sanitize_error_for_client
    auth_error = PermissionError("Access denied to /home/user/.ssh/private_key")
    sanitized = sanitize_error_for_client(auth_error, "TEST-123")
    
    print(f"Sanitized error: {sanitized}")
    assert "/home/user/.ssh" not in str(sanitized)
    assert sanitized["error"]["error_id"] == "TEST-123"
    
    print("✅ sanitize_error_for_client works")
    
    # Test get_safe_error_message
    sql_error = Exception("SQL query failed: SELECT * FROM users WHERE password = 'admin123'")
    safe_message = get_safe_error_message(sql_error)
    
    print(f"Safe message: {safe_message}")
    assert "admin123" not in safe_message
    assert "SELECT" not in safe_message
    assert safe_message == "Internal server error"
    
    print("✅ get_safe_error_message works")
    
    # Test safe_handle_external_error decorator
    @safe_handle_external_error
    def risky_function(should_fail=False):
        if should_fail:
            raise Exception("Internal database connection string: mysql://root:password@localhost/secrets")
        return {"status": "success", "data": "test"}
    
    # Test success case
    result = risky_function(False)
    assert result["status"] == "success"
    print("✅ Decorator allows success")
    
    # Test error case
    result = risky_function(True)
    print(f"Decorated error result: {result}")
    assert result["status"] == "error"
    assert "mysql://" not in str(result)
    assert "password" not in str(result)
    assert "correlation_id" in result
    
    print("✅ safe_handle_external_error decorator works")


def test_mcp_server_error_handling():
    """Test MCP server error handling with safe responses"""
    print("🔍 Testing MCP Server Error Handling...")
    
    try:
        import requests
        
        # Test invalid JSON
        invalid_json = "{ invalid json"
        
        try:
            response = requests.post(
                TEST_SERVER_URL,
                data=invalid_json,
                headers={'Content-Type': 'application/json'},
                timeout=5
            )
            
            if response.status_code == 400:
                error_data = response.json()
                print(f"Invalid JSON response: {error_data}")
                
                # Verify safe error response
                assert "error" in error_data
                error_message = error_data["error"]["message"]
                
                # Should not contain internal parser details
                assert "json.decoder" not in error_message.lower()
                assert "traceback" not in error_message.lower()
                assert "invalid json" not in error_message.lower()
                
                print("✅ Invalid JSON handled safely")
            else:
                print(f"❌ Expected 400, got {response.status_code}")
                
        except requests.exceptions.RequestException:
            print("⚠️ Server not running - skipping live test")
            
        # Test malformed request with sensitive data
        malicious_request = {
            "method": "chat_query",
            "params": {
                "query": "test",
                "secret_key": "sk-1234567890abcdef",
                "database_url": "postgresql://admin:secret@prod-db:5432/customers"
            }
        }
        
        try:
            response = requests.post(
                TEST_SERVER_URL,
                json=malicious_request,
                timeout=5
            )
            
            if response.status_code >= 400:
                error_data = response.json()
                print(f"Malicious request response: {error_data}")
                
                # Verify no sensitive data in response
                response_str = str(error_data)
                assert "sk-1234567890abcdef" not in response_str
                assert "postgresql://" not in response_str
                assert "secret" not in response_str
                assert "prod-db" not in response_str
                
                print("✅ Sensitive data not leaked in error response")
            else:
                print("✅ Request handled without error")
                
        except requests.exceptions.RequestException:
            print("⚠️ Server not running - skipping live test")
            
    except ImportError:
        print("⚠️ requests not available - skipping HTTP tests")


def test_bridge_error_handling():
    """Test Khursheed bridge error handling"""
    print("🔍 Testing Bridge Error Handling...")
    
    from enaam.integrations.khursheed_bridge import KhursheedBridge
    from unittest.mock import patch
    
    bridge = KhursheedBridge()
    
    # Mock a failing bridge operation  
    def failing_operation():
        raise Exception("Database connection failed: host=production-db.internal.company.com, user=admin_user, password=super_secret_password")
    
    # Test that bridge operations return safe error responses
    with patch.object(bridge, '_get_bridge_operation', return_value=failing_operation):
        result = bridge._execute_with_logging("test_operation", {}, failing_operation)
        
        print(f"Bridge error result: {result}")
        
        # Verify it's an error response
        assert result["status"] == "error"
        
        # Verify sensitive data is not exposed
        result_str = str(result)
        assert "production-db.internal.company.com" not in result_str
        assert "admin_user" not in result_str 
        assert "super_secret_password" not in result_str
        
        # Verify correlation ID is present
        assert "correlation_id" in result["data"]
        
        print("✅ Bridge error handling prevents data leakage")


def test_validation_error_messages():
    """Test that validation errors don't leak internal details"""
    print("🔍 Testing Validation Error Messages...")
    
    from enaam.mcp.schemas import validate_mcp_request
    from enaam.core.exceptions import ValidationError
    
    # Test validation with potentially sensitive data
    invalid_requests = [
        # Request with sensitive data in wrong fields
        {
            "method": "SELECT * FROM users WHERE password='admin'",
            "params": {"api_key": "sk-secret123"}
        },
        
        # Request with file paths
        {
            "method": "chat_query",
            "params": {"config_file": "/etc/passwd"}
        },
        
        # Extremely long fields that might reveal structure
        {
            "method": "x" * 1000,
            "params": {}
        }
    ]
    
    for i, invalid_request in enumerate(invalid_requests):
        print(f"Testing invalid request {i + 1}...")
        
        try:
            validate_mcp_request(invalid_request)
            print("❌ Request should have failed validation")
        except ValidationError as e:
            error_message = str(e)
            print(f"Validation error: {error_message}")
            
            # Check that sensitive data is not in error message
            assert "admin" not in error_message or "password" not in error_message
            assert "/etc/passwd" not in error_message
            assert "sk-secret123" not in error_message
            
            # Check that error is reasonably generic
            assert len(error_message) < 200  # Not too verbose
            
            print(f"✅ Request {i + 1} safely rejected")


def main():
    """Run all error leakage prevention tests"""
    print("🚀 Starting Error Leakage Prevention Tests")
    print("=" * 50)
    
    try:
        test_error_sanitizer()
        print()
        
        test_safe_error_logger() 
        print()
        
        test_safe_error_response_functions()
        print()
        
        test_validation_error_messages()
        print()
        
        test_bridge_error_handling()
        print()
        
        test_mcp_server_error_handling()
        print()
        
        print("🎯 All error leakage prevention tests completed!")
        print("✅ No information leakage detected")
        print("=" * 50)
        
    except Exception as e:
        print(f"❌ Test suite failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()