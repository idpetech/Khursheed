"""
Enaam Legacy Package - Compatibility layer for legacy Khursheed modules

This package provides access to legacy Khursheed modules through proper
Python imports instead of sys.path manipulation.

Legacy modules included:
- executive_summary: Executive summary generation
- manager: Main Khursheed manager  
- notifications: Notification system
- skills: All legacy skills
"""

import logging

# Setup logging for legacy component loading
legacy_logger = logging.getLogger('enaam.legacy')

# Re-export legacy modules for backward compatibility
from ..legacy_modules import (
    executive_summary,
    manager, 
    notifications,
    skills,
    get_generate_executive_summary,
    get_manager_class,
    get_notification_classes,
    get_skill_classes,
)

# For easier access to specific functions/classes  
try:
    generate_executive_summary = get_generate_executive_summary()
    Manager = get_manager_class()

    # Get notification classes
    _notif_classes = get_notification_classes()
    CompositeNotifier = _notif_classes["CompositeNotifier"]
    EmailNotifier = _notif_classes["EmailNotifier"]  
    MarkdownFileNotifier = _notif_classes["MarkdownFileNotifier"]

    # Get skill classes
    _skill_classes = get_skill_classes()
    EchoSkill = _skill_classes["EchoSkill"]
    LeadScoutSkill = _skill_classes["LeadScoutSkill"]
    SifterSkill = _skill_classes["SifterSkill"]
    TimestampSkill = _skill_classes["TimestampSkill"]
    CalculatorSkill = _skill_classes["CalculatorSkill"]
    WeatherSkill = _skill_classes["WeatherSkill"]
    FileAnalyzerSkill = _skill_classes["FileAnalyzerSkill"]
    
except (ImportError, AttributeError) as e:
    legacy_logger.warning("Could not load some legacy components: %s", str(e))
    # Create placeholder None values for missing components
    generate_executive_summary = None
    Manager = None
    CompositeNotifier = None
    EmailNotifier = None  
    MarkdownFileNotifier = None
    EchoSkill = None
    LeadScoutSkill = None
    SifterSkill = None
    TimestampSkill = None
    CalculatorSkill = None
    WeatherSkill = None
    FileAnalyzerSkill = None

__all__ = [
    "executive_summary",
    "manager", 
    "notifications", 
    "skills",
    "generate_executive_summary",
    "Manager",
    "CompositeNotifier",
    "EmailNotifier", 
    "MarkdownFileNotifier",
    "EchoSkill",
    "LeadScoutSkill", 
    "SifterSkill",
    "TimestampSkill",
    "CalculatorSkill",
    "WeatherSkill",
    "FileAnalyzerSkill",
]