"""
Legacy Modules Bridge - Safe imports for legacy Khursheed modules

This module provides a safe way to import legacy modules from the project root
without using sys.path manipulation. It uses importlib to import modules
from the parent directory.
"""

import importlib.util
import logging
import sys
from pathlib import Path
from typing import Any, Dict, Optional

# Setup logging for legacy module loading
legacy_logger = logging.getLogger('enaam.legacy')

# Get the project root directory (parent of enaam)
_PROJECT_ROOT = Path(__file__).parent.parent

# Cache for loaded modules to avoid repeated imports
_MODULE_CACHE: Dict[str, Any] = {}


def _load_legacy_module(module_name: str, file_path: Optional[Path] = None) -> Any:
    """
    Load a legacy module from the project root using importlib.
    
    Args:
        module_name: Name of the module to load
        file_path: Optional custom path to the module file
        
    Returns:
        The loaded module
    """
    if module_name in _MODULE_CACHE:
        return _MODULE_CACHE[module_name]
    
    if file_path is None:
        file_path = _PROJECT_ROOT / f"{module_name}.py"
    
    if not file_path.exists():
        raise ImportError(f"Legacy module '{module_name}' not found at {file_path}")
    
    # Load the module using importlib
    spec = importlib.util.spec_from_file_location(module_name, file_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Could not load module spec for '{module_name}'")
    
    module = importlib.util.module_from_spec(spec)
    
    # Add to sys.modules to handle relative imports within the legacy module
    full_module_name = f"enaam.legacy.{module_name}"
    sys.modules[full_module_name] = module
    
    # Also add with the original module name for legacy imports
    sys.modules[module_name] = module
    
    # Execute the module
    spec.loader.exec_module(module)
    
    # Cache the loaded module
    _MODULE_CACHE[module_name] = module
    
    return module


def _load_skills_package() -> Any:
    """Load the skills package from the project root."""
    if "skills" in _MODULE_CACHE:
        return _MODULE_CACHE["skills"]
    
    skills_path = _PROJECT_ROOT / "skills"
    if not skills_path.exists() or not (skills_path / "__init__.py").exists():
        raise ImportError(f"Skills package not found at {skills_path}")
    
    # Load the skills package
    spec = importlib.util.spec_from_file_location("skills", skills_path / "__init__.py")
    if spec is None or spec.loader is None:
        raise ImportError("Could not load skills package spec")
    
    skills_module = importlib.util.module_from_spec(spec)
    
    # Add to sys.modules
    sys.modules["enaam.legacy.skills"] = skills_module
    sys.modules["skills"] = skills_module  # For legacy compatibility
    
    # Execute the module  
    spec.loader.exec_module(skills_module)
    
    # Cache the module
    _MODULE_CACHE["skills"] = skills_module
    
    return skills_module


# Load legacy modules safely in the right order (handle dependencies)
# Load dependencies first

# Load manager first (no dependencies)
try:
    manager = _load_legacy_module("manager")
except ImportError as e:
    legacy_logger.warning("Could not load manager module: %s", str(e))
    manager = None

# Load notifications next (no external dependencies) 
try:
    notifications = _load_legacy_module("notifications")
except ImportError as e:
    legacy_logger.warning("Could not load notifications module: %s", str(e))
    notifications = None

# Load executive_summary (depends on manager and notifications)
try:
    executive_summary = _load_legacy_module("executive_summary")
except ImportError as e:
    legacy_logger.warning("Could not load executive_summary module: %s", str(e))
    executive_summary = None

# Load skills package last
try:
    skills = _load_skills_package()
except ImportError as e:
    legacy_logger.warning("Could not load skills package: %s", str(e))
    skills = None


# Export specific classes and functions that are used by the bridge
def get_generate_executive_summary():
    """Get the generate_executive_summary function."""
    if executive_summary is None:
        raise ImportError("Executive summary module not available")
    return getattr(executive_summary, "generate_executive_summary", None)


def get_manager_class():
    """Get the Manager class."""
    if manager is None:
        raise ImportError("Manager module not available")
    return getattr(manager, "Manager", None)


def get_notification_classes():
    """Get notification classes."""
    if notifications is None:
        raise ImportError("Notifications module not available")
    
    return {
        "CompositeNotifier": getattr(notifications, "CompositeNotifier", None),
        "EmailNotifier": getattr(notifications, "EmailNotifier", None), 
        "MarkdownFileNotifier": getattr(notifications, "MarkdownFileNotifier", None),
    }


def get_skill_classes():
    """Get skill classes."""
    if skills is None:
        raise ImportError("Skills package not available")
    
    return {
        "EchoSkill": getattr(skills, "EchoSkill", None),
        "LeadScoutSkill": getattr(skills, "LeadScoutSkill", None),
        "SifterSkill": getattr(skills, "SifterSkill", None), 
        "TimestampSkill": getattr(skills, "TimestampSkill", None),
        "CalculatorSkill": getattr(skills, "CalculatorSkill", None),
        "WeatherSkill": getattr(skills, "WeatherSkill", None),
        "FileAnalyzerSkill": getattr(skills, "FileAnalyzerSkill", None),
    }


__all__ = [
    "executive_summary",
    "manager", 
    "notifications",
    "skills",
    "get_generate_executive_summary",
    "get_manager_class",
    "get_notification_classes", 
    "get_skill_classes",
]