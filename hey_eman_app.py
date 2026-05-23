import json
import logging
import os
from datetime import datetime, timezone

import streamlit as st
from dotenv import load_dotenv

from executive_summary import generate_executive_summary
from llm_agent import HeyEmanAgent
from manager import Manager
from notifications import MarkdownFileNotifier
from skills import EchoSkill, LeadScoutSkill, SifterSkill, TimestampSkill

logger = logging.getLogger(__name__)


@st.cache_resource
def _init_manager() -> Manager:
    manager = Manager()
    manager.register_many([EchoSkill(), LeadScoutSkill(), SifterSkill(), TimestampSkill()])
    return manager


@st.cache_resource
def _init_agent(_manager: Manager) -> HeyEmanAgent:
    return HeyEmanAgent(_manager, api_key=os.getenv("OPENAI_API_KEY"))


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

    load_dotenv(override=True)
    manager = _init_manager()
    agent = _init_agent(manager)

    query = st.text_input("Ask me a command", placeholder="Hey Eman, what are my todos today?")
    if st.button("Submit") and query:
        logger.info("Processing query: %s", query[:80])
        if os.getenv("OPENAI_API_KEY"):
            response = agent.respond(query)
        else:
            response = _handle_query(query, manager)
        st.session_state["last_response"] = response

    if "last_response" in st.session_state:
        st.markdown("### Latest Response")
        st.markdown(st.session_state["last_response"])

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
    main()
