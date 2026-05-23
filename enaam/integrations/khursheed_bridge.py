"""
Khursheed Bridge - Wrapper for existing Khursheed functionality

This module provides a bridge to call existing Khursheed workflows
without modifying the original implementation.
"""

import sys
import os
import time
from pathlib import Path
from typing import Dict, Any
import json

# Add parent directory to Python path to import Khursheed modules
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from manager import Manager
from executive_summary import generate_executive_summary
from notifications import MarkdownFileNotifier, CompositeNotifier, EmailNotifier
from skills import EchoSkill, LeadScoutSkill, SifterSkill, TimestampSkill

# Import Enaam logger
from ..core.logging import logger


class KhursheedBridge:
    """Bridge to existing Khursheed functionality"""
    
    def __init__(self):
        self._manager = None
        self._initialize_manager()
    
    def _initialize_manager(self):
        """Initialize the Khursheed manager with existing skills"""
        self._manager = Manager()
        self._manager.register_many([
            EchoSkill(),
            LeadScoutSkill(), 
            SifterSkill(),
            TimestampSkill()
        ])
    
    def _log_execution(self, function_name: str, input_data: Dict[str, Any], response: Dict[str, Any], execution_time_ms: int):
        """Log function execution to Enaam logger"""
        try:
            logger.log_execution(
                function_name=function_name,
                source=response.get("source", "khursheed"),
                status=response.get("status", "unknown"),
                input_data=input_data,
                output_data=response,
                execution_time_ms=execution_time_ms,
                error_message=response.get("data", {}).get("error") if response.get("status") == "error" else None
            )
        except Exception as e:
            # Don't fail the main operation if logging fails
            print(f"Warning: Failed to log execution: {e}")
    
    def _execute_with_logging(self, function_name: str, func, input_data: Dict[str, Any] = None):
        """Execute a function with logging wrapper"""
        start_time = time.time()
        try:
            result = func()
            execution_time_ms = int((time.time() - start_time) * 1000)
            self._log_execution(function_name, input_data or {}, result, execution_time_ms)
            return result
        except Exception as e:
            execution_time_ms = int((time.time() - start_time) * 1000)
            error_response = {
                "status": "error",
                "source": "khursheed",
                "action": function_name,
                "data": {"error": str(e)},
                "next_steps": ["Check system configuration", "Review error logs"]
            }
            self._log_execution(function_name, input_data or {}, error_response, execution_time_ms)
            return error_response
    
    def weekly_digest(self) -> Dict[str, Any]:
        """Generate weekly digest using existing weekly_summary.py logic"""
        def _execute():
            # Use the same logic as weekly_summary.py but without email sending
            summary = generate_executive_summary(self._manager, MarkdownFileNotifier())
            return {
                "status": "success",
                "source": "khursheed",
                "action": "weekly_digest",
                "data": {"summary": summary},
                "next_steps": ["Review weekly summary", "Plan upcoming tasks"]
            }
        
        return self._execute_with_logging("weekly_digest", _execute)
    
    def email_summary(self) -> Dict[str, Any]:
        """Check emails using existing sifter skill"""
        def _execute():
            # Run the sifter skill to check emails
            result = self._manager.run_skill("sifter", "enaam-email-check", {})
            
            return {
                "status": "success",
                "source": "khursheed",
                "action": "email_summary", 
                "data": result,
                "next_steps": ["Review flagged emails", "Process expense items"]
            }
        
        return self._execute_with_logging("email_summary", _execute)
    
    # NEW REQUIRED WRAPPER FUNCTIONS
    
    def weekly_monday_9am_digest(self) -> Dict[str, Any]:
        """
        Monday 9 AM weekly digest - wraps the existing weekly_summary.py automation
        This mimics the exact cron job behavior but returns structured response
        """
        def _execute():
            # Check if email sending is configured
            sender = os.getenv("GMAIL_EMAIL")
            password = os.getenv("GMAIL_PASSWORD")
            recipient = os.getenv("SUMMARY_TO")
            
            if sender and password and recipient:
                # Full weekly summary with email (like the cron job)
                notifier = CompositeNotifier(
                    MarkdownFileNotifier(),
                    EmailNotifier(sender=sender, password=password, recipient=recipient)
                )
                summary = generate_executive_summary(self._manager, notifier)
                
                return {
                    "status": "success",
                    "source": "khursheed",
                    "action": "weekly_monday_9am_digest",
                    "data": {
                        "summary": summary,
                        "email_sent": True,
                        "recipient": recipient
                    },
                    "next_steps": ["Check email for delivery", "Review weekly summary"]
                }
            else:
                # Just generate summary without email
                summary = generate_executive_summary(self._manager, MarkdownFileNotifier())
                
                return {
                    "status": "success",
                    "source": "khursheed", 
                    "action": "weekly_monday_9am_digest",
                    "data": {
                        "summary": summary,
                        "email_sent": False,
                        "note": "Email credentials not configured"
                    },
                    "next_steps": ["Configure email settings for full automation", "Review generated summary"]
                }
        
        return self._execute_with_logging("weekly_monday_9am_digest", _execute)
    
    def lead_generation_run(self) -> Dict[str, Any]:
        """
        Lead generation automation - wraps the existing lead_scout skill execution
        This matches the task-003 from tasks.json with 3-day interval
        """
        def _execute():
            # Use the same payload as tasks.json task-003
            payload = {
                "queries": [
                    "Fractional CTO roles in Jacksonville",
                    "Warehouse optimization consulting"
                ]
            }
            
            result = self._manager.run_skill("lead_scout", "enaam-lead-generation", payload)
            
            return {
                "status": "success",
                "source": "khursheed",
                "action": "lead_generation_run",
                "data": result,
                "next_steps": ["Review discovered leads", "Qualify prospects", "Update CRM", "Plan outreach"]
            }
        
        return self._execute_with_logging("lead_generation_run", _execute, 
                                        {"queries": ["Fractional CTO roles in Jacksonville", "Warehouse optimization consulting"]})
    
    def email_triage_run(self) -> Dict[str, Any]:
        """
        Email triage automation - wraps the existing sifter skill for full email processing
        This performs the complete email triage and expense extraction workflow
        """
        def _execute():
            # Run comprehensive email triage
            result = self._manager.run_skill("sifter", "enaam-email-triage", {})
            
            # Process the result to provide better summary
            data = result.copy()
            
            # Add triage summary if available
            if "emails_processed" in result:
                data["triage_summary"] = f"Processed {result.get('emails_processed', 0)} emails"
                
            if "expenses_extracted" in result:
                data["expense_summary"] = f"Extracted {result.get('expenses_extracted', 0)} expense items"
            
            return {
                "status": "success", 
                "source": "khursheed",
                "action": "email_triage_run",
                "data": data,
                "next_steps": ["Review flagged emails", "Process expenses", "Update financial records", "Respond to urgent messages"]
            }
        
        return self._execute_with_logging("email_triage_run", _execute)
    
    def lead_scan(self) -> Dict[str, Any]:
        """Run lead discovery using existing lead_scout skill"""
        def _execute():
            # Default search queries from tasks.json
            payload = {
                "queries": [
                    "Fractional CTO roles in Jacksonville",
                    "Warehouse optimization consulting"
                ]
            }
            
            result = self._manager.run_skill("lead_scout", "enaam-lead-scan", payload)
            
            return {
                "status": "success", 
                "source": "khursheed",
                "action": "lead_scan",
                "data": result,
                "next_steps": ["Review discovered leads", "Prioritize outreach", "Update CRM"]
            }
        
        return self._execute_with_logging("lead_scan", _execute, 
                                        {"queries": ["Fractional CTO roles in Jacksonville", "Warehouse optimization consulting"]})
    
    def executive_summary(self) -> Dict[str, Any]:
        """Generate executive summary using existing logic"""
        def _execute():
            summary = generate_executive_summary(self._manager, MarkdownFileNotifier())
            
            return {
                "status": "success",
                "source": "khursheed",
                "action": "executive_summary",
                "data": {"summary": summary},
                "next_steps": ["Review daily activities", "Plan next actions"]
            }
        
        return self._execute_with_logging("executive_summary", _execute)
    
    def run_scheduled_tasks(self) -> Dict[str, Any]:
        """Run all scheduled Khursheed tasks from tasks.json"""
        def _execute():
            tasks = self._manager.load_tasks("tasks.json")
            self._manager.run_tasks(tasks)
            
            return {
                "status": "success",
                "source": "khursheed", 
                "action": "run_scheduled_tasks",
                "data": {"tasks_executed": len(tasks)},
                "next_steps": ["Review task results", "Generate executive summary"]
            }
        
        return self._execute_with_logging("run_scheduled_tasks", _execute, {"tasks_file": "tasks.json"})
    
    # ENAAM STATE AND LOGGING FUNCTIONS
    
    def get_execution_logs(self, limit: int = 10) -> Dict[str, Any]:
        """Get recent Enaam execution logs"""
        try:
            recent_runs = logger.get_recent_runs(limit)
            stats = logger.get_function_stats()
            
            return {
                "status": "success",
                "source": "enaam",
                "action": "get_execution_logs",
                "data": {
                    "recent_runs": recent_runs,
                    "function_stats": stats,
                    "total_runs": len(recent_runs)
                },
                "next_steps": ["Review execution patterns", "Analyze performance metrics"]
            }
        except Exception as e:
            return {
                "status": "error",
                "source": "enaam",
                "action": "get_execution_logs",
                "data": {"error": str(e)},
                "next_steps": ["Check logging database", "Verify database permissions"]
            }