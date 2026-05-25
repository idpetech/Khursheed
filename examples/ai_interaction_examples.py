#!/usr/bin/env python3
"""
AI Interaction Examples with Enaam

Examples of how AI systems can interact with Enaam through various interfaces.
"""

import json
import requests
from typing import Dict, Any

# Example server URL (adjust as needed)
ENAAM_SERVER = "http://localhost:8080"


def chat_with_enaam(query: str) -> Dict[str, Any]:
    """
    AI can ask natural language queries to Enaam.
    
    Example use cases:
    - "What are my priorities this week?"
    - "Show me recent email summaries"
    - "Generate executive summary"
    - "Run lead discovery"
    """
    request = {
        "method": "chat_query",
        "params": {"query": query},
        "response_type": "chat",
        "id": f"ai-chat-{hash(query)}"
    }
    
    try:
        response = requests.post(ENAAM_SERVER, json=request, timeout=30)
        return response.json()
    except Exception as e:
        return {"error": str(e)}


def run_enaam_skill(skill_name: str, input_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    AI can execute specific Enaam skills.
    
    Available skills:
    - echo: Simple echo functionality
    - sifter: Email processing and filtering  
    - lead_scout: Lead discovery and analysis
    - timestamp: Add timestamps to data
    """
    request = {
        "method": "run_skill",
        "params": {
            "skill_name": skill_name,
            "input": input_data
        },
        "response_type": "json",
        "id": f"ai-skill-{skill_name}"
    }
    
    try:
        response = requests.post(ENAAM_SERVER, json=request, timeout=60)
        return response.json()
    except Exception as e:
        return {"error": str(e)}


def run_khursheed_bridge_function(function_name: str, params: Dict[str, Any] = None) -> Dict[str, Any]:
    """
    AI can execute Khursheed bridge functions for business operations.
    
    Available functions:
    - email_summary: Process and summarize emails
    - lead_scan: Discover new business leads  
    - weekly_digest: Generate weekly business digest
    - executive_summary: Create executive summary
    - run_scheduled_tasks: Execute scheduled operations
    - weekly_monday_9am_digest: Weekly Monday digest
    - lead_generation_run: Run lead generation workflow
    - email_triage_run: Process email triage
    - get_execution_logs: Get system execution logs
    """
    request = {
        "method": "run_bridge",
        "params": {
            "function_name": function_name,
            "params": params or {}
        },
        "response_type": "json", 
        "id": f"ai-bridge-{function_name}"
    }
    
    try:
        response = requests.post(ENAAM_SERVER, json=request, timeout=120)
        return response.json()
    except Exception as e:
        return {"error": str(e)}


def get_enaam_capabilities() -> Dict[str, Any]:
    """Get available capabilities from Enaam server."""
    try:
        response = requests.get(f"{ENAAM_SERVER}/capabilities", timeout=10)
        return response.json()
    except Exception as e:
        return {"error": str(e)}


def ai_workflow_example():
    """Example AI workflow using Enaam capabilities."""
    print("🤖 AI Workflow Example with Enaam")
    print("=" * 40)
    
    # Step 1: Check capabilities
    print("\\n1. 🔍 Checking Enaam capabilities...")
    capabilities = get_enaam_capabilities()
    if "error" not in capabilities:
        print(f"✅ Available methods: {capabilities.get('methods', [])}")
        print(f"✅ Available skills: {capabilities.get('skills', [])}")
        print(f"✅ Bridge functions: {len(capabilities.get('bridge_functions', []))} available")
    else:
        print("❌ Could not connect to Enaam server")
        print("💡 Start server with: python -m enaam.mcp_server start")
        return
    
    # Step 2: Ask for priorities
    print("\\n2. 💬 Asking about priorities...")
    chat_response = chat_with_enaam("What are my priorities this week?")
    if "error" not in chat_response:
        result = chat_response.get("result", {})
        print(f"✅ Response: {result.get('message', 'No message')}")
    else:
        print(f"❌ Chat error: {chat_response['error']}")
    
    # Step 3: Run weekly digest
    print("\\n3. 📊 Generating weekly digest...")
    digest_response = run_khursheed_bridge_function("weekly_digest")
    if "error" not in digest_response:
        result = digest_response.get("result", {})
        print(f"✅ Status: {result.get('status', 'unknown')}")
        data = result.get("data", {})
        if "summary" in data:
            print(f"✅ Summary: {data['summary'][:100]}...")
    else:
        print(f"❌ Digest error: {digest_response['error']}")
    
    # Step 4: Run lead discovery
    print("\\n4. 🎯 Running lead discovery...")
    lead_response = run_enaam_skill("lead_scout", {"query": "Fractional CTO roles"})
    if "error" not in lead_response:
        result = lead_response.get("result", {})
        print(f"✅ Lead discovery completed: {result.get('status', 'unknown')}")
    else:
        print(f"❌ Lead discovery error: {lead_response['error']}")
    
    print("\\n🎯 AI workflow example completed!")


# Example prompts AI can use with Enaam
AI_PROMPT_EXAMPLES = [
    # Business Operations
    "Generate an executive summary for this week",
    "What are my top priorities right now?", 
    "Show me recent email highlights",
    "Run lead discovery for tech consulting",
    "Process my email backlog and summarize",
    "Generate weekly business digest",
    
    # Data Analysis
    "Analyze execution logs for patterns",
    "Show me system performance metrics", 
    "What tasks completed successfully today?",
    "Identify any error trends in the logs",
    
    # Workflow Management  
    "Run scheduled maintenance tasks",
    "Execute Monday morning digest workflow",
    "Process email triage for urgent items",
    "Update lead generation pipeline",
    
    # Custom Operations
    "Echo test message for system verification",
    "Add timestamps to data processing",
    "Filter emails by priority level",
    "Scout for new business opportunities"
]


def show_ai_integration_patterns():
    """Show different patterns for AI integration."""
    print("🤖 AI Integration Patterns with Enaam")
    print("=" * 45)
    
    print("\\n1. 🗣️ CONVERSATIONAL INTERFACE")
    print("   AI can chat naturally with Enaam:")
    for i, prompt in enumerate(AI_PROMPT_EXAMPLES[:4], 1):
        print(f"   {i}. {prompt}")
    
    print("\\n2. ⚡ DIRECT FUNCTION CALLS") 
    print("   AI can call specific functions:")
    print("   • run_skill('sifter', {'emails': email_data})")
    print("   • run_bridge('executive_summary', {})")
    print("   • run_bridge('lead_generation_run', {'query': 'consulting'})")
    
    print("\\n3. 🔄 WORKFLOW AUTOMATION")
    print("   AI can orchestrate complex workflows:")
    print("   • Check capabilities → Run digest → Process emails → Generate summary")
    print("   • Lead discovery → Email outreach → Follow-up scheduling")
    print("   • Daily operations → Executive reporting → Task prioritization")
    
    print("\\n4. 📊 DATA ANALYSIS")
    print("   AI can analyze system data:")
    print("   • Execution logs analysis")
    print("   • Performance pattern detection")
    print("   • Error trend identification")
    print("   • Business metrics correlation")
    
    print("\\n5. 🛡️ SECURE INTERACTIONS")
    print("   Built-in security features:")
    print("   • Rate limiting (60 req/min)")
    print("   • Input validation and sanitization")
    print("   • Error message sanitization")
    print("   • Correlation ID tracking")


if __name__ == "__main__":
    print("📋 Enaam AI Interaction Examples")
    print("=" * 35)
    print("\\n💡 This script shows how AI can interact with Enaam")
    print("🚀 Start the Enaam server first: python -m enaam.mcp_server start")
    print()
    
    show_ai_integration_patterns()
    print()
    
    # Uncomment to run live example (requires server running)
    # ai_workflow_example()