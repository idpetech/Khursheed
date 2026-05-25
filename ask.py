#!/usr/bin/env python3
"""CLI interface for querying Khursheed / Hey Eman."""
import os
import sys

from dotenv import load_dotenv

from executive_summary import generate_executive_summary
from llm_agent import HeyEmanAgent
from manager import Manager
from notifications import MarkdownFileNotifier
from skills import (
    EchoSkill, LeadScoutSkill, SifterSkill, TimestampSkill,
    CalculatorSkill, WeatherSkill, FileAnalyzerSkill
)


def main() -> None:
    load_dotenv(override=True)

    if len(sys.argv) < 2:
        print("Usage: python ask.py \"<your question>\"")
        print()
        print("Examples:")
        print("  python ask.py \"executive summary\"")
        print("  python ask.py \"what are my todos today\"")
        print("  python ask.py \"check email\"")
        print("  python ask.py \"run tasks\"")
        sys.exit(1)

    query = " ".join(sys.argv[1:])

    manager = Manager()
    manager.register_many([
        EchoSkill(), 
        LeadScoutSkill(), 
        SifterSkill(), 
        TimestampSkill(),
        CalculatorSkill(),
        WeatherSkill(),
        FileAnalyzerSkill()
    ])

    api_key = os.getenv("OPENAI_API_KEY")
    if api_key:
        agent = HeyEmanAgent(manager, api_key=api_key)
        response = agent.respond(query)
    else:
        response = _handle_query(query, manager)

    print(response)


def _handle_query(query: str, manager: Manager) -> str:
    from datetime import datetime, timezone

    normalized = query.strip().lower()
    if "summary" in normalized:
        return generate_executive_summary(manager, MarkdownFileNotifier())
    if "todo" in normalized:
        import json
        with open("tasks.json", "r") as f:
            tasks = json.load(f).get("tasks", [])
        lines = "\n".join(f"- {t['id']}: {', '.join(t.get('skills', []))}" for t in tasks)
        return "Configured Tasks:\n" + (lines or "No tasks configured.")
    if "check email" in normalized or "check emails" in normalized:
        task_id = f"manual-sifter-{datetime.now(timezone.utc).isoformat()}"
        manager.run_skill("sifter", task_id, {})
        return "Email check complete. Ask for the executive summary for details."
    if "run" in normalized:
        tasks = manager.load_tasks("tasks.json")
        manager.run_tasks(tasks)
        return "Tasks executed. Ask for the executive summary for details."
    return "Try: 'executive summary', 'what are my todos today', 'check email', or 'run tasks'."


if __name__ == "__main__":
    main()
