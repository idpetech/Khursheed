#!/usr/bin/env python3
"""CLI interface for querying Khursheed / Hey Eman."""

import os
import sys
from datetime import UTC
from datetime import datetime

from dotenv import load_dotenv

from desk_settings import prepare_desk_tasks
from executive_summary import generate_executive_summary
from llm_agent import HeyEmanAgent
from manager import Manager
from notifications import daily_brief_notifier
from runtime import prepare_runtime
from skills_bootstrap import register_default_skills


def main() -> None:
    load_dotenv(override=True)
    prepare_runtime()

    manager = Manager()
    register_default_skills(manager)

    if len(sys.argv) < 2:
        _interactive(manager)
        return

    query = " ".join(sys.argv[1:])
    print(_answer(query, manager))


def _answer(query: str, manager: Manager) -> str:
    if os.getenv("OPENAI_API_KEY"):
        return HeyEmanAgent(manager).respond(query)
    return _handle_query(query, manager)


def _interactive(manager: Manager) -> None:
    print("Hey Eman. Type a question, or 'exit'.")
    while True:
        try:
            query = input("ask> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not query:
            continue
        if query.lower() in {"exit", "quit"}:
            return
        print(_answer(query, manager))


def _handle_query(query: str, manager: Manager) -> str:
    normalized = query.strip().lower()
    if "summary" in normalized:
        return generate_executive_summary(manager, daily_brief_notifier())
    if "todo" in normalized:
        tasks = manager.load_tasks("tasks.json")
        lines = "\n".join(f"- {task['id']}: {', '.join(task.get('skills', []))}" for task in tasks)
        return "Configured Tasks:\n" + (lines or "No tasks configured.")
    if "check email" in normalized or "check emails" in normalized:
        task_id = f"manual-sifter-{datetime.now(UTC).isoformat()}"
        manager.run_skill("sifter", task_id, {})
        return "Email check complete. Ask for the executive summary for details."
    if "run" in normalized:
        tasks = prepare_desk_tasks(manager.load_tasks("tasks.json"), manager._db_path)
        manager.run_tasks(tasks)
        return "Tasks executed. Ask for the executive summary for details."
    return "Try: 'executive summary', 'what are my todos today', 'check email', or 'run tasks'."


if __name__ == "__main__":
    main()
