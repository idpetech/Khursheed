#!/usr/bin/env python3
"""
Enaam Runner - Main entry point

Simple CLI interface to run Enaam Chief-of-Staff system.
"""

import sys
from typing import Any
from typing import Dict

from .core.agent import EnaamAgent
from .core.error_handler import get_error_logger
from .core.logging import create_logger


def main():
    """Main entry point for Enaam"""
    print("🤖 Enaam - Chief of Staff AI System")
    print("=" * 50)
    
    # Initialize logger and agent
    cli_logger = create_logger()
    agent = EnaamAgent()
    
    if len(sys.argv) > 1:
        # Command line mode
        request = " ".join(sys.argv[1:])
        response = agent.process_request(request)
        print_response(response)
    else:
        # Interactive mode
        print("Type 'exit' to quit, 'status' for system status")
        print("Available commands: email summary, lead scan, weekly digest, executive summary, run tasks")
        print()
        
        while True:
            try:
                request = input("Enaam> ").strip()
                
                if request.lower() in ['exit', 'quit', 'q']:
                    print("👋 Goodbye!")
                    break
                elif request.lower() == 'status':
                    response = agent.get_status()
                    print_response(response)
                elif request:
                    cli_logger.debug("Processing interactive request: %s", request)
                    response = agent.process_request(request)
                    print_response(response)
                else:
                    print("Please enter a command.")
                    
            except KeyboardInterrupt:
                print("\n👋 Goodbye!")
                break
            except Exception as e:
                error_logger = get_error_logger('run')
                error_logger.exception("Unexpected error in interactive mode")
                cli_logger.error("Interactive mode error: %s", str(e))
                print(f"❌ Error: {e}")


def print_response(response: Dict[str, Any]) -> None:
    """Pretty print Enaam response"""
    status_icon = "✅" if response.get("status") == "success" else "❌"
    source = response.get("source", "unknown")
    action = response.get("action", "unknown")
    
    print(f"\n{status_icon} [{source.upper()}] {action}")
    print("-" * 40)
    
    # Print data
    data = response.get("data", {})
    if isinstance(data, dict):
        if "summary" in data:
            print("📋 Summary:")
            print(data["summary"])
        elif "message" in data:
            print("💬 Message:")
            print(data["message"])
            if "available_actions" in data:
                print("\n📝 Available Actions:")
                for action in data["available_actions"]:
                    print(f"  • {action}")
        elif "error" in data:
            print(f"⚠️  Error: {data['error']}")
        else:
            # Print other data
            for key, value in data.items():
                if key not in ["summary", "message", "error"]:
                    print(f"📊 {key}: {value}")
    
    # Print next steps
    next_steps = response.get("next_steps", [])
    if next_steps:
        print("\n🎯 Next Steps:")
        for step in next_steps:
            print(f"  • {step}")
    
    print()


if __name__ == "__main__":
    main()