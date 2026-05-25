import json
import os
from datetime import datetime, timezone

import streamlit as st

from executive_summary import generate_executive_summary
from llm_agent import HeyEmanAgent
from manager import Manager
from notifications import MarkdownFileNotifier
from skills import EchoSkill, LeadScoutSkill, SifterSkill, TimestampSkill


def _load_dotenv(path: str = ".env") -> None:
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            os.environ.setdefault(key.strip(), value.strip())


def _load_tasks(path: str = "tasks.json") -> list[dict]:
    with open(path, "r", encoding="utf-8") as file:
        data = json.load(file)
    return data.get("tasks", [])


def _render_todos(tasks: list[dict]) -> str:
    if not tasks:
        return "No tasks configured."
    return "\n".join(f"- {task['id']}: {', '.join(task.get('skills', []))}" for task in tasks)


def _run_skill_now(manager: Manager, skill_name: str, payload: dict | None = None) -> None:
    task_id = f"manual-{skill_name}-{datetime.now(timezone.utc).isoformat()}"
    manager.run_tasks(
        [
            {
                "id": task_id,
                "skills": [skill_name],
                "payload": payload or {},
            }
        ]
    )


def _handle_query(query: str, manager: Manager) -> str:
    normalized = query.strip().lower()
    if "summary" in normalized:
        return generate_executive_summary(manager, MarkdownFileNotifier())
    if "todo" in normalized:
        tasks = _load_tasks()
        return "### Configured Tasks\n" + _render_todos(tasks)
    if "check email" in normalized or "check emails" in normalized:
        _run_skill_now(manager, "sifter")
        return "Email check complete. Ask for the executive summary for details."
    if "run" in normalized:
        tasks = manager.load_tasks("tasks.json")
        manager.run_tasks(tasks)
        return "Tasks executed. Ask for the executive summary for details."
    return "Try: 'executive summary', 'what are my todos today', or 'run tasks'."


def main() -> None:
    st.set_page_config(page_title="Hey Eman", page_icon="📬")
    st.title("Hey Eman")
    st.caption("Lightweight command center for Khursheed.")

    _load_dotenv()
    manager = Manager()
    manager.register_many([EchoSkill(), LeadScoutSkill(), SifterSkill(), TimestampSkill()])
    agent = HeyEmanAgent(manager)

    query = st.text_input("Ask me a command", placeholder="Hey Eman, what are my todos today?")
    if st.button("Submit") and query:
        if os.getenv("OPENAI_API_KEY"):
            try:
                response = agent.respond(query)
            except Exception as e:
                st.warning(f"OpenAI API failed: {str(e)[:100]}... Falling back to simple commands.")
                response = _handle_query(query, manager)
        else:
            response = _handle_query(query, manager)
        st.markdown(response)

    st.markdown("---")
    st.subheader("Quick Actions")
    if st.button("Run Tasks Now"):
        tasks = manager.load_tasks("tasks.json")
        manager.run_tasks(tasks)
        st.success("Tasks executed.")
    if st.button("Check Email Now"):
        _run_skill_now(manager, "sifter")
        st.success("Email check complete.")
    if st.button("Generate Executive Summary"):
        report = generate_executive_summary(manager, MarkdownFileNotifier())
        st.markdown(report)
    st.caption(f"Last refreshed: {datetime.now(timezone.utc).isoformat()}")


if __name__ == "__main__":
    # Legacy app - use development port to avoid conflict with main Enaam UI
    import sys
    if "--server.port" not in sys.argv and "--server-port" not in sys.argv:
        sys.argv.extend(["--server.port", "8510"])
    main()
