#!/usr/bin/env python3
"""
Architecture Validation Script

Validates the Enaam system architecture including:
- Dependency injection implementation
- Error leakage prevention
- Global state elimination  
- Type safety
- Import structure
- Security measures
"""

import ast
import importlib
import logging
import os
import sys
from pathlib import Path
from typing import List, Dict, Set, Any

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


class ArchitectureValidator:
    """Validates architecture principles and design patterns"""
    
    def __init__(self):
        self.violations = []
        self.warnings = []
        self.successes = []
        
    def log_violation(self, violation: str):
        """Log an architecture violation"""
        self.violations.append(violation)
        
    def log_warning(self, warning: str):
        """Log an architecture warning"""
        self.warnings.append(warning)
        
    def log_success(self, success: str):
        """Log an architecture success"""
        self.successes.append(success)
        
    def validate_dependency_injection(self) -> bool:
        """Validate dependency injection implementation"""
        print("🔍 Validating Dependency Injection...")
        
        try:
            from enaam.core.container import ServiceContainer
            from enaam.core.logging import create_default_logger
            from enaam.core.error_sanitizer import create_error_sanitizer
            
            # Test service container
            container = ServiceContainer()
            self.log_success("Service container imports and creates successfully")
            
            # Test factory functions exist
            logger = create_default_logger()
            sanitizer = create_error_sanitizer()
            
            if logger and sanitizer:
                self.log_success("Factory functions working correctly")
            else:
                self.log_violation("Factory functions not working properly")
                
            return True
            
        except ImportError as e:
            self.log_violation(f"Dependency injection imports failed: {e}")
            return False
        except Exception as e:
            self.log_violation(f"Dependency injection validation failed: {e}")
            return False
    
    def validate_error_leakage_prevention(self) -> bool:
        """Validate error leakage prevention implementation"""
        print("🛡️ Validating Error Leakage Prevention...")
        
        try:
            from enaam.core.error_sanitizer import ErrorSanitizer
            from enaam.core.exceptions import create_safe_error_response
            
            sanitizer = ErrorSanitizer()
            
            # Test sensitive data sanitization
            test_cases = [
                ("password=secret123", "secret123"),
                ("/etc/passwd", "/etc/passwd"),
                ("mysql://user:pass@host", "pass"),
                ("sk-1234567890abcdef", "sk-1234567890abcdef")
            ]
            
            all_sanitized = True
            for content, sensitive_part in test_cases:
                sanitized = sanitizer._sanitize_content(content)
                if sensitive_part in sanitized:
                    self.log_violation(f"Sensitive data '{sensitive_part}' not sanitized in: {content}")
                    all_sanitized = False
                    
            if all_sanitized:
                self.log_success("All sensitive data patterns properly sanitized")
            
            # Test safe error response
            test_error = FileNotFoundError("/secret/path/file.txt")
            correlation_id, safe_response = create_safe_error_response(test_error)
            
            if "/secret/path" not in str(safe_response):
                self.log_success("Safe error responses prevent path leakage")
            else:
                self.log_violation("Safe error responses leak sensitive paths")
                
            if correlation_id and correlation_id.startswith("ERR-"):
                self.log_success("Error correlation IDs generated correctly")
            else:
                self.log_violation("Error correlation IDs not generated properly")
                
            return True
            
        except Exception as e:
            self.log_violation(f"Error leakage prevention validation failed: {e}")
            return False
    
    def validate_global_state_elimination(self) -> bool:
        """Check for global mutable state in core modules"""
        print("🌐 Validating Global State Elimination...")
        
        enaam_path = project_root / "enaam"
        global_state_found = False
        
        # Patterns that indicate global mutable state
        global_patterns = [
            "global ",
            "_instance = ",
            "_cache = ",
            "_state = ",
            "logger = logging.getLogger"  # Should use factories instead
        ]
        
        excluded_files = {
            "__init__.py",  # Package initialization is OK
            "legacy_modules.py",  # Legacy code exception
        }
        
        for py_file in enaam_path.rglob("*.py"):
            if py_file.name in excluded_files:
                continue
                
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                for pattern in global_patterns:
                    if pattern in content:
                        # Check if it's actually problematic
                        if "logger = logging.getLogger" in pattern:
                            # Allow factory function definitions
                            if "def " in content.split(pattern)[0].split('\n')[-1]:
                                continue
                                
                        rel_path = py_file.relative_to(project_root)
                        self.log_warning(f"Potential global state in {rel_path}: '{pattern}'")
                        global_state_found = True
                        
            except Exception as e:
                self.log_warning(f"Could not analyze {py_file}: {e}")
        
        if not global_state_found:
            self.log_success("No problematic global state patterns found")
            
        return not global_state_found
    
    def validate_import_structure(self) -> bool:
        """Validate clean import structure and circular import prevention"""
        print("📦 Validating Import Structure...")
        
        try:
            # Test core imports
            import enaam
            import enaam.core
            import enaam.mcp
            import enaam.integrations
            
            self.log_success("All main package imports work")
            
            # Test specific key modules
            from enaam.core.error_sanitizer import ErrorSanitizer
            from enaam.core.exceptions import create_safe_error_response
            from enaam.mcp.server import MCPServer
            from enaam.integrations.khursheed_bridge import KhursheedBridge
            
            self.log_success("All key module imports work without circular dependencies")
            
            return True
            
        except ImportError as e:
            self.log_violation(f"Import structure issue: {e}")
            return False
        except Exception as e:
            self.log_violation(f"Import validation failed: {e}")
            return False
    
    def validate_security_measures(self) -> bool:
        """Validate security measures implementation"""
        print("🔒 Validating Security Measures...")
        
        try:
            from enaam.core.validation import RateLimiter, InputValidator, SecurityValidator
            
            # Test rate limiting
            limiter = RateLimiter(max_requests=5, window_seconds=60)
            client_ip = "192.168.1.1"
            
            # Should allow up to limit
            allowed_count = 0
            for _ in range(10):
                if limiter.is_allowed(client_ip):
                    allowed_count += 1
                    
            if allowed_count <= 5:
                self.log_success("Rate limiting working correctly")
            else:
                self.log_violation(f"Rate limiting failed: allowed {allowed_count}/10 requests")
            
            # Test input validation
            validator = InputValidator()
            
            # Test injection detection
            security = SecurityValidator()
            
            malicious_inputs = [
                "<script>alert('xss')</script>",
                "'; DROP TABLE users; --",
                "javascript:alert(1)"
            ]
            
            injection_detected = True
            for malicious_input in malicious_inputs:
                if not security.detect_injection_attempt(malicious_input):
                    self.log_violation(f"Failed to detect injection: {malicious_input}")
                    injection_detected = False
                    
            if injection_detected:
                self.log_success("Injection detection working correctly")
                
            return True
            
        except Exception as e:
            self.log_violation(f"Security validation failed: {e}")
            return False
    
    def validate_type_safety(self) -> bool:
        """Validate type hints and type safety"""
        print("🔤 Validating Type Safety...")
        
        # Check for type hints in key modules
        type_hinted_modules = [
            "enaam.core.error_sanitizer",
            "enaam.core.exceptions", 
            "enaam.core.validation",
            "enaam.mcp.schemas"
        ]
        
        all_typed = True
        for module_name in type_hinted_modules:
            try:
                module = importlib.import_module(module_name)
                module_file = Path(module.__file__)
                
                with open(module_file, 'r', encoding='utf-8') as f:
                    content = f.read()
                    
                # Check for basic type hint patterns
                if "from typing import" in content or "import typing" in content:
                    self.log_success(f"Type hints present in {module_name}")
                else:
                    self.log_warning(f"No typing imports in {module_name}")
                    all_typed = False
                    
            except Exception as e:
                self.log_warning(f"Could not check types in {module_name}: {e}")
                all_typed = False
        
        return all_typed
    
    def run_comprehensive_validation(self) -> bool:
        """Run all validation checks"""
        print("🚀 Starting Comprehensive Architecture Validation")
        print("=" * 60)
        
        validations = [
            ("Dependency Injection", self.validate_dependency_injection),
            ("Error Leakage Prevention", self.validate_error_leakage_prevention),
            ("Global State Elimination", self.validate_global_state_elimination),
            ("Import Structure", self.validate_import_structure),
            ("Security Measures", self.validate_security_measures),
            ("Type Safety", self.validate_type_safety),
        ]
        
        all_passed = True
        for name, validation_func in validations:
            try:
                success = validation_func()
                if not success:
                    all_passed = False
                print()
            except Exception as e:
                self.log_violation(f"{name} validation crashed: {e}")
                all_passed = False
                print()
        
        # Print summary
        print("📋 VALIDATION SUMMARY")
        print("=" * 60)
        
        if self.successes:
            print(f"✅ SUCCESSES ({len(self.successes)}):")
            for success in self.successes:
                print(f"   • {success}")
            print()
        
        if self.warnings:
            print(f"⚠️ WARNINGS ({len(self.warnings)}):")
            for warning in self.warnings:
                print(f"   • {warning}")
            print()
        
        if self.violations:
            print(f"❌ VIOLATIONS ({len(self.violations)}):")
            for violation in self.violations:
                print(f"   • {violation}")
            print()
        
        if all_passed and not self.violations:
            print("🎉 ALL ARCHITECTURE VALIDATIONS PASSED!")
            print("✅ System meets architectural requirements")
        else:
            print("❌ ARCHITECTURE VIOLATIONS DETECTED")
            print("🔧 Please address the issues above")
        
        return all_passed and len(self.violations) == 0


def main():
    """Main validation entry point"""
    validator = ArchitectureValidator()
    success = validator.run_comprehensive_validation()
    
    # Exit with appropriate code
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()